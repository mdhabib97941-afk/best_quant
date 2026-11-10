"""
====================================================================
🏛️ TITAN QUANT SYSTEM — LONG SQUEEZE SENTINEL (Liquidation Cascade Radar)
====================================================================
Detects imminent or active Long Squeezes / Downside Waterfall Liquidation Cascades:
1. Negative Delta Explosion (Taker Sell Delta <= -750 BTC on 1H or <= -400 BTC on 15M)
2. High-Volume Sell Surge (>= 1.6x 10-bar avg with heavy negative delta)
3. Compression Floor Breakdown (Slicing below support with aggressive selling)
4. Retail Long Trapping (Elevated retail long exposure getting liquidated)
5. Dispatches high-priority Telegram alerts & updates website state
====================================================================
"""

import os
import sys
import time
import json
import requests
import urllib.request
import threading

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

TELEGRAM_BOT_TOKEN = "8918704289:AAFg33hZSpa0XrUTFah4TakDBx6ryrAHHgU"
TELEGRAM_CHAT_ID = "7736288854"
STATE_FILE = os.path.join(CORE_DIR, "long_squeeze_state.json")
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


def check_long_squeeze_signals():
    """
    Empirical quantitative long squeeze / waterfall cascade detector:
    Evaluates 1H & 15M candles for:
    1. Taker Sell Delta Explosion (Delta <= -750 BTC on 1H or <= -400 BTC on 15M)
    2. Volume Surge with Heavy Negative Delta (>= 1.6x avg, Delta <= -200 BTC)
    3. Compression Support Floor Breakdown with negative delta
    4. Support Floor / 24h Low Sweep Danger
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

    # Current 1H bar
    curr_1h = klines_1h[-1]
    c_vol = float(curr_1h[5])
    c_tb = float(curr_1h[9])
    c_delta = c_tb - (c_vol - c_tb)  # Positive = Buy Delta, Negative = Sell Delta

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

    detected = False
    reasons = []

    # Rule 1: Negative Delta Explosion (Heavy Taker Selling)
    if c_delta <= -750.0 or delta_15m <= -400.0:
        detected = True
        reasons.append(f"Sell Delta Explosion ({min(c_delta, delta_15m):,.0f} BTC Taker Sell)")

    # Rule 2: High Volume Flush with Negative Delta
    if vol_ratio >= 1.6 and c_delta <= -200.0:
        detected = True
        reasons.append(f"Volume Flush Surge ({vol_ratio:.1f}x 10-bar avg, Delta {c_delta:,.0f} BTC)")

    # Rule 3: Compression Support Floor Breakdown
    if prior_range_pct <= 0.012 and c_delta < -150.0 and curr_price <= prior_4_low:
        detected = True
        reasons.append(f"Compression Floor Breakdown (Range {prior_range_pct*100:.1f}%)")

    # Rule 4: Support Floor / 24h Low Sweep Danger
    if curr_price <= (low_24h + 50.0):
        detected = True
        reasons.append(f"24h Low Floor Sweep Danger (${low_24h:,.1f})")

    return {
        "detected": detected,
        "reasons": reasons,
        "price": curr_price,
        "c_delta": c_delta,
        "delta_15m": delta_15m,
        "vol_ratio": vol_ratio,
        "high_24h": high_24h,
        "low_24h": low_24h
    }


def run_long_squeeze_sentinel(force_test=False):
    state = load_state()
    sig = check_long_squeeze_signals()
    if not sig:
        print("[LongSqueezeSentinel] Failed to fetch market telemetry.")
        return False

    now = time.time()
    cooldown_seconds = 900  # 15 minutes between duplicate alerts
    is_cooled_down = (now - state.get("last_alert_ts", 0)) > cooldown_seconds

    print(f"[LongSqueezeSentinel] Price: ${sig['price']:,.1f} | 1H Delta: {sig['c_delta']:+,.1f} BTC | 15M Delta: {sig['delta_15m']:+,.1f} BTC | Vol Ratio: {sig['vol_ratio']:.1f}x | Triggered: {sig['detected']}")

    if (sig['detected'] and is_cooled_down) or force_test:
        trigger_str = " | ".join(sig['reasons']) if sig['reasons'] else "Manual Test Trigger"
        
        msg = (
            f"🩸 <b>[TITAN QUANT — LONG SQUEEZE RADAR ALERT]</b> 🩸\n\n"
            f"⚠️ <b>জরুরি সতর্কতা: লং লিকুইডেশন ক্যাসকেড বা ডাউনসাইড ওয়াটারফল শনাক্ত হয়েছে!</b>\n\n"
            f"📊 <b>লাইভ প্রাইস:</b> <code>${sig['price']:,.2f}</code>\n"
            f"⚡ <b>সিগন্যাল ট্রিগার:</b> {trigger_str}\n"
            f"📉 <b>নেট সেলার ডেল্টা (CVD):</b> <code>{sig['c_delta']:+,.1f} BTC (1H)</code>\n"
            f"🔊 <b>ভলিউম অনুপাত:</b> <code>{sig['vol_ratio']:.1f}x (১০-বার গড়ের তুলনায়)</code>\n"
            f"🛡️ <b>সাপোর্ট ফ্লোর টার্গেট:</b> <code>${sig['low_24h']:,.1f}</code>\n\n"
            f"💡 <b>ট্রেডার অ্যাকশন গাইড (Immediate Action):</b>\n"
            f"• যদি লং পজিশনে থাকেন, <b>অবিলম্বে এক্সিট করুন বা এসএল টাইট করুন</b>—মার্কেট ফ্রি-ফল হতে পারে!\n"
            f"• পতনশীল ছুরিতে হাত দিয়ে বটমে লং ধরতে যাবেন না, লিকুইডেশন সুইপ শেষ হওয়া পর্যন্ত অপেক্ষা করুন!\n"
            f"• শর্ট ট্রেডারদের জন্য: এটি প্রফিট এক্সপানশন মোমেন্টাম!\n\n"
            f"🌐 <i>লাইভ ড্যাশবোর্ড: http://localhost:8585</i>"
        )
        print("🩸 Dispatching Urgent Long Squeeze Telegram Alert...")
        sent = send_telegram(msg)
        print(f"Telegram alert sent status: {sent}")
        
        state["last_alert_ts"] = now
        state["last_alert_price"] = sig["price"]
        state["is_squeeze_active"] = True
        state["last_trigger_reason"] = trigger_str
        save_state(state)
        return True
    else:
        state["is_squeeze_active"] = sig["detected"]
        save_state(state)
        return False


if __name__ == "__main__":
    force = "--test" in sys.argv or "--force" in sys.argv
    run_long_squeeze_sentinel(force_test=force)
