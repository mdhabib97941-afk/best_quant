import os
import sys
import time
import json
import requests
import urllib.request
import threading

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Ensure core directory in sys.path
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

TELEGRAM_BOT_TOKEN = "8918704289:AAFg33hZSpa0XrUTFah4TakDBx6ryrAHHgU"
TELEGRAM_CHAT_ID = "7736288854"
STATE_FILE = os.path.join(CORE_DIR, "short_squeeze_state.json")
_LOCK = threading.RLock()


def get_json(url, timeout=8):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
    return None


def send_telegram(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json().get("ok", False)
    except Exception as e:
        print(f"Error sending Telegram notice: {e}")
        return False


def load_state():
    with _LOCK:
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "last_alert_ts": 0,
            "last_alert_price": 0.0,
            "is_squeeze_active": False,
            "last_trigger_reason": "None"
        }


def save_state(state):
    with _LOCK:
        tmp_file = f"{STATE_FILE}.tmp.{os.getpid()}"
        try:
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_file, STATE_FILE)
        except Exception as e:
            print(f"Error saving state: {e}")
            if os.path.exists(tmp_file):
                try: os.remove(tmp_file)
                except Exception: pass


def check_short_squeeze_signals():
    """
    Institutional Short Squeeze & Resistance Bait Detector:
    1. Filters out false alarms when Coinbase Premium is heavily negative (Fake Bounces)
    2. Identifies Whale Resistance Traps (bounces intended to lure retail to buy resistance)
    3. Requires genuine Taker Buy Delta explosion (>= +800 BTC) and volume surge for true squeeze
    """
    # 1. Fetch 1H klines
    klines_1h = get_json('https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=15')
    if not klines_1h or len(klines_1h) < 12:
        return None
    
    # 2. Fetch 15M klines
    klines_15m = get_json('https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=15m&limit=10')
    if not klines_15m:
        return None

    # Current price & 24h ticker
    ticker = get_json('https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT')
    if not ticker:
        return None
    curr_price = float(ticker['lastPrice'])
    high_24h = float(ticker['highPrice'])
    low_24h = float(ticker['lowPrice'])

    # 3. Coinbase Spot Premium Check (Anti-Trap Guard)
    cb_ticker = get_json('https://api.exchange.coinbase.com/products/BTC-USD/ticker')
    bn_spot_ticker = get_json('https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT')
    cb_premium = 0.0
    if cb_ticker and bn_spot_ticker:
        cb_premium = float(cb_ticker.get('price', curr_price)) - float(bn_spot_ticker.get('price', curr_price))

    # Current 1H bar
    curr_1h = klines_1h[-1]
    c_vol = float(curr_1h[5])
    c_tb = float(curr_1h[9])
    c_delta = c_tb - (c_vol - c_tb)

    # 10-bar average volume
    avg_vol_10 = sum(float(k[5]) for k in klines_1h[-11:-1]) / 10.0
    vol_ratio = c_vol / avg_vol_10 if avg_vol_10 > 0 else 1.0

    # 15m delta
    curr_15m = klines_15m[-1]
    v_15m = float(curr_15m[5])
    tb_15m = float(curr_15m[9])
    delta_15m = tb_15m - (v_15m - tb_15m)

    # 4-bar compression
    prior_4_high = max(float(k[2]) for k in klines_1h[-5:-1])
    prior_4_low = min(float(k[3]) for k in klines_1h[-5:-1])
    prior_range_pct = (prior_4_high - prior_4_low) / curr_price

    # Detection flags
    detected = False
    is_resistance_trap = False
    reasons = []

    # INSTITUTIONAL FILTER: If Coinbase Premium is heavily negative, US spot is dumping/discounted.
    # Bounces are RESISTANCE BAIT TRAPS, NOT TRUE SQUEEZES!
    is_spot_veto = (cb_premium < -35.0)

    # Rule 1: Genuine Mega Delta Explosion (Unstoppable market taker buying)
    if (c_delta >= 850.0 or delta_15m >= 500.0) and not is_spot_veto:
        detected = True
        reasons.append(f"Genuine Delta Explosion (+{max(c_delta, delta_15m):,.0f} BTC Buy Delta)")

    # Rule 2: High Volume Breakout with Positive Delta and Bullish Spot Premium
    if vol_ratio >= 2.0 and c_delta > 350.0 and cb_premium > 0:
        detected = True
        reasons.append(f"Spot-Confirmed Breakout Surge ({vol_ratio:.1f}x Vol, +{c_delta:,.0f} BTC Delta)")

    # Rule 3: Compression Breakout with True Volume
    if prior_range_pct <= 0.010 and c_delta > 300.0 and curr_price > prior_4_high and not is_spot_veto:
        detected = True
        reasons.append(f"High-Volume Compression Break (Range {prior_range_pct*100:.1f}%)")

    # Anti-Trap Detection: Price pushing into resistance while Coinbase Premium is heavily negative
    if curr_price >= (high_24h - 150.0) and is_spot_veto and c_delta < 200.0:
        is_resistance_trap = True
        reasons.append(f"Whale Resistance Bait Detected (CB Prem: ${cb_premium:.1f}, Fake Bounce for Exit Dump)")

    return {
        "detected": detected,
        "is_resistance_trap": is_resistance_trap,
        "reasons": reasons,
        "price": curr_price,
        "c_delta": c_delta,
        "delta_15m": delta_15m,
        "vol_ratio": vol_ratio,
        "cb_premium": cb_premium,
        "high_24h": high_24h,
        "low_24h": low_24h
    }


def run_short_squeeze_sentinel(force_test=False):
    state = load_state()
    sig = check_short_squeeze_signals()
    if not sig:
        print("[ShortSqueezeSentinel] Failed to fetch market telemetry.")
        return False

    now = time.time()
    cooldown_seconds = 1200  # 20 minutes between duplicate alerts
    is_cooled_down = (now - state.get("last_alert_ts", 0)) > cooldown_seconds

    print(f"[ShortSqueezeSentinel] Price: ${sig['price']:,.1f} | 1H Delta: {sig['c_delta']:+,.1f} BTC | 15M Delta: {sig['delta_15m']:+,.1f} BTC | CB Prem: ${sig['cb_premium']:+.1f} | Triggered: {sig['detected']} | Trap: {sig['is_resistance_trap']}")

    # Only alert if a TRUE squeeze is detected and cooled down, or force_test
    if (sig['detected'] and is_cooled_down) or force_test:
        trigger_str = " | ".join(sig['reasons']) if sig['reasons'] else "Manual Test Trigger"
        
        msg = (
            f"🚨 <b>[TITAN QUANT — REAL SHORT SQUEEZE ALERT]</b> 🚨\n\n"
            f"⚠️ <b>প্রকৃত শর্ট স্কুইজ ব্রেকআউট শনাক্ত হয়েছে! (স্পট ও ভলিউম ভেরিফাইড)</b>\n\n"
            f"📊 <b>লাইভ প্রাইস:</b> <code>${sig['price']:,.2f}</code>\n"
            f"⚡ <b>সিগন্যাল ট্রিগার:</b> {trigger_str}\n"
            f"📈 <b>নেট বায়ার ডেল্টা (CVD):</b> <code>{sig['c_delta']:+,.1f} BTC (1H)</code>\n"
            f"🔊 <b>ভলিউম অনুপাত:</b> <code>{sig['vol_ratio']:.1f}x (১০-বার গড়ের তুলনায়)</code>\n"
            f"🏛️ <b>Coinbase Premium:</b> <code>${sig['cb_premium']:+.1f} USD</code>\n\n"
            f"💡 <b>ট্রেডার অ্যাকশন গাইড:</b>\n"
            f"• এটি ফেক বাউন্স নয়, আগ্রাসী টেকার বাই আসছে—শর্ট পজিশনের এসএল টাইট করুন!\n\n"
            f"🌐 <i>লাইভ ড্যাশবোর্ড: http://localhost:8585</i>"
        )
        print("🚀 Dispatching Verified Short Squeeze Telegram Alert...")
        sent = send_telegram(msg)
        print(f"Telegram alert sent status: {sent}")
        
        state["last_alert_ts"] = now
        state["last_alert_price"] = sig["price"]
        state["is_squeeze_active"] = True
        state["last_trigger_reason"] = trigger_str
        save_state(state)
        return True
    else:
        state["is_squeeze_active"] = sig['detected']
        save_state(state)
        return False


if __name__ == "__main__":
    force = "--test" in sys.argv or "--force" in sys.argv
    run_short_squeeze_sentinel(force_test=force)
