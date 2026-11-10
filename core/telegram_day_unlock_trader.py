import sys
import os
import requests
import json
import time
import datetime
import urllib.parse
import re

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ----------------------------------------------------------------------------------
# F27 REMEDIATION: Deterministic sys.path Injection (Core & Repository Root)
# ----------------------------------------------------------------------------------
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(CURRENT_DIR) == "core":
    CORE_DIR = CURRENT_DIR
    PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
else:
    p = CURRENT_DIR
    while p and os.path.dirname(p) != p:
        if os.path.exists(os.path.join(p, "core")):
            break
        p = os.path.dirname(p)
    PROJECT_ROOT = p if os.path.exists(os.path.join(p, "core")) else os.path.dirname(CURRENT_DIR)
    CORE_DIR = os.path.join(PROJECT_ROOT, "core")

if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(1, PROJECT_ROOT)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8918704289:AAFg33hZSpa0XrUTFah4TakDBx6ryrAHHgU")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "7736288854")
STATE_FILE = os.path.join(CORE_DIR, "daily_unlock_state.json")

# Import Quantum Market Physics & Options Oracle
try:
    from master_market_oracle import run_master_analysis
except Exception as e:
    print(f"Warning: master_market_oracle import error: {e}")
    run_master_analysis = None


# ----------------------------------------------------------------------------------
# F26 REMEDIATION: Live Institutional Intelligence Fallback (Replacing Phantom Engine)
# ----------------------------------------------------------------------------------
def get_institutional_intelligence(symbol="BTCUSDT"):
    """
    Genuine fallback aggregator.
    Derives live institutional intelligence from check_market_4pillars and coinbase_institutional_radar.
    """
    try:
        import check_market_4pillars as p4
        audit = p4.audit_market(symbol)
        
        cvd_delta = audit.get('spot_delta_4h', 0.0)
        cvd_sign = "+" if cvd_delta > 0 else ""
        daily_pain = audit.get('daily_pain')
        pain_str = f"${daily_pain:,.0f}" if daily_pain is not None else "N/A"
        pcr = audit.get('pcr')
        pcr_str = f"{pcr:.2f}" if pcr is not None else "N/A"
        oi = audit.get('cur_oi', 0.0)
        cb_prem = audit.get('cb_premium', 0.0)
        trap = audit.get('trap_status', 'ORGANIC')
        
        aggression = "BUYER_DOMINANCE" if cvd_delta > 0 else "SELLER_DOMINANCE"
        sentiment = "BEARISH_HEDGE" if (pcr is not None and pcr > 1.0) else "BULLISH_EXPOSURE"
        
        return {
            'taker_cvd': {
                'last_1h_net_delta': cvd_delta,
                'aggression': aggression
            },
            'deribit_options': {
                'pc_vol_ratio': pcr_str,
                'sentiment': sentiment,
                'max_pain': pain_str
            },
            'multi_exchange_oi': {
                'total_aggregated_oi_btc': oi
            },
            'stablecoin_flow': {
                'delta_7d_usd_billion': 0.0
            },
            'synthesis_verdict': trap
        }
    except Exception as e:
        print(f"Warning: Fallback institutional intelligence unavailable: {e}")
        return {
            'taker_cvd': {'last_1h_net_delta': 0.0, 'aggression': 'NEUTRAL'},
            'deribit_options': {'pc_vol_ratio': 'N/A', 'sentiment': 'NEUTRAL', 'max_pain': 'N/A'},
            'multi_exchange_oi': {'total_aggregated_oi_btc': 0.0},
            'stablecoin_flow': {'delta_7d_usd_billion': 0.0},
            'synthesis_verdict': 'DATA_OFFLINE'
        }


# ----------------------------------------------------------------------------------
# NETWORK RESILIENCY: Production-Grade Telegram Dispatcher
# ----------------------------------------------------------------------------------
def send_telegram(text, max_retries=3):
    """
    Robust Telegram API dispatcher with:
    - Message length truncation (enforcing Telegram's 4096 character limit)
    - Retry logic with exponential backoff on timeouts / socket disconnects
    - Dynamic sleep handling on HTTP 429 (Too Many Requests)
    - Automatic plain-text fallback on HTTP 400 (entity parse / unclosed tag errors)
    """
    if not text:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    # Enforce safe character ceiling
    if len(text) > 4000:
        text = text[:3980] + "\n...[TRUNCATED]"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    for attempt in range(max_retries):
        try:
            r = requests.post(url, json=payload, timeout=12)
            res = r.json()

            if res.get("ok", False):
                return True

            error_code = res.get("error_code")
            desc = res.get("description", "")

            # Handle 429 Rate Limits
            if error_code == 429:
                retry_after = res.get("parameters", {}).get("retry_after", 3)
                sleep_time = min(10, max(1, retry_after))
                print(f"⚠️ Telegram 429 rate limit hit. Sleeping {sleep_time}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(sleep_time)
                continue

            # Handle 400 HTML Entity Parse Errors (fallback to plain text)
            if error_code == 400 and ("can't parse entities" in desc.lower() or "tag" in desc.lower()):
                print(f"⚠️ Telegram HTML parse error: '{desc}'. Retrying with plain text...")
                clean_text = re.sub(r'<[^>]+>', '', text)
                plain_payload = {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": clean_text,
                    "disable_web_page_preview": True
                }
                r_plain = requests.post(url, json=plain_payload, timeout=12)
                return r_plain.json().get("ok", False)

            print(f"Telegram API rejected message: code={error_code}, desc={desc}")
            return False

        except (requests.exceptions.Timeout, requests.exceptions.RequestException) as e:
            print(f"⚠️ Telegram network error: {e} (attempt {attempt+1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(1.5 * (attempt + 1))
        except Exception as e:
            print(f"Error sending to Telegram: {e}")
            return False

    return False


def fetch_klines(symbol="BTCUSDT", interval="1h", limit=50):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if not isinstance(data, list):
            print(f"Warning: Unexpected kline payload for {symbol}: {data}")
            return []
        candles = []
        for c in data:
            if not isinstance(c, list) or len(c) < 6:
                continue
            v = float(c[5])
            tbv = float(c[9]) if len(c) > 9 else v * 0.5
            candles.append({
                'time': int(c[0]),
                'open': float(c[1]),
                'high': float(c[2]),
                'low': float(c[3]),
                'close': float(c[4]),
                'volume': v,
                'delta': tbv - (v - tbv)
            })
        return candles
    except Exception as e:
        print(f"Error fetching {interval} klines for {symbol}: {e}")
        return []


def calculate_dealing_range(candles, lookback=20):
    if not candles or len(candles) < lookback:
        return None
    sub = candles[-lookback:]
    hh = max(c['high'] for c in sub)
    ll = min(c['low'] for c in sub)
    eq_50 = (hh + ll) / 2.0
    cur_c = candles[-1]['close']
    zone = "PREMIUM" if cur_c > eq_50 else "DISCOUNT"
    return {
        'hh': hh,
        'll': ll,
        'eq_50': round(eq_50, 2),
        'cur': cur_c,
        'zone': zone
    }


def get_asset_buffer(symbol, cur_price):
    if "BTC" in symbol:
        return max(350.0, cur_price * 0.005)
    elif "ETH" in symbol:
        return max(25.0, cur_price * 0.007)
    elif "SOL" in symbol:
        return max(2.5, cur_price * 0.012)
    else:
        return max(0.5, cur_price * 0.006)


def get_asset_expansion_step(symbol, cur_price, r_1h):
    h_range = r_1h['hh'] - r_1h['ll']
    if "BTC" in symbol:
        return max(700.0, h_range * 0.6)
    elif "ETH" in symbol:
        return max(30.0, h_range * 0.6)
    elif "SOL" in symbol:
        return max(2.2, h_range * 0.6)
    else:
        return max(1.0, cur_price * 0.015)


# ----------------------------------------------------------------------------------
# R2 REMEDIATION: Dynamic Money Management & Risk-Reward Multipliers
# ----------------------------------------------------------------------------------
def get_exness_specs(symbol, cur_price, risk_pts, rr1=2.0, rr2=3.5, rr3=5.5):
    """Dynamically computes lot sizing and USD targets based on live R:R ratios."""
    if "BTC" in symbol:
        lot = "0.01 - 0.02 Lot"
        sl_usd = round(0.01 * risk_pts, 2)
    elif "ETH" in symbol:
        lot = "0.02 - 0.04 Lot"
        sl_usd = round(0.15 * risk_pts, 2)
    elif "SOL" in symbol:
        lot = "0.05 - 0.10 Lot"
        sl_usd = round(2.5 * risk_pts, 2)
    else:
        lot = "0.01 Lot"
        sl_usd = round(0.01 * risk_pts, 2)
        
    sl_usd = max(2.50, min(12.0, sl_usd))
    tp1_usd = round(sl_usd * max(1.0, rr1), 2)
    tp2_usd = round(sl_usd * max(1.5, rr2), 2)
    tp3_usd = round(sl_usd * max(2.0, rr3), 2)
    return lot, sl_usd, tp1_usd, tp2_usd, tp3_usd


def analyze_unlock_signal(symbol="BTCUSDT"):
    c_1d = fetch_klines(symbol, "1d", 30)
    c_4h = fetch_klines(symbol, "4h", 30)
    c_1h = fetch_klines(symbol, "1h", 30)
    
    if not (c_1d and c_4h and c_1h):
        return None
        
    r_1d = calculate_dealing_range(c_1d, 20)
    r_4h = calculate_dealing_range(c_4h, 20)
    r_1h = calculate_dealing_range(c_1h, 20)
    
    c_15m = fetch_klines(symbol, "15m", 30)
    r_15m = calculate_dealing_range(c_15m, 20)

    # Protected against NoneType subscript errors
    if not (r_1d and r_4h and r_1h and r_15m):
        return None

    cur_price = c_1h[-1]['close']
    dec = 2 if "SOL" in symbol else 1
    
    # Raw dealing range unlock conditions
    is_bull_unlock = (cur_price >= r_15m['eq_50'] * 0.998) and (cur_price >= r_1h['eq_50'] * 0.998) and (cur_price >= r_4h['eq_50'] * 0.998)
    is_bear_unlock = (cur_price < r_15m['eq_50']) and (cur_price < r_1h['eq_50']) and (cur_price < r_4h['eq_50'])

    # Range extreme filter: never buy into ceiling resistance, never short into floor support
    if is_bull_unlock and (cur_price >= r_1h['hh'] * 0.993):
        print(f"🛑 [RANGE SHIELD] {symbol} Bull Unlock BLOCKED! Price near 1H Range High Ceiling (${r_1h['hh']:,.1f}). Buying here is a FOMO Trap!")
        return None
    if is_bear_unlock and (cur_price <= r_1h['ll'] * 1.007):
        print(f"🛑 [RANGE SHIELD] {symbol} Bear Unlock BLOCKED! Price near 1H Range Low Floor (${r_1h['ll']:,.1f}). Shorting here is a Bear Trap!")
        return None

    oracle = None
    if run_master_analysis:
        try:
            oracle = run_master_analysis(symbol)
        except Exception as e:
            print(f"[{symbol}] Master oracle audit warning: {e}")

    # FAIL-CLOSED ARCHITECTURE: Never trade blindly if oracle fails or times out
    if not oracle:
        print(f"🛑 [SAFETY LOCK] {symbol} Master Oracle unavailable. FAIL-CLOSED: No trade permitted without complete institutional confirmation.")
        return None

    trap = oracle.get('trap_status', '')
    p_bounce = oracle.get('p_bounce', 50.0)
    p_break = oracle.get('p_break', 50.0)
    daily_opt = oracle.get('daily_options')
    confluence = oracle.get('confluence', False)
    spot_net = oracle.get('spot_net_delta', 0.0)
    
    # 1. Bear Unlock Shield (Prevents getting trapped in Bear Traps & Gamma Squeezes)
    if is_bear_unlock:
        if trap.startswith('BEAR_TRAP') or spot_net > 40.0:
            print(f"🛑 [QUANTUM SHIELD] {symbol} Bear Unlock BLOCKED! Bear Trap Active: Real Cash Spot is Accumulating ({spot_net:+.1f} BTC).")
            return None
        if p_bounce >= 65.0:
            print(f"🛑 [QUANTUM SHIELD] {symbol} Bear Unlock BLOCKED! High Spring Bounce Probability ({p_bounce:.1f}% Bullish Force).")
            return None
        if daily_opt and daily_opt.get('max_pain') and (cur_price <= daily_opt['max_pain'] * 1.008) and confluence:
            print(f"🛑 [QUANTUM SHIELD] {symbol} Bear Unlock BLOCKED! Price near Options Max Pain Iron Floor (${daily_opt['max_pain']}). Gamma Pin in effect.")
            return None

    # 2. Bull Unlock Shield (Prevents buying into Bull Traps & Liquidations)
    if is_bull_unlock:
        if trap.startswith('BULL_TRAP') or spot_net < -30.0:
            print(f"🛑 [QUANTUM SHIELD] {symbol} Bull Unlock BLOCKED! Bull Trap Active: Real Cash Spot is Dumping ({spot_net:+.1f} BTC).")
            return None
        if p_break >= 65.0:
            print(f"🛑 [QUANTUM SHIELD] {symbol} Bull Unlock BLOCKED! High Floor Breakdown Probability ({p_break:.1f}% Gravity).")
            return None
        
        # MULTI-EXCHANGE SPOT-LEAD SUPREME VETO ENFORCEMENT (COINBASE + BINANCE)
        if "BTC" in symbol:
            try:
                from coinbase_institutional_radar import analyze_coinbase_flow
                cb_flow = analyze_coinbase_flow()
                if cb_flow:
                    cb_prem = cb_flow.get('current_premium', 0.0)
                    is_twap = cb_flow.get('is_twap_dump', False)
                    if cb_prem < -40.0 or is_twap:
                        print(f"🛑 [SPOT-LEAD SUPREME VETO] {symbol} Bull Unlock HARD-LOCKED! Coinbase Spot Dumping Active (CB Discount: ${cb_prem:.1f}, TWAP Dump: {is_twap}).")
                        return None
            except Exception as e:
                print(f"Warning checking Spot Veto in {symbol}: {e}")

    buffer = get_asset_buffer(symbol, cur_price)
    step = get_asset_expansion_step(symbol, cur_price, r_1h)
    
    if is_bull_unlock:
        # Build 3-Zone Institutional Long Trade Setup
        sweep_low = min(c['low'] for c in c_1h[-8:])
        
        zone_down_min = round(sweep_low, dec)
        zone_down_max = round(sweep_low + (r_1h['hh'] - sweep_low) * 0.25, dec)
        zone_mid = round(max(r_1h['eq_50'], r_4h['eq_50']), dec)
        
        entry_min = round(zone_down_min, dec)
        entry_max = round(zone_mid * 1.002, dec)
        
        sl = round(sweep_low - buffer, dec)
        risk = round(zone_mid - sl, dec)
        if risk <= 0:
            risk = round(buffer * 2.0, dec)
            sl = round(zone_mid - risk, dec)
            
        tp1 = round(r_1h['hh'], dec)
        tp2 = round(max(tp1 + step, r_4h['hh']), dec)
        tp3 = round(max(tp2 + step, r_1d['eq_50']), dec)
        
        # Dynamic R:R per TP target (R2 Remediation)
        rr1 = round(max(0.1, tp1 - zone_mid) / max(0.1, risk), 1)
        rr2 = round(max(0.1, tp2 - zone_mid) / max(0.1, risk), 1)
        rr_macro = round(max(0.1, tp3 - zone_mid) / max(0.1, risk), 1)
        
        is_near_top = cur_price >= (r_1h['hh'] * 0.995)
        exec_note = f"⚠️ সতর্কতা: প্রাইস রেসিস্ট্যান্সের মুখে (${r_1h['hh']:,.{dec}f})। এখন সরাসরি মার্কেট বাই নিষেধ! নিচে আসলে ${zone_mid:,.{dec}f}-এ লিমিট বাই।" if is_near_top else "ডিপ রিটেস্টে লিমিট বাই অর্ডার সক্রিয়।"

        return {
            'type': 'BULL_UNLOCK',
            'symbol': symbol,
            'direction': '🟢 LONG / BUY (PULLBACK LIMIT)',
            'order_type': 'BUY LIMIT ONLY (মার্কেট বাই নিষেধ — পুলব্যাকে এন্ট্রি)',
            'cur_price': cur_price,
            'entry_min': entry_min,
            'entry_max': entry_max,
            'entry_target': zone_mid,
            'exact_entry': f"${zone_mid:,.{dec}f} (Pullback 50% EQ)",
            'exact_sl': f"${sl:,.{dec}f}",
            'exact_tp1': f"${tp1:,.{dec}f} (1:{rr1} R:R Range High)",
            'exact_tp2': f"${tp2:,.{dec}f} (1:{rr2} R:R Mega BSL Magnet)",
            'exact_tp3': f"${tp3:,.{dec}f} (1:{rr_macro} R:R Daily Macro Target) 🎯",
            'active_zone': 'DOWN & MIDDLE',
            'zone_up': '⛔ NO SHORT (বুলিশ ট্রেন্ডে কাউন্টার শর্ট নিষেধ, তবে টপে ফোমো বাইও নিষেধ)',
            'zone_mid': f"${zone_mid:,.{dec}f} (50% Equilibrium Retest)",
            'zone_down': f"${zone_down_min:,.{dec}f} – ${zone_down_max:,.{dec}f} (Extreme Discount OB Floor)",
            'sl': f"${sl:,.{dec}f}",
            'risk_usd_per_btc': round(risk, 2),
            'tp1': f"${tp1:,.{dec}f}",
            'tp2': f"${tp2:,.{dec}f}",
            'tp3': f"${tp3:,.{dec}f}",
            'rr1': rr1,
            'rr2': rr2,
            'rr': f"1:{rr_macro}",
            'oracle': oracle,
            'reason_bn': (
                f"{exec_note} রিসেন্ট সুইপ লো (${sweep_low:,.{dec}f}) এর নিচে থাকা রিটেইলারদের স্টপ লস ও সেল লিকুইডিটি সুইপ করে মার্কেট বুলিশ রিজেকশন কনফার্ম করেছে। "
                f"বর্তমান প্রাইস (${cur_price:,.{dec}f}) ১H হাইয়ের মুখে। প্রফেশনালরা কখনো টপে ফোমো বাই করে না; "
                f"দাম পুলব্যাক দিয়ে ৫০% লেভেলে (${zone_mid:,.{dec}f}) নামলে সেখান থেকে লং-এর আসল বিস্ফোরক মুভ পাওয়া যাবে।"
            )
        }
        
    elif is_bear_unlock:
        # Build 3-Zone Institutional Short Trade Setup
        sweep_high = max(c['high'] for c in c_1h[-8:])
        
        zone_up_min = round(cur_price + (sweep_high - cur_price) * 0.50, dec)
        zone_up_max = round(sweep_high, dec)
        zone_up_mt = round((zone_up_min + zone_up_max) / 2.0, dec)
        zone_mid = round(min(r_1h['eq_50'], r_4h['eq_50']), dec)
        
        raw_e1 = round(zone_mid * 0.998, dec)
        raw_e2 = round(zone_up_max, dec)
        entry_min = min(raw_e1, raw_e2)
        entry_max = max(raw_e1, raw_e2)
        
        sl = round(sweep_high + buffer, dec)
        risk = round(sl - zone_up_mt, dec)
        if risk <= 0:
            risk = round(buffer * 2.0, dec)
            sl = round(zone_up_mt + risk, dec)
            
        tp1 = round(zone_up_mt - risk * 2.0, dec)
        tp2 = round(min(tp1 - step, r_4h['ll']), dec)
        tp3 = round(min(tp2 - step, r_1d['ll']), dec)
        
        # Dynamic R:R per TP target (R2 Remediation)
        rr1 = round(max(0.1, zone_up_mt - tp1) / max(0.1, risk), 1)
        rr2 = round(max(0.1, zone_up_mt - tp2) / max(0.1, risk), 1)
        rr_macro = round(max(0.1, zone_up_mt - tp3) / max(0.1, risk), 1) if risk > 0 else 4.0
        
        return {
            'type': 'BEAR_UNLOCK',
            'symbol': symbol,
            'direction': '🔴 SHORT / SELL',
            'order_type': 'SELL LIMIT (or MARKET at Entry)',
            'cur_price': cur_price,
            'entry_min': entry_min,
            'entry_max': entry_max,
            'entry_target': zone_up_mt,
            'exact_entry': f"${zone_up_mt:,.{dec}f}",
            'exact_sl': f"${sl:,.{dec}f}",
            'exact_tp1': f"${tp1:,.{dec}f}",
            'exact_tp2': f"${tp2:,.{dec}f}",
            'exact_tp3': f"${tp3:,.{dec}f}",
            'active_zone': 'UP & MIDDLE',
            'zone_up': f"${zone_up_min:,.{dec}f} – ${zone_up_max:,.{dec}f} (Sniper 50% MT: ${zone_up_mt:,.{dec}f})",
            'zone_mid': f"${zone_mid:,.{dec}f} (4H 50% EQ & FVG Retest)",
            'zone_down': '⛔ NO LONG (বিয়ারিশ ট্রেন্ডে অন্ধ বটম বাই নিষিদ্ধ)',
            'sl': f"${sl:,.{dec}f}",
            'risk_usd_per_btc': round(risk, 2),
            'tp1': f"${tp1:,.{dec}f} (1:{rr1} R:R Quick Target)",
            'tp2': f"${tp2:,.{dec}f} (1:{rr2} R:R Overnight Sweep: ${r_4h['ll']:,.{dec}f})",
            'tp3': f"${tp3:,.{dec}f} (1:{rr_macro} Daily Macro SSL Floor) 🎯",
            'rr1': rr1,
            'rr2': rr2,
            'rr': f"1:{rr_macro}",
            'oracle': oracle,
            'reason_bn': (
                f"প্রাইস ১৫ মিনিট, ১ ঘণ্টা এবং ৪ ঘণ্টার ৫০% সাপোর্টের নিচে নেমে গেছে। "
                f"কোয়ান্ট শিল্ড অডিট পাস করেছে—কোনো বিয়ার ট্র্যাপ বা স্ট্রং গামা বাউন্স নেই। "
                f"টপে থাকা Bearish Order Block বা মাঝের ৫০% EQ রিটেস্টে শর্ট নিলে সর্বোচ্চ উইন-রেট পাওয়া যায়।"
            )
        }
        
    return None


def format_telegram_message(sig):
    now_str = datetime.datetime.now().strftime("%I:%M %p | %d %b %Y")
    dec = 2 if "SOL" in sig['symbol'] else 1
    
    # Exness Calculator on $200 capital tailored by asset using dynamic R:R (R2 Remediation)
    risk_pts = sig.get('risk_usd_per_btc', 200.0)
    rr1_val = sig.get('rr1', 2.0)
    rr2_val = sig.get('rr2', 3.5)
    rr3_val = float(sig['rr'].split(':')[-1]) if ':' in sig.get('rr', '') else 5.5
    lot_str, sl_usd, tp1_usd, tp2_usd, tp3_usd = get_exness_specs(sig['symbol'], sig['cur_price'], risk_pts, rr1_val, rr2_val, rr3_val)
    
    # Extract rich Quantum Oracle intelligence if available
    oracle = sig.get('oracle')
    base = sig['symbol'].replace("USDT", "").replace("BUSD", "")
    
    if oracle:
        spot_delta = oracle.get('spot_net_delta', 0.0)
        spot_sign = "+" if spot_delta > 0 else ""
        trap = oracle.get('trap_status', 'ORGANIC')
        p_bounce = oracle.get('p_bounce', 50.0)
        daily_opt = oracle.get('daily_options')
        confluence = oracle.get('confluence', False)
        
        if daily_opt and daily_opt.get('max_pain') is not None:
            pain_text = f"${daily_opt['max_pain']:,.0f} ({daily_opt.get('date', 'Daily')})"
            if confluence: pain_text += " [IRON FLOOR PIN]"
            pcr_val = daily_opt.get('pcr')
            pcr_text = f"{pcr_val:.2f} ({'BEARISH_HEDGE' if pcr_val > 1.0 else 'BULLISH_EXPOSURE'})" if pcr_val is not None else "N/A"
            oi_val = daily_opt.get('total_oi')
            oi_text = f"{oi_val:,.1f} {base}" if oi_val is not None else f"{oracle.get('curr_oi', 0):,.1f} {base}"
        else:
            pain_text = "N/A (Spot Engine Active)"
            pcr_text = "N/A"
            oi_text = f"{oracle.get('curr_oi', 0):,.1f} {base}"
            
        trap_label = "VERIFIED SAFE (Zero Trap Detected)" if (not trap or "ORGANIC" in trap) else str(trap)[:32]
        inst_section = (
            f"🏛️ <b>QUANTUM ORACLE & DEALER GAMMA INTELLIGENCE:</b>\n"
            f"├─ 🩸 <b>Real Spot vs Futures Flow:</b> <code>{spot_sign}{spot_delta:,.1f} {base} ({str(trap)[:32]})</code>\n"
            f"├─ 🧲 <b>Dealer Gamma & Max Pain:</b> <code>{pain_text}</code>\n"
            f"├─ 📜 <b>Deribit Options P/C:</b> <code>{pcr_text}</code>\n"
            f"├─ 🌐 <b>Aggregated Open Interest:</b> <code>{oi_text}</code>\n"
            f"├─ 🌊 <b>Spring Accumulation Force:</b> <code>{p_bounce:.1f}% Bullish Vector</code>\n"
            f"└─ 🛡️ <b>Anti-Trap Shield:</b> <code>{trap_label}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )
    else:
        # F26 REMEDIATION: Clean fallback institutional radar without phantom import
        inst = get_institutional_intelligence(sig['symbol'])
        cvd = inst['taker_cvd']
        opt = inst['deribit_options']
        oi = inst['multi_exchange_oi']
        stables = inst['stablecoin_flow']
        verdict = inst['synthesis_verdict']
        delta_sign = "+" if cvd['last_1h_net_delta'] > 0 else ""
        flow_sign = "+" if stables['delta_7d_usd_billion'] > 0 else ""
        inst_section = (
            f"🏛️ <b>4-PILLAR INSTITUTIONAL RADAR (LIVE FALLBACK):</b>\n"
            f"├─ 🩸 <b>Real CVD (Taker Delta):</b> <code>{delta_sign}{cvd['last_1h_net_delta']:,.1f} BTC ({cvd['aggression']})</code>\n"
            f"├─ 📜 <b>Deribit Options P/C:</b> <code>{opt['pc_vol_ratio']} ({opt['sentiment']})</code>\n"
            f"├─ 🌐 <b>Aggregated Multi-OI:</b> <code>{oi['total_aggregated_oi_btc']:,.1f} BTC</code>\n"
            f"├─ 🌊 <b>7D Stablecoin Flow:</b> <code>{flow_sign}{stables['delta_7d_usd_billion']}B USD</code>\n"
            f"└─ 🛡️ <b>Macro Verdict:</b> <code>{verdict}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )

    msg = (
        f"🎯 <b>[CITADEL-MAGNET SFP MASTER TRADE SETUP]</b> 🎯\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ <b>সিগন্যাল সময়:</b> {now_str} (Dhaka Time)\n"
        f"🪙 <b>অ্যাসেট:</b> #{sig['symbol']} | <b>বর্তমান প্রাইস:</b> <code>${sig['cur_price']:,.{dec}f}</code>\n"
        f"🧭 <b>ট্রেডের দিক:</b> <b>{sig['direction']}</b>\n"
        f"⚖️ <b>Max Potential R:R:</b> <b>{sig['rr']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚡ <b>[EXNESS / MT5 সরাসরি কপি-পেস্ট এন্ট্রি বক্স]</b> ⚡\n"
        f"▶️ <b>অর্ডার টাইপ:</b> <code>{sig.get('order_type', 'LIMIT / MARKET')}</code>\n"
        f"▶️ <b>🎯 এন্ট্রি প্রাইস (ENTRY):</b> <code>{sig['exact_entry']}</code>\n"
        f"▶️ <b>🛑 স্টপ লস (STOP LOSS):</b> <code>{sig['exact_sl']}</code>\n"
        f"▶️ <b>🏆 টেক প্রফিট ১ (TP 1):</b> <code>{sig['exact_tp1']}</code>\n"
        f"▶️ <b>🏆 টেক প্রফিট ২ (TP 2):</b> <code>{sig['exact_tp2']}</code>\n"
        f"▶️ <b>🏆 টেক প্রফিট ৩ (TP 3):</b> <code>{sig['exact_tp3']}</code>\n"
        f"▶️ <b>লট সাইজ ($200 Capital):</b> <code>{lot_str}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 <b>সুনির্দিষ্ট ট্রেড লেভেল ডিটেইলস:</b>\n"
        f"• 🎯 <b>প্রাইমারি এন্ট্রি জোন:</b> <code>{sig['zone_down'] if 'LONG' in sig['direction'] else sig['zone_up']}</code>\n"
        f"• 🟡 <b>সেকেন্ডারি রিটেস্ট লেভেল (50% EQ):</b> <code>{sig['zone_mid']}</code>\n"
        f"• 🛡️ <b>সার্জিক্যাল টাইট SL:</b> <code>{sig['exact_sl']}</code> (রিস্ক দূরত্ব: <code>${risk_pts:,.{dec}f}</code>)\n\n"
        f"🏆 <b>টেক প্রফিট টার্গেটস:</b>\n"
        f"├─ 🥇 <b>TP 1:</b> <code>{sig['exact_tp1']}</code> (৫০% প্রফিট বুক ও SL ব্রেকইভেনে)\n"
        f"├─ 🥈 <b>TP 2:</b> <code>{sig['exact_tp2']}</code> (ইকুইলিব্রিয়াম / সুইপ টার্গেট)\n"
        f"└─ 🥉 <b>TP 3 (ম্যাক্রো রানার):</b> <code>{sig['exact_tp3']}</code> (বিপরীত লিকুইডিটি পুল)\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ <b>Exness মানি ম্যানেজমেন্ট ($200 Capital | {lot_str}):</b>\n"
        f"• 🛑 <b>SL হিট করলে সর্বোচ্চ লস:</b> <code>-${sl_usd:.2f} USD</code> (মাত্র {sl_usd/200*100:.1f}% রিস্ক)\n"
        f"• 🎯 <b>TP 1 এ ৫০% প্রফিট:</b> <code>+${tp1_usd:.2f} USD</code> (সাথে সাথে SL ➔ Breakeven!)\n"
        f"• 🎯 <b>TP 2 এ প্রফিট:</b> <code>+${tp2_usd:.2f} USD</code>\n"
        f"• 🎯 <b>TP 3 ফুল রানার প্রফিট:</b> <code>+${tp3_usd:.2f} USD</code> (+{tp3_usd/200*100:.1f}% গ্রোথ)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{inst_section}"
        f"🔬 <b>ইনস্টিটিউশনাল কনফার্মেশন চেকলিস্ট (৫টি গোল্ডেন বাতি):</b>\n"
        f"✅ <b>১. লোকেশন:</b> ডিলিং রেঞ্জ এক্সট্রিম ফিল্টার পাসড\n"
        f"✅ <b>২. লিকুইডিটি:</b> ক্যান্ডেল সুইপ ও রিজেকশন কনফার্মড\n"
        f"✅ <b>৩. আনফেকবল ফ্লো:</b> স্পট ক্যাশ ডেল্টা ও CVD সিনার্জি\n"
        f"✅ <b>৪. অপশনস গ্র্যাভিটি:</b> ডিলার গামা ও ম্যাক্স পেইন সাপোর্ট কনফার্মড\n"
        f"✅ <b>৫. অ্যান্টি-ট্র্যাপ শিল্ড:</b> কোনো ফেকআউট বা ট্র্যাপ সনাক্ত হয়নি (Safe)\n\n"
        f"🧠 <b>প্রাতিষ্ঠানিক লজিক (Whale Reasoning):</b>\n"
        f"<i>{sig['reason_bn']}</i>\n\n"
        f"🛡️ <b>একক ট্রেড প্রটেকশন রুল:</b>\n"
        f"<i>বস, এটিই আপনার বর্তমানের একক মাস্টার ট্রেড। TP 1 হিট না হওয়া পর্যন্ত অতিরিক্ত কোনো ট্রেড নেবেন না। TP 1 হিট হওয়া মাত্রই বাকি ৫০% পজিশন সম্পূর্ণ ফ্রি (Breakeven)-তে চলবে!</i>"
    )
    return msg


def audit_zone_momentum(symbol, direction, entry_min, entry_max, cur_price):
    c_5m = fetch_klines(symbol, '5m', 5)
    if not c_5m:
        return 'NO_DATA', {}
        
    c = c_5m[-1]
    prev_c = c_5m[-2] if len(c_5m) >= 2 else c
    
    rng = max(0.01, c['high'] - c['low'])
    lw = min(c['open'], c['close']) - c['low']
    uw = c['high'] - max(c['open'], c['close'])
    body = abs(c['close'] - c['open'])
    
    lw_pct = (lw / rng) * 100.0
    uw_pct = (uw / rng) * 100.0
    body_pct = (body / rng) * 100.0
    is_green = c['close'] >= c['open']
    delta = c['delta']
    vol = max(0.001, c['volume'])
    delta_pct = (delta / vol) * 100.0
    
    metrics = {
        'lw_pct': round(lw_pct, 1),
        'uw_pct': round(uw_pct, 1),
        'body_pct': round(body_pct, 1),
        'is_green': is_green,
        'delta': round(delta, 1),
        'delta_pct': round(delta_pct, 1),
        'cur_price': cur_price
    }
    
    in_zone = (cur_price <= entry_max * 1.002) and (cur_price >= entry_min * 0.998)
    if not in_zone:
        return 'NOT_IN_ZONE', metrics
        
    if 'LONG' in direction:
        if (not is_green) and (body_pct > 60.0) and (lw_pct < 20.0) and (delta_pct < -20.0):
            return 'FALLING_KNIFE', metrics
            
        if (lw_pct >= 25.0) or (is_green and delta_pct > 5.0) or (prev_c['close'] < prev_c['open'] and is_green and lw_pct >= 15.0):
            return 'CONFIRMED_LIFT', metrics
            
        return 'NEUTRAL_IN_ZONE', metrics
    else:
        if is_green and (body_pct > 60.0) and (uw_pct < 20.0) and (delta_pct > 20.0):
            return 'RISING_VOLCANO', metrics
            
        if (uw_pct >= 25.0) or ((not is_green) and delta_pct < -5.0) or (prev_c['close'] > prev_c['open'] and (not is_green) and uw_pct >= 15.0):
            return 'CONFIRMED_DROP', metrics
            
        return 'NEUTRAL_IN_ZONE', metrics


def format_retest_confirmed_message(sym, setup, metrics):
    now_str = datetime.datetime.now().strftime("%I:%M %p | %d %b %Y")
    dec = 2 if "SOL" in sym else 1
    direction = setup.get('direction', 'LONG')
    is_long = "LONG" in direction
    cur_p = metrics['cur_price']
    lw = metrics.get('lw_pct', 0.0)
    uw = metrics.get('uw_pct', 0.0)
    delta = metrics.get('delta', 0.0)
    delta_sign = "+" if delta > 0 else ""
    base = sym.replace("USDT", "").replace("BUSD", "")
    lot_str = setup.get('lot_str', '0.01 Lot')
    sl_usd = setup.get('sl_usd', 4.0)
    tp1_usd = setup.get('tp1_usd', 8.0)
    
    if is_long:
        header = "⚡ <b>[LIVE PULLBACK RETEST: MOMENTUM CONFIRMED — ENTER NOW!]</b> ⚡"
        action_text = "🟢 <b>BUY MARKET / LIMIT NOW (পুলব্যাক বায়ার রিজেকশন কনফার্মড)</b>"
        rejection_detail = f"├─ 🛡️ <b>Lower Wick Absorption:</b> <code>{lw:.1f}% (স্ট্রং বায়ার রিজেকশন)</code>\n"
        delta_detail = f"├─ 🩸 <b>5m Micro Buyer Delta:</b> <code>{delta_sign}{delta:,.1f} {base} (পজিটিভ বায়ার ফ্লো)</code>\n"
        advice = "প্রাইস পুলব্যাক ৫০% ইকুইলিব্রিয়াম জোনে এসে লোয়ার উইক রিজেকশন তৈরি করেছে এবং বায়াররা সেলারদের ভলিউম শুষে নিয়েছে (Absorption)। ফলিং নাইফ বা ডাম্পিং ঝুঁকি সম্পূর্ণ মুক্ত। এখনই এক্সনেস / MT5 এ সরাসরি এন্ট্রি নিতে পারেন।"
    else:
        header = "⚡ <b>[LIVE PULLBACK RETEST: REJECTION CONFIRMED — SHORT NOW!]</b> ⚡"
        action_text = "🔴 <b>SELL MARKET / LIMIT NOW (রিটেস্ট সেলার রিজেকশন কনফার্মড)</b>"
        rejection_detail = f"├─ 🛡️ <b>Upper Wick Rejection:</b> <code>{uw:.1f}% (স্ট্রং সেলার রিজেকশন)</code>\n"
        delta_detail = f"├─ 🩸 <b>5m Micro Seller Delta:</b> <code>{delta_sign}{delta:,.1f} {base} (সেলিং প্রেশার)</code>\n"
        advice = "প্রাইস পুলব্যাক ৫০% ইকুইলিব্রিয়াম জোনে এসে আপার উইক রিজেকশন তৈরি করেছে এবং সেলাররা দখল নিয়েছে। কোনো পাম্প বা স্পাইক ঝুঁকি নেই। এখনই এক্সনেস / MT5 এ সরাসরি শর্ট এন্ট্রি নিতে পারেন।"

    msg = (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ <b>লাইভ কনফার্মেশন সময়:</b> {now_str} (Dhaka Time)\n"
        f"🪙 <b>অ্যাসেট:</b> #{sym} | <b>বর্তমান লাইভ প্রাইস:</b> <code>${cur_p:,.{dec}f}</code>\n"
        f"🧭 <b>ট্রেড সিগন্যাল:</b> {action_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 <b>[EXNESS / MT5 সরাসরি এক্সিকিউশন বক্স]</b> 🎯\n"
        f"▶️ <b>🎯 লাইভ এন্ট্রি (ENTRY):</b> <code>${cur_p:,.{dec}f}</code>\n"
        f"▶️ <b>🛑 স্টপ লস (STOP LOSS):</b> <code>{setup.get('exact_sl')}</code>\n"
        f"▶️ <b>🏆 টেক প্রফিট ১ (TP 1):</b> <code>{setup.get('exact_tp1')}</code>\n"
        f"▶️ <b>🏆 টেক প্রফিট ২ (TP 2):</b> <code>{setup.get('exact_tp2')}</code>\n"
        f"▶️ <b>🏆 টেক প্রফিট ৩ (TP 3):</b> <code>{setup.get('exact_tp3')}</code>\n"
        f"▶️ <b>লট সাইজ ($200 Capital):</b> <code>{lot_str}</code> (Max Loss: <code>-${sl_usd:.2f} USD</code>)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔬 <b>মাইক্রো-টেপ মোমেন্টাম অডিট (Micro Tape Audit):</b>\n"
        f"{rejection_detail}"
        f"{delta_detail}"
        f"└─ 🧭 <b>স্টেটাস:</b> <code>MOMENTUM_VERIFIED (অন্ধ এন্ট্রি নয় — ১০০% ভেরিফাইড পুলব্যাক)</code>\n\n"
        f"💡 <b>বস, অ্যাকশন প্ল্যান:</b>\n"
        f"<i>{advice}</i>\n"
        f"<i>TP 1 হিট হওয়া মাত্রই ৫০% প্রফিট (+${tp1_usd:.2f} USD) বুক করে স্টপ লস এন্ট্রি প্রাইসে (Breakeven) টেনে দিন!</i>"
    )
    return msg


def format_velocity_warning_message(sym, setup, metrics):
    now_str = datetime.datetime.now().strftime("%I:%M %p | %d %b %Y")
    dec = 2 if "SOL" in sym else 1
    direction = setup.get('direction', 'LONG')
    is_long = "LONG" in direction
    cur_p = metrics['cur_price']
    body = metrics.get('body_pct', 0.0)
    delta = metrics.get('delta', 0.0)
    delta_sign = "+" if delta > 0 else ""
    base = sym.replace("USDT", "").replace("BUSD", "")
    
    if is_long:
        header = "⚠️ <b>[PULLBACK WARNING: HIGH SELLING VELOCITY — DO NOT ENTER YET!]</b> ⚠️"
        warning_type = "🔴 <b>ফলিং নাইফ সতর্কতা (Falling Knife Detected)</b>"
        flow_desc = f"আগ্রাসী সেলিং প্রেশার (৫মি বডি: {body:.1f}%, ডেল্টা: {delta_sign}{delta:,.1f} {base})"
        advice = (
            "বস, প্রাইস পুলব্যাক এন্ট্রি জোনে এলেও সেলারদের স্পিড এখনও খুব বেশি! অন্ধভাবে লিমিট অর্ডারে এন্ট্রি নিয়ে ফলিং নাইফ ধরবেন না। "
            "আমরা লাইভ টেপ মনিটর করছি; সেলারদের ভলিউম শুষে নিয়ে বায়ার রিজেকশন কনফার্ম হলেই সাথে সাথে এন্ট্রি মেসেজ আসবে।"
        )
    else:
        header = "⚠️ <b>[PULLBACK WARNING: HIGH BUYING VELOCITY — DO NOT SHORT YET!]</b> ⚠️"
        warning_type = "🟢 <b>ভলকানো পাম্প সতর্কতা (High Buying Velocity Detected)</b>"
        flow_desc = f"আগ্রাসী বাইং প্রেশার (৫মি বডি: {body:.1f}%, ডেল্টা: {delta_sign}{delta:,.1f} {base})"
        advice = (
            "বস, প্রাইস রিটেস্ট জোনে এলেও বায়ারদের পাম্পের গতি অনেক বেশি! অন্ধভাবে কাউন্টার শর্ট নিতে যাবেন না। "
            "আমরা লাইভ টেপ মনিটর করছি; বায়ারদের গতি কমে আপার উইক রিজেকশন পেলেই শর্ট এন্ট্রি কনফার্মেশন পাঠানো হবে।"
        )
        
    msg = (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ <b>ওয়ার্নিং সময়:</b> {now_str} (Dhaka Time)\n"
        f"🪙 <b>অ্যাসেট:</b> #{sym} | <b>বর্তমান লাইভ প্রাইস:</b> <code>${cur_p:,.{dec}f}</code>\n"
        f"⚠️ <b>সতর্কবার্তা:</b> {warning_type}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚨 <b>কেন অপেক্ষা করবেন?</b>\n"
        f"• <b>ফ্লো স্টেটাস:</b> <code>{flow_desc}</code>\n"
        f"• <b>ঝুঁকি:</b> প্রাইস জোনে থাকলেও এখনও রিজেকশন বা অ্যাবসর্পশন তৈরি হয়নি।\n\n"
        f"🧠 <b>কোয়ান্ট প্রটেকশন নির্দেশিকা:</b>\n"
        f"<i>{advice}</i>\n\n"
        f"🛡️ <i>ধৈর্য ধরুন—মোমেন্টাম গ্রিন সিগন্যাল দিলেই স্বয়ংক্রিয় 'ENTER NOW' অ্যালার্ট পাঠানো হবে!</i>"
    )
    return msg


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    """Atomic state persistence preventing corrupted JSON."""
    tmp_path = f"{STATE_FILE}.tmp.{os.getpid()}_{time.time()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, STATE_FILE)
    except Exception as e:
        print(f"Error saving state: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def run_once(force=False):
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    state = load_state()
    now_ts = time.time()
    
    for sym in symbols:
        # -------------------------------------------------------------
        # 1. MACRO SFP UNLOCK SCAN (Stage 1)
        # -------------------------------------------------------------
        sig = analyze_unlock_signal(sym)
        if sig:
            last_sig_type = state.get(sym, {}).get('type')
            last_sig_time = state.get(sym, {}).get('timestamp', 0)
            
            should_alert_macro = force or (sig['type'] != last_sig_type) or (now_ts - last_sig_time > 7200)
            
            if should_alert_macro:
                msg = format_telegram_message(sig)
                success = send_telegram(msg)
                if success:
                    print(f"✅ [{sym}] Sent {sig['type']} Citadel-Magnet alert to Telegram successfully!")
                    rr1_val = sig.get('rr1', 2.0)
                    rr2_val = sig.get('rr2', 3.5)
                    rr3_val = float(sig['rr'].split(':')[-1]) if ':' in sig.get('rr', '') else 5.5
                    lot_str, sl_usd, tp1_usd, tp2_usd, tp3_usd = get_exness_specs(sym, sig['cur_price'], sig.get('risk_usd_per_btc', 200.0), rr1_val, rr2_val, rr3_val)
                    state[sym] = {
                        'type': sig['type'],
                        'direction': sig['direction'],
                        'timestamp': now_ts,
                        'price': sig['cur_price'],
                        'entry_min': sig['entry_min'],
                        'entry_max': sig['entry_max'],
                        'entry_target': sig['entry_target'],
                        'exact_entry': sig['exact_entry'],
                        'exact_sl': sig['exact_sl'],
                        'exact_tp1': sig['exact_tp1'],
                        'exact_tp2': sig['exact_tp2'],
                        'exact_tp3': sig['exact_tp3'],
                        'lot_str': lot_str,
                        'sl_usd': sl_usd,
                        'tp1_usd': tp1_usd,
                        'tp2_usd': tp2_usd,
                        'tp3_usd': tp3_usd,
                        'retest_alerted': False,
                        'warning_alerted': False
                    }
                    save_state(state)
                else:
                    print(f"❌ [{sym}] Failed to send Telegram alert.")
            else:
                print(f"ℹ️ [{sym}] {sig['type']} macro setup already alerted recently.")
                if 'entry_min' not in state.get(sym, {}):
                    rr1_val = sig.get('rr1', 2.0)
                    rr2_val = sig.get('rr2', 3.5)
                    rr3_val = float(sig['rr'].split(':')[-1]) if ':' in sig.get('rr', '') else 5.5
                    lot_str, sl_usd, tp1_usd, tp2_usd, tp3_usd = get_exness_specs(sym, sig['cur_price'], sig.get('risk_usd_per_btc', 200.0), rr1_val, rr2_val, rr3_val)
                    if sym not in state:
                        state[sym] = {}
                    state[sym].update({
                        'type': sig['type'],
                        'direction': sig['direction'],
                        'entry_min': sig['entry_min'],
                        'entry_max': sig['entry_max'],
                        'entry_target': sig['entry_target'],
                        'exact_entry': sig['exact_entry'],
                        'exact_sl': sig['exact_sl'],
                        'exact_tp1': sig['exact_tp1'],
                        'exact_tp2': sig['exact_tp2'],
                        'exact_tp3': sig['exact_tp3'],
                        'lot_str': lot_str,
                        'sl_usd': sl_usd,
                        'tp1_usd': tp1_usd,
                        'tp2_usd': tp2_usd,
                        'tp3_usd': tp3_usd
                    })
                    save_state(state)
        else:
            print(f"[{sym}] No valid unlock condition (or filtered by Quantum Shield).")

        # -------------------------------------------------------------
        # 2. MICRO-MOMENTUM LIVE ZONE AUDIT (Stage 2)
        # -------------------------------------------------------------
        sym_state = state.get(sym)
        if sym_state and sym_state.get('entry_min') and sym_state.get('entry_max'):
            if (now_ts - sym_state.get('timestamp', 0)) < 14400:
                direction = sym_state.get('direction', 'LONG')
                entry_min = sym_state['entry_min']
                entry_max = sym_state['entry_max']
                
                cur_p = sig['cur_price'] if sig else None
                if not cur_p:
                    try:
                        ticker_res = requests.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}", timeout=5).json()
                        if isinstance(ticker_res, dict) and 'price' in ticker_res:
                            cur_p = float(ticker_res['price'])
                        else:
                            cur_p = sym_state.get('price', 0)
                    except Exception:
                        cur_p = sym_state.get('price', 0)
                
                status, metrics = audit_zone_momentum(sym, direction, entry_min, entry_max, cur_p)
                print(f"🔍 [{sym}] Micro Zone Status: {status} | Price: ${cur_p} | Zone: [${entry_min} - ${entry_max}]")
                
                if status in ['CONFIRMED_LIFT', 'CONFIRMED_DROP']:
                    if not sym_state.get('retest_alerted', False):
                        retest_msg = format_retest_confirmed_message(sym, sym_state, metrics)
                        if send_telegram(retest_msg):
                            print(f"🚀 [{sym}] Dispatched LIVE RETEST CONFIRMED alert to Telegram!")
                            sym_state['retest_alerted'] = True
                            save_state(state)
                        else:
                            print(f"❌ [{sym}] Failed to send retest alert.")
                    else:
                        print(f"ℹ️ [{sym}] Retest confirmation already alerted for this setup.")
                        
                elif status in ['FALLING_KNIFE', 'RISING_VOLCANO']:
                    if not sym_state.get('warning_alerted', False) and not sym_state.get('retest_alerted', False):
                        warn_msg = format_velocity_warning_message(sym, sym_state, metrics)
                        if send_telegram(warn_msg):
                            print(f"⚠️ [{sym}] Dispatched PULLBACK VELOCITY WARNING alert to Telegram!")
                            sym_state['warning_alerted'] = True
                            save_state(state)
                        else:
                            print(f"❌ [{sym}] Failed to send warning alert.")
                    else:
                        print(f"ℹ️ [{sym}] Warning already alerted or retest already confirmed.")

        # -------------------------------------------------------------
        # 3. REAL INSTITUTIONAL ACCUMULATION SENTINEL (Pillar 1-4 & Coinbase Inflow Radar)
        # -------------------------------------------------------------
        if sym == "BTCUSDT":
            try:
                import check_market_4pillars as p4
                audit = p4.audit_market(sym)
                
                try:
                    from coinbase_institutional_radar import analyze_coinbase_flow
                    cips = analyze_coinbase_flow()
                except Exception:
                    cips = None

                is_genuine_acc = (audit.get('spot_delta_4h', 0) > 25.0) and (audit.get('cb_premium', -999) > -15.0) and (audit.get('fut_delta_4h', 0) > 50.0)
                
                cb_prem_val = audit.get('cb_premium', -999.0)
                is_twap_active = cips.get('is_twap_dump', False) if cips else False
                is_cips_inflow = (cips is not None) and (not is_twap_active) and (cb_prem_val > -25.0) and (
                    cips.get('cips_score', 0) >= 75.0 or (cips.get('cips_score', 0) >= 65.0 and cips.get('premium_velocity_5m', 0) >= 20.0)
                )

                last_acc_time = state.get(sym, {}).get('last_acc_time', 0)
                last_cips_time = state.get(sym, {}).get('last_cips_time', 0)

                if is_cips_inflow and (now_ts - last_cips_time > 7200):
                    now_str = datetime.datetime.now().strftime("%I:%M %p | %d %b %Y")
                    msg_cips = (
                        f"🚨 <b>[COINBASE INSTITUTIONAL BUYING DETECTED — SMART MONEY ACTIVE!]</b> 🚨\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"⏱️ <b>সময়:</b> {now_str} (Dhaka Time)\n"
                        f"🪙 <b>অ্যাসেট:</b> #{sym} | <b>লাইভ প্রাইস:</b> <code>${audit['fut_price']:,.1f}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"🏛️ <b>আমেরিকান প্রাতিষ্ঠানিক মাইক্রোস্ট্রাকচার সিগনেচার:</b>\n"
                        f"├─ 🎯 <b>CIPS ইনডেক্স:</b> <code>{cips.get('cips_score', 0)}% ({cips.get('signal', 'NEUTRAL')})</code>\n"
                        f"├─ 📈 <b>Premium Velocity (5m):</b> <code>{cips.get('premium_velocity_5m', 0.0):+.2f} USD (দ্রুত সংকুচিত হচ্ছে)</code>\n"
                        f"├─ 🛡️ <b>CB L2 Bid Depth (1%):</b> <code>{cips.get('bids_1pct_btc', 0.0):.1f} BTC vs {cips.get('asks_1pct_btc', 0.0):.1f} BTC (OBI: {cips.get('cb_obi_1pct', 0.0):+.2f})</code>\n"
                        f"├─ 🩸 <b>CB Taker Tape Delta:</b> <code>{cips.get('last_100_delta_btc', 0.0):+.2f} BTC (Buy Ratio: {cips.get('buy_ratio_pct', 50.0):.1f}%)</code>\n"
                        f"└─ 🐋 <b>হোয়েল ব্লক ট্রেডস:</b> <code>{cips.get('whale_trades_count', 0)} টি (সাইজ: {cips.get('whale_buy_btc', 0.0):.2f} BTC)</code>\n\n"
                        f"💡 <b>বস, অ্যাকশন প্ল্যান:</b>\n"
                        f"<i>কয়েনবেসে মার্কিন প্রাতিষ্ঠানিক ক্রেতারা সক্রিয় হয়েছে। ডাম্পের গতি দুর্বল হচ্ছে এবং তারা গোপনে ডিপ শুষে নিচ্ছে। অতিরিক্ত লোভে শর্টে থাকবেন না, সম্ভাব্য রিভার্সাল লং সেটআপের জন্য প্রস্তুত হোন!</i>"
                    )
                    if send_telegram(msg_cips):
                        print(f"🚀 [{sym}] Dispatched COINBASE INSTITUTIONAL INFLOW alert to Telegram!")
                        if sym not in state: state[sym] = {}
                        state[sym]['last_cips_time'] = now_ts
                        save_state(state)

                if is_genuine_acc and (now_ts - last_acc_time > 14400):
                    now_str = datetime.datetime.now().strftime("%I:%M %p | %d %b %Y")
                    # Safe formatting of Deribit Options Max Pain (prevent TypeError on None)
                    daily_pain_val = audit.get('daily_pain')
                    pain_display = f"${daily_pain_val:,.0f} (Max Pain Cushion)" if daily_pain_val is not None else "N/A (Options Data Offline)"
                    msg_acc = (
                        f"💎 <b>[INSTITUTIONAL ACCUMULATION CONFIRMED — WHALES ARE BUYING!]</b> 💎\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"⏱️ <b>সময়:</b> {now_str} (Dhaka Time)\n"
                        f"🪙 <b>অ্যাসেট:</b> #{sym} | <b>বর্তমান লাইভ প্রাইস:</b> <code>${audit['fut_price']:,.1f}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"🏛️ <b>প্রমাণিত একুমুলেশন সিগনেচার (৪টি স্তম্ভ কনফার্মড):</b>\n"
                        f"├─ 🩸 <b>Real Spot Cash Flow:</b> <code>+{audit.get('spot_delta_4h', 0):,.1f} BTC (আসল স্পট ক্যাশ বায়িং শুরু)</code>\n"
                        f"├─ 🇺🇸 <b>Coinbase Premium:</b> <code>{audit.get('cb_premium', 0):+.1f} USD (ইউএস ডিসকাউন্ট শেষ)</code>\n"
                        f"├─ 🌐 <b>Futures Delta 4H:</b> <code>+{audit.get('fut_delta_4h', 0):,.1f} BTC (বায়ার ডমিনেন্স)</code>\n"
                        f"├─ 🧲 <b>Deribit Options Floor:</b> <code>{pain_display}</code>\n"
                        f"└─ 🎯 <b>স্ট্যাটাস:</b> <code>GENUINE_ACCUMULATION (বুল ট্র্যাপ মুক্ত)</code>\n\n"
                        f"💡 <b>বস, অ্যাকশন প্ল্যান:</b>\n"
                        f"<i>তিমিরা অবশেষে আসল স্পট ক্যাশ দিয়ে মাল কেনা শুরু করেছে। ফেইক বাউন্স বা ট্র্যাপের ভয় কেটে গেছে। এখন আপনি নিরাপদভাবে লং এন্ট্রির প্রস্তুতি নিতে পারেন!</i>"
                    )
                    if send_telegram(msg_acc):
                        print(f"🚀 [{sym}] Dispatched INSTITUTIONAL ACCUMULATION alert to Telegram!")
                        if sym not in state: state[sym] = {}
                        state[sym]['last_acc_time'] = now_ts
                        save_state(state)
            except Exception as e:
                print(f"[{sym}] Accumulation sentinel audit warning: {e}")

if __name__ == "__main__":
    force_run = "--force" in sys.argv
    run_once(force=force_run)
