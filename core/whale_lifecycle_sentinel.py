import os
import sys
import json
import time
import requests
import datetime
import threading

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8918704289:AAFg33hZSpa0XrUTFah4TakDBx6ryrAHHgU")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "7736288854")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whale_lifecycle_state.json")

_STATE_LOCK = threading.RLock()

# Import local data engines
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import coinbase_institutional_radar as cir
    import whale_smart_tracker as wst
except Exception as e:
    cir = None
    wst = None
    print(f"Warning importing local modules: {e}")

try:
    from market_cache import get_market_cache, TTL_TICKER, TTL_KLINES, TTL_DERIVATIVES
except ImportError:
    try:
        from core.market_cache import get_market_cache, TTL_TICKER, TTL_KLINES, TTL_DERIVATIVES
    except ImportError:
        get_market_cache = None

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=12)
        res = r.json()
        return res.get("ok", False)
    except Exception as e:
        print(f"Error sending to Telegram: {e}")
        return False

def load_state():
    with _STATE_LOCK:
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "regime": "NONE",
            "last_alert_regime": "NONE",
            "last_alert_time": 0,
            "last_entry_price": 0.0,
            "last_vwap": 0.0,
            "defense_ceiling": 0.0,
            "last_oi": 0.0
        }

def save_state(s):
    tmp_path = f"{STATE_FILE}.tmp.{os.getpid()}_{threading.get_ident()}_{time.time()}"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(s, f, indent=2, ensure_ascii=False)
        for attempt in range(3):
            try:
                with _STATE_LOCK:
                    os.replace(tmp_path, STATE_FILE)
                break
            except (OSError, PermissionError) as pe:
                if attempt < 2:
                    time.sleep(0.01)
                else:
                    raise pe
        return True
    except Exception as e:
        print(f"Error saving lifecycle state: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False

def get_market_metrics():
    headers = {'User-Agent': 'Mozilla/5.0'}
    cache = get_market_cache() if get_market_cache else None
    
    try:
        # 1. Binance Futures Ticker & OI
        if cache:
            ticker_res = cache.cached_get_json('https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT', headers=headers, timeout=8, ttl=TTL_TICKER)
            curr_price = float(ticker_res['lastPrice'])
            
            oi_res = cache.cached_get_json('https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT', headers=headers, timeout=8, ttl=TTL_DERIVATIVES)
            curr_oi = float(oi_res['openInterest'])

            oi_hist = cache.cached_get_json('https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=6', headers=headers, timeout=8, ttl=TTL_DERIVATIVES)
        else:
            ticker_res = requests.get('https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT', headers=headers, timeout=8).json()
            curr_price = float(ticker_res['lastPrice'])
            
            oi_res = requests.get('https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT', headers=headers, timeout=8).json()
            curr_oi = float(oi_res['openInterest'])

            oi_hist = requests.get('https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=6', headers=headers, timeout=8).json()

        ois = [float(x.get('sumOpenInterest', 0)) for x in oi_hist] if oi_hist else [curr_oi]
        oi_peak_6h = max(max(ois), curr_oi)
        oi_drop = max(0.0, oi_peak_6h - curr_oi)
        
        # 2. Ratios
        if cache:
            global_ls = cache.cached_get_json('https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=5m&limit=1', headers=headers, timeout=8, ttl=TTL_DERIVATIVES)
            top_pos_ls = cache.cached_get_json('https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol=BTCUSDT&period=5m&limit=1', headers=headers, timeout=8, ttl=TTL_DERIVATIVES)
        else:
            global_ls = requests.get('https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=5m&limit=1', headers=headers, timeout=8).json()
            top_pos_ls = requests.get('https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol=BTCUSDT&period=5m&limit=1', headers=headers, timeout=8).json()

        retail_long_pct = float(global_ls[0]['longAccount']) * 100 if global_ls else 50.0
        top_pos_ratio = float(top_pos_ls[0]['longShortRatio']) if top_pos_ls else 1.0
        
        # 3. Klines 1h for 6h and 24h short/long VWAP
        if cache:
            klines_res = cache.cached_get_json('https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=24', headers=headers, timeout=8, ttl=TTL_KLINES)
        else:
            klines_res = requests.get('https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=24', headers=headers, timeout=8).json()

        last_6 = klines_res[-6:] if len(klines_res) >= 6 else klines_res
        
        ts_vol_6h = sum(float(k[5]) - float(k[9]) for k in last_6)
        ts_quote_6h = sum(float(k[7]) - float(k[10]) for k in last_6)
        short_vwap_6h = ts_quote_6h / ts_vol_6h if ts_vol_6h > 0 else curr_price
        
        tb_vol_6h = sum(float(k[9]) for k in last_6)
        tb_quote_6h = sum(float(k[10]) for k in last_6)
        long_vwap_6h = tb_quote_6h / tb_vol_6h if tb_vol_6h > 0 else curr_price
        
        fut_delta_6h = tb_vol_6h - ts_vol_6h
        
        defense_ceiling = round(max(short_vwap_6h + 80.0, max(float(k[2]) for k in last_6)), 1)
        defense_floor = round(min(long_vwap_6h - 80.0, min(float(k[3]) for k in last_6)), 1)

        # Dynamic 24h High, Low, POC wick and Range
        high_24h = max(float(k[2]) for k in klines_res) if klines_res else curr_price * 1.02
        low_24h = min(float(k[3]) for k in klines_res) if klines_res else curr_price * 0.98
        poc_wick = round((high_24h + low_24h) / 2.0, 1)
        macro_u = round(high_24h, 1)
        macro_l = round(low_24h, 1)
        
        # 4. Spot Data
        cb_data = cir.analyze_coinbase_flow() if cir else {}
        cb_premium = cb_data.get('current_premium', -100.0)
        cb_spot_delta = cb_data.get('last_100_delta_btc', 0.0)
        
        whale_inv = wst.analyze_whale_inventory() if wst else {}
        real_spot_bag = whale_inv.get('real_spot_bag', {})
        real_spot_net = real_spot_bag.get('net_btc', 0.0)
        bn_spot_delta = real_spot_bag.get('binance_spot_delta', 0.0)
        
        return {
            "status": "ONLINE",
            "price": curr_price,
            "oi": curr_oi,
            "oi_drop": round(oi_drop, 1),
            "oi_peak": round(oi_peak_6h, 1),
            "retail_long_pct": retail_long_pct,
            "top_pos_ratio": top_pos_ratio,
            "fut_delta_6h": fut_delta_6h,
            "short_vwap_6h": round(short_vwap_6h, 1),
            "long_vwap_6h": round(long_vwap_6h, 1),
            "defense_ceiling": defense_ceiling,
            "defense_floor": defense_floor,
            "poc_wick": poc_wick,
            "macro_u": macro_u,
            "macro_l": macro_l,
            "cb_premium": round(cb_premium, 1),
            "cb_spot_delta": round(cb_spot_delta, 1),
            "bn_spot_delta": round(bn_spot_delta, 1),
            "real_spot_net": round(real_spot_net, 1)
        }
    except Exception as e:
        print(f"Error fetching market metrics in lifecycle sentinel: {e}")
        return {
            "status": "DATA_OFFLINE",
            "price": 0.0,
            "oi": 0.0,
            "oi_drop": 0.0,
            "oi_peak": 0.0,
            "retail_long_pct": 50.0,
            "top_pos_ratio": 1.0,
            "fut_delta_6h": 0.0,
            "short_vwap_6h": 0.0,
            "long_vwap_6h": 0.0,
            "defense_ceiling": 0.0,
            "defense_floor": 0.0,
            "poc_wick": 0.0,
            "macro_u": 0.0,
            "macro_l": 0.0,
            "cb_premium": 0.0,
            "cb_spot_delta": 0.0,
            "bn_spot_delta": 0.0,
            "real_spot_net": 0.0
        }

def check_whale_lifecycle(force_send=False):
    m = get_market_metrics()
    state = load_state()
    now_ts = int(time.time())
    now_str = datetime.datetime.now().strftime("%I:%M %p | %d %b %Y")
    
    prev_regime = state.get("regime", "NONE")
    prev_oi = state.get("last_oi", m["oi"])
    oi_delta = m["oi"] - prev_oi
    
    print(f"📊 [WHALE LIFECYCLE AUDIT] Price: ${m['price']} | Retail Long: {m['retail_long_pct']}% | Top Pos: {m['top_pos_ratio']} | Fut Delta: {m['fut_delta_6h']:+.1f} BTC | Spot Net: {m['real_spot_net']:+.1f} BTC | CB Prem: ${m['cb_premium']:+.1f}")
    
    # Classification Logic
    # 1. Genuine Whale Long Entry
    is_whale_long = (
        (m['real_spot_net'] > 40.0 or m['bn_spot_delta'] > 60.0) and
        (m['cb_premium'] > -15.0) and
        (m['fut_delta_6h'] > 30.0) and
        (m['retail_long_pct'] < 64.0)
    )
    
    # 2. Whale Short Hedge / Institutional Dump Entry
    is_whale_short = (
        (m['fut_delta_6h'] < -120.0) and
        (m['retail_long_pct'] >= 60.0) and
        ((m['cb_premium'] < -35.0) or (m['bn_spot_delta'] > 50.0 and m['fut_delta_6h'] < -200.0) or (m['real_spot_net'] < -20.0))
    )
    
    # 3. Short Squeeze / Short Exit Trigger
    is_short_exit = (
        (prev_regime == "WHALE_SHORT") and
        (m['price'] > state.get('defense_ceiling', 999999.0))
    )
    
    # 4. Long Distribution / Long Exit Trigger
    is_long_exit = (
        (prev_regime == "WHALE_LONG") and
        ((m['cb_premium'] < -50.0) or (m['real_spot_net'] < 0.0 and m['price'] > state.get('last_entry_price', 0.0) + 500.0))
    )

    detected_regime = "NONE"
    if is_whale_short:
        detected_regime = "WHALE_SHORT"
    elif is_whale_long:
        detected_regime = "WHALE_LONG"
    else:
        detected_regime = "NEUTRAL"
        
    state["regime"] = detected_regime
    state["last_oi"] = m["oi"]
    
    # Trigger Notifications
    
    # SCENARIO A: NEW WHALE SHORT ENTRY
    if (detected_regime == "WHALE_SHORT" and (state.get("last_alert_regime") != "WHALE_SHORT" or force_send or (now_ts - state.get("last_alert_time", 0) > 28800))):
        hedge_ratio = abs(m['fut_delta_6h']) / max(1.0, abs(m['real_spot_net'])) if m['real_spot_net'] != 0 else 1.0
        msg = (
            f"🔴 🛡️ <b>[WHALE SHORT HEDGE / INSTITUTIONAL DUMP INITIATED]</b> 🛡️ 🔴\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ <b>সময়:</b> {now_str} (Dhaka Time)\n"
            f"🪙 <b>অ্যাসেট:</b> #BTCUSDT | <b>বর্তমান প্রাইস:</b> <code>${m['price']:,.1f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏛️ <b>তিমিদের শর্ট এন্ট্রির লাইভ প্রমাণ:</b>\n"
            f"├─ 🩸 <b>ফিউচার্স শর্ট ডেল্টা (6h):</b> <code>{m['fut_delta_6h']:+,.1f} BTC (ভারী শর্ট পুশ)</code>\n"
            f"├─ 🔒 <b>শর্ট হেজ রেশিও:</b> <code>{hedge_ratio:.1f}x Over-Hedged (প্রটেকশন লকড)</code>\n"
            f"├─ 🇺🇸 <b>Coinbase Premium:</b> <code>${m['cb_premium']:+.1f} USD (ইউএস ডিসকাউন্টে ডাম্প)</code>\n"
            f"├─ 👥 <b>Retail Sentiment:</b> <code>{m['retail_long_pct']:.1f}% LONG (রিটেইলাররা লং ফাঁদে বন্দী)</code>\n"
            f"└─ 🐋 <b>Whale Position Ratio:</b> <code>{m['top_pos_ratio']:.2f} (টপ তিমিদের শর্ট ডমিনেন্স)</code>\n\n"
            f"🎯 <b>ট্রেড সেটআপ (Whale Short Execution Plan):</b>\n"
            f"├─ 📤 <b>তিমিদের শর্ট এন্ট্রি VWAP:</b> <code>${m['short_vwap_6h']:,.1f}</code>\n"
            f"├─ 🛡️ <b>ডিফেন্স সিলিং (Stop / Invalidation):</b> <code>${m['defense_ceiling']:,.1f}</code>\n"
            f"├─ 🎯 <b>টার্গেট ১ (TP1):</b> <code>${(m['price'] - 450):,.1f}</code>\n"
            f"└─ 🎯 <b>টার্গেট ২ (TP2):</b> <code>${(m['price'] - 1100):,.1f}</code>\n\n"
            f"💡 <b>বস, অ্যাকশন প্ল্যান:</b>\n"
            f"<i>রিটেইলাররা ৬৮%+ লং ফাঁদে আটকে আছে। তিমিরা ফিউচার্সে ভারী শর্ট ডেল্টা পুশ করছে। বাউন্স পেলেই তিমিদের সাথে শর্ট অপরচুনিটি খুঁজুন। ভুলেও লং করবেন না!</i>"
        )
        if send_telegram(msg):
            print("🚀 Successfully sent WHALE SHORT HEDGE alert to Telegram!")
            state["last_alert_regime"] = "WHALE_SHORT"
            state["last_alert_time"] = now_ts
            state["last_entry_price"] = m["price"]
            state["last_vwap"] = m["short_vwap_6h"]
            state["defense_ceiling"] = m["defense_ceiling"]
            save_state(state)
            
    # SCENARIO B: NEW WHALE LONG ENTRY
    elif (detected_regime == "WHALE_LONG" and (state.get("last_alert_regime") != "WHALE_LONG" or force_send or (now_ts - state.get("last_alert_time", 0) > 28800))):
        msg = (
            f"🟢 🚀 <b>[INSTITUTIONAL WHALE LONG INITIATED — UNHEDGED PUMP]</b> 🚀 🟢\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ <b>সময়:</b> {now_str} (Dhaka Time)\n"
            f"🪙 <b>অ্যাসেট:</b> #BTCUSDT | <b>বর্তমান প্রাইস:</b> <code>${m['price']:,.1f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏛️ <b>তিমিদের লং এন্ট্রির লাইভ প্রমাণ:</b>\n"
            f"├─ 🩸 <b>Real Spot Accumulation:</b> <code>{m['real_spot_net']:+,.1f} BTC (আসল স্পট ক্যাশ বাই)</code>\n"
            f"├─ 🇺🇸 <b>Coinbase Premium:</b> <code>${m['cb_premium']:+.1f} USD (US স্মার্ট মানি প্রিমিয়ামে বাই করছে)</code>\n"
            f"├─ 🌐 <b>Futures Taker Flow:</b> <code>{m['fut_delta_6h']:+,.1f} BTC (কোনো শর্ট হেজ নেই—আনহেজড!)</code>\n"
            f"├─ 🐋 <b>Top Trader Long Ratio:</b> <code>{m['top_pos_ratio']:.2f} (তিমিরা লং পজিশন বাড়াচ্ছে)</code>\n"
            f"└─ 👥 <b>Retail Sentiment:</b> <code>{m['retail_long_pct']:.1f}% Long (রিটেইল ক্রাউড ছাড়া ফ্রেশ মুভ)</code>\n\n"
            f"🎯 <b>ট্রেড সেটআপ (Whale Long Execution Plan):</b>\n"
            f"├─ 📥 <b>তিমিদের লং এন্ট্রি VWAP:</b> <code>${m['long_vwap_6h']:,.1f}</code>\n"
            f"├─ 🛑 <b>ইনভ্যালিডেশন / স্টপলস:</b> <code>${m['defense_floor']:,.1f}</code>\n"
            f"├─ 🎯 <b>টার্গেট ১ (TP1):</b> <code>${(m['price'] + 650):,.1f}</code>\n"
            f"└─ 🎯 <b>টার্গেট ২ (TP2):</b> <code>${(m['price'] + 1400):,.1f}</code>\n\n"
            f"💡 <b>বস, অ্যাকশন প্ল্যান:</b>\n"
            f"<i>তিমিরা কোনো শর্ট হেজ ছাড়া উন্মুক্ত স্পট ক্যাশ বাই করেছে। মার্কেট পাম্প করিয়ে উপরে প্রফিট বুক করাই তাদের উদ্দেশ্য। পুলব্যাকে নিরাপদে তিমিদের সাথে লং এন্ট্রি নিন!</i>"
        )
        if send_telegram(msg):
            print("🚀 Successfully sent WHALE LONG alert to Telegram!")
            state["last_alert_regime"] = "WHALE_LONG"
            state["last_alert_time"] = now_ts
            state["last_entry_price"] = m["price"]
            state["last_vwap"] = m["long_vwap_6h"]
            state["defense_floor"] = m["defense_floor"]
            save_state(state)

    # SCENARIO C: SHORT EXIT / SHORT SQUEEZE TRIGGER
    elif is_short_exit:
        msg = (
            f"🚨 🚀 <b>[WHALE SHORT DEFENSE BROKEN — SHORT SQUEEZE SURGE!]</b> 🚀 🚨\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ <b>সময়:</b> {now_str} (Dhaka Time)\n"
            f"🪙 <b>অ্যাসেট:</b> #BTCUSDT | <b>বর্তমান প্রাইস:</b> <code>${m['price']:,.1f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⚡ <b>শর্ট কভারিং ও স্কুইজের প্রমাণ:</b>\n"
            f"├─ 🛡️ <b>ডিফেন্স সিলিং পার:</b> <code>${m['price']:,.1f} > ${state.get('defense_ceiling', 0):,.1f}</code>\n"
            f"├─ 💥 <b>Whale Shorts Underwater:</b> তিমিদের শর্ট পজিশন লোকসানে পড়েছে!\n"
            f"├─ 📉 <b>Forced Buy-to-Cover:</b> শর্ট লিকুইডেশন এড়াতে তিমিরা মার্কেট বাই করছে\n"
            f"└─ 🎯 <b>পরবর্তী লিকুইডেশন ম্যাগনেট:</b> <code>${m['price'] * 1.015:,.0f} - ${m['price'] * 1.025:,.0f} (Dynamic Squeeze Target)</code>\n\n"
            f"💡 <b>বস, অ্যাকশন প্ল্যান:</b>\n"
            f"<i>তিমিদের শর্ট ডিফেন্স ভেঙে গেছে! আপনার যদি কোনো শর্ট পজিশন থাকে, অবিলম্বে এক্সিট করুন। মার্কেট দ্রুত উপরের দিকে স্কুইজ হতে পারে!</i>"
        )
        if send_telegram(msg):
            print("🚀 Successfully sent SHORT SQUEEZE EXIT alert to Telegram!")
            state["regime"] = "SQUEEZING"
            state["last_alert_regime"] = "SHORT_SQUEEZE"
            state["last_alert_time"] = now_ts
            save_state(state)

    # SCENARIO D: LONG EXIT / DISTRIBUTION TRIGGER
    elif is_long_exit:
        msg = (
            f"⚠️ 📤 <b>[WHALE LONG EXIT / PROFIT TAKING DETECTED]</b> 📤 ⚠️\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ <b>সময়:</b> {now_str} (Dhaka Time)\n"
            f"🪙 <b>অ্যাসেট:</b> #BTCUSDT | <b>বর্তমান প্রাইস:</b> <code>${m['price']:,.1f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🚨 <b>প্রস্থান অ্যালার্ট (Whales are Cashing Out):</b>\n"
            f"├─ 🩸 <b>Spot CVD Divergence:</b> প্রাইস উপরে উঠলেও স্পট ক্যাশ ফ্লো ডাম্প শুরু হয়েছে!\n"
            f"├─ 🇺🇸 <b>Coinbase Inflow Stop:</b> প্রিমিয়াম ড্রপ করেছে (US স্মার্ট মানি ক্যাশ আউট করছে)\n"
            f"└─ 🎯 <b>রেজিস্ট্যান্স ডিস্ট্রিবিউশন:</b> রিটেইল বায়ারদের কাছে মাল হ্যান্ডওভার চলছে\n\n"
            f"💡 <b>বস, অ্যাকশন প্ল্যান:</b>\n"
            f"<i>তিমিরা তাদের লং থেকে প্রফিট লক করে মার্কেট থেকে বের হয়ে যাচ্ছে! অবিলম্বে আপনার লং ট্রেড ক্লোজ করুন অথবা ট্রেইলিং স্টপলস একদম টাইট করে নিন!</i>"
        )
        if send_telegram(msg):
            print("🚀 Successfully sent WHALE LONG EXIT alert to Telegram!")
            state["regime"] = "DISTRIBUTING"
            state["last_alert_regime"] = "LONG_EXIT"
            state["last_alert_time"] = now_ts
            save_state(state)

    # SCENARIO E: WHALE SHORT TAKE-PROFIT / UNWINDING TRIGGER
    elif (prev_regime == "WHALE_SHORT" and m.get("oi_drop", 0) >= 600.0 and (now_ts - state.get("last_unwind_time", 0) > 7200)):
        msg = (
            f"⚠️ 📤 <b>[WHALE SHORT UNWINDING / TAKE-PROFIT DETECTED]</b> 📤 ⚠️\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ <b>সময়:</b> {now_str} (Dhaka Time)\n"
            f"🪙 <b>অ্যাসেট:</b> #BTCUSDT | <b>বর্তমান প্রাইস:</b> <code>${m['price']:,.1f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🚨 <b>তিমির শর্ট ক্লোজের লাইভ প্রমাণ:</b>\n"
            f"├─ 📉 <b>ওপেন ইন্টারেস্ট ড্রপ:</b> <code>-{m['oi_drop']:,.0f} BTC (পিক থেকে ক্লোজড)</code>\n"
            f"├─ 🩸 <b>শর্ট কভারিং স্ট্যাটাস:</b> <code>তিমিরা আংশিক শর্ট ক্লোজ করে প্রফিট নিচ্ছে</code>\n"
            f"└─ 🎯 <b>বর্তমান OI:</b> <code>{m['oi']:,.0f} BTC</code>\n\n"
            f"💡 <b>বস, অ্যাকশন প্ল্যান:</b>\n"
            f"<i>তিমিরা নিচে প্রফিট লক করা শুরু করেছে! আপনিও আপনার শর্ট থেকে কিছু প্রফিট বুক করে নিন অথবা স্টপলস একদম টাইট করে এন্ট্রি প্রাইসে নিয়ে আসুন!</i>"
        )
        if send_telegram(msg):
            print("🚀 Successfully sent WHALE SHORT UNWIND alert to Telegram!")
            state["last_unwind_time"] = now_ts
            save_state(state)
            
    # 5. INSTITUTIONAL ICEBERG SENTINEL (LIVE NOTICE DISPATCH)
    try:
        import iceberg_order_engine as ioe
        raw_ice = ioe.scan_live_icebergs(m["price"], m["cb_premium"])
        buff_ice = ioe.update_rolling_buffer(raw_ice, m["price"])
        analytics_ice = ioe.compute_iceberg_analytics(buff_ice, m["price"])
        sniper_ice = ioe.calibrate_sniper_setup(
            curr_price=m["price"],
            market_regime=detected_regime,
            def_ceiling=m["defense_ceiling"],
            def_floor=m["defense_floor"],
            macro_l=m.get("macro_l", m["price"] * 0.98),
            macro_u=m.get("macro_u", m["price"] * 1.02),
            poc_wick=m.get("poc_wick", m["price"]),
            iceberg_analytics=analytics_ice
        )
        ioe.check_and_send_iceberg_alert(m["price"], m["cb_premium"], sniper_ice, analytics_ice, force_send=force_send)
    except Exception as e_ice:
        print(f"Error checking iceberg sentinel: {e_ice}")

    save_state(state)
    return m

if __name__ == '__main__':
    force = "--force" in sys.argv
    check_whale_lifecycle(force_send=force)
