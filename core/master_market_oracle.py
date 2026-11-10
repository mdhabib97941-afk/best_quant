"""
========================================================================================
MASTER MARKET ORACLE: QUANTUM PHYSICS, DUAL-HORIZON OPTIONS & LIQUIDATION PURGE
========================================================================================
Unified Institutional Quantitative Intelligence Engine for BTC & Crypto Assets.
Combines:
  1. Unfakeable Binance Spot Cash vs Futures Leverage (Anti-Trap Filter)
  2. Dual-Horizon Options Gravitational Pull (Deribit/CoinGlass Daily + Weekly Max Pain)
  3. Retail Long/Short Overload (5m Micro Tape & Accounts Sentiment)
  4. Liquidation Purge Progress (OI Flushes, 50x & 25x Hunt Tiers)
  5. Newtonian Market Physics (Ball Drop Velocity, Floor Hardness, Spring Compression)
  6. Actionable Execution Setup (Entry, Tight SL, TP Ladder, Risk/Reward)
========================================================================================
"""

import urllib.request
import json
import time
import math
import sys
import os
from datetime import datetime

# UTF-8 stdout on Windows
if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

core_dir = os.path.dirname(os.path.abspath(__file__))
if core_dir not in sys.path:
    sys.path.insert(0, core_dir)

try:
    from market_cache import cached_get_json, TTL_KLINES
except Exception:
    cached_get_json = None
    TTL_KLINES = 15

def fetch_json(url, headers=None, timeout=8):
    if cached_get_json and not headers:
        cached = cached_get_json(url, ttl_seconds=TTL_KLINES, timeout=timeout)
        if cached is not None:
            return cached
    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    if headers: default_headers.update(headers)
    try:
        req = urllib.request.Request(url, headers=default_headers)
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode('utf-8'))
    except:
        return None

def calculate_dynamic_levels(current_price, local_low=None):
    ref_low = min(current_price, local_low) if local_low and local_low > 0 else current_price
    tier_50x_hunt = round(ref_low * 0.982, 1)
    tier_50x_high = round(ref_low * 0.988, 1)
    tier_25x_purge = round(ref_low * 0.965, 1)
    tier_25x_high = round(ref_low * 0.972, 1)
    sl_price = round(tier_25x_purge * 0.995, 1)
    target_1 = round(current_price * 1.015, 1)
    target_2 = round(current_price * 1.025, 1)
    target_3 = round(current_price * 1.040, 1)
    return {
        "retail_hunt_50x_low": tier_50x_hunt,
        "retail_hunt_50x_high": tier_50x_high,
        "purge_25x_low": tier_25x_purge,
        "purge_25x_high": tier_25x_high,
        "hard_sl": sl_price,
        "target_1": target_1,
        "target_2": target_2,
        "target_3": target_3
    }

def run_master_analysis(symbol="BTCUSDT"):
    base = symbol.replace("USDT", "").replace("BUSD", "")
    
    # ----------------------------------------------------------------------------------
    # 1. BINANCE SPOT & FUTURES REAL TAPE (UNFAKEABLE)
    # ----------------------------------------------------------------------------------
    spot_k = fetch_json(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=24")
    fut_k = fetch_json(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit=24")
    fut_taker = fetch_json(f"https://fapi.binance.com/futures/data/takerlongshortRatio?symbol={symbol}&period=1h&limit=24") or []
    oi_hist = fetch_json(f"https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period=1h&limit=24") or []
    prem = fetch_json(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}") or {}
    
    # 5m Retail Sentiment
    g_ls_5m = fetch_json(f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={symbol}&period=5m&limit=12") or []
    top_pos_5m = fetch_json(f"https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol={symbol}&period=5m&limit=12") or []
    
    if not (spot_k and fut_k):
        raise RuntimeError("Failed to fetch market data from Binance.")
        
    current_price = float(spot_k[-1][4])
    local_high = max(float(x[2]) for x in spot_k[-12:])
    local_low = min(float(x[3]) for x in spot_k[-12:])
    
    # Spot Delta
    spot_taker_buy = sum(float(x[9]) for x in spot_k[-6:])
    spot_vol = sum(float(x[5]) for x in spot_k[-6:])
    spot_taker_sell = spot_vol - spot_taker_buy
    spot_net_delta = spot_taker_buy - spot_taker_sell
    spot_cvd_ratio = spot_taker_buy / spot_taker_sell if spot_taker_sell > 0 else 1.0
    
    # Futures Delta
    fut_buy_vol = sum(float(x.get("buyVol", 0)) for x in fut_taker[-6:])
    fut_sell_vol = sum(float(x.get("sellVol", 0)) for x in fut_taker[-6:])
    fut_net_delta = fut_buy_vol - fut_sell_vol
    
    # Anti-Trap Divergence
    if fut_net_delta > 0 and spot_net_delta < -50:
        trap_status = "BULL_TRAP (Futures Paper Pumping, Spot Real Cash Offloading)"
    elif fut_net_delta < 0 and spot_net_delta > 50:
        trap_status = "BEAR_TRAP (Futures Shorts Piling In, Spot Real Cash Accumulating)"
    else:
        trap_status = "ORGANIC ALIGNMENT"
        
    funding_rate = float(prem.get("lastFundingRate", 0.0001))
    
    # ----------------------------------------------------------------------------------
    # 2. RETAIL LIQUIDATION OVERLOAD & OI STATUS
    # ----------------------------------------------------------------------------------
    curr_retail_long = float(g_ls_5m[-1]["longAccount"]) * 100.0 if g_ls_5m else 60.0
    curr_top_long = float(top_pos_5m[-1]["longAccount"]) * 100.0 if top_pos_5m else 58.0
    curr_oi = float(oi_hist[-1]["sumOpenInterest"]) if oi_hist else 94000.0
    peak_oi_24h = max(float(x["sumOpenInterest"]) for x in oi_hist) if oi_hist else curr_oi
    oi_drawdown = curr_oi - peak_oi_24h
    
    # Dynamic purge baseline: 2.15% of peak OI to fully reset leverage
    target_oi_flush = round(peak_oi_24h * 0.0215, 1) if peak_oi_24h > 0 else 2030.0
    purge_progress_pct = min(100.0, max(0.0, (abs(oi_drawdown) / target_oi_flush) * 100.0)) if (oi_drawdown < 0 and target_oi_flush > 0) else 0.0
    
    # ----------------------------------------------------------------------------------
    # 3. DUAL-HORIZON OPTIONS GRAVITY (DERIBIT / COINGLASS)
    # ----------------------------------------------------------------------------------
    options_url = f"https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency={base}&kind=option"
    res_opts = fetch_json(options_url)
    daily_profile = None
    weekly_profile = None
    confluence = False
    
    if res_opts and "result" in res_opts:
        book = res_opts["result"]
        expiries = {}
        for item in book:
            parts = item.get("instrument_name", "").split("-")
            if len(parts) == 4:
                d, k, t, oi = parts[1], float(parts[2]), parts[3], float(item.get("open_interest", 0))
                if d not in expiries: expiries[d] = []
                expiries[d].append({"strike": k, "type": t, "oi": oi})
                
        def parse_d(s):
            try: return datetime.strptime(s, "%d%b%y")
            except: return datetime.max
            
        sorted_d = sorted(expiries.keys(), key=parse_d)
        now = datetime.now()
        upcoming = [d for d in sorted_d if parse_d(d) >= now]
        if upcoming:
            daily_d = upcoming[0]
            weekly_d = next((d for d in upcoming if parse_d(d).weekday() == 4 and d != daily_d), upcoming[1] if len(upcoming)>1 else daily_d)
            
            def calc_pain(d_name):
                opts = expiries.get(d_name, [])
                if not opts: return None
                strikes = sorted(list(set(x["strike"] for x in opts)))
                min_l = float("inf")
                best = strikes[len(strikes)//2]
                c_oi = sum(x["oi"] for x in opts if x["type"] == "C")
                p_oi = sum(x["oi"] for x in opts if x["type"] == "P")
                pcr = p_oi / c_oi if c_oi > 0 else 1.0
                for s in strikes:
                    loss = 0.0
                    for opt in opts:
                        k_val = opt["strike"]
                        if opt["type"] == "C" and s > k_val: loss += (s - k_val) * opt["oi"]
                        elif opt["type"] == "P" and s < k_val: loss += (k_val - s) * opt["oi"]
                    if loss < min_l:
                        min_l = loss
                        best = s
                return {"date": d_name, "max_pain": best, "total_oi": c_oi + p_oi, "pcr": pcr}
                
            daily_profile = calc_pain(daily_d)
            weekly_profile = calc_pain(weekly_d)
            if daily_profile and weekly_profile:
                if abs(daily_profile["max_pain"] - weekly_profile["max_pain"]) / daily_profile["max_pain"] < 0.01:
                    confluence = True

    # ----------------------------------------------------------------------------------
    # 4. NEWTONIAN MARKET PHYSICS (BALL DROP & SPRING ACCUMULATION)
    # ----------------------------------------------------------------------------------
    drop_range = local_high - current_price
    drop_pct = (drop_range / local_high) * 100.0 if local_high > 0 else 0.0
    
    # Wick Rejection
    last_c = spot_k[-1]
    c_h, c_l, c_o, c_c = float(last_c[2]), float(last_c[3]), float(last_c[1]), float(last_c[4])
    c_range = max(1.0, c_h - c_l)
    lower_wick = min(c_o, c_c) - c_l
    wick_ratio = lower_wick / c_range
    
    # Floor Hardness (0-100)
    floor_score = 50.0
    if wick_ratio > 0.40: floor_score += 20.0
    elif wick_ratio < 0.15: floor_score -= 15.0
    if spot_net_delta > 0: floor_score += 15.0 * min(2.0, spot_cvd_ratio)
    else: floor_score -= 15.0
    if confluence: floor_score += 10.0
    floor_score = max(5.0, min(95.0, floor_score))
    
    # Force Vectors
    force_up = 30.0 * min(2.0, spot_cvd_ratio) + (20.0 if confluence else 5.0) + (15.0 if funding_rate < 0.0001 else 0.0)
    force_down = (25.0 if curr_retail_long > 60.5 else 10.0) + (20.0 if fut_net_delta < -200 else 0.0)
    net_bias = ((force_up - force_down) / (force_up + force_down)) * 100.0
    
    coeff_restitution = (floor_score / 100.0) * math.sqrt(max(0.1, force_up / max(1.0, force_down)))
    p_bounce = max(10.0, min(90.0, 50.0 + (net_bias * 0.4) + ((floor_score - 50.0) * 0.3)))
    p_break = 100.0 - p_bounce

    # ----------------------------------------------------------------------------------
    # 5. LIQUIDATION TIERS & PROJECTED HUNT ZONES (DYNAMICALLY CALCULATED)
    # ----------------------------------------------------------------------------------
    # 50x retail long liquidations typically pool 1.2% - 1.8% below current price/support
    # 25x institutional purge zones sit 3.0% - 3.8% below current price/support
    ref_low = min(current_price, local_low) if local_low > 0 else current_price
    tier_50x_hunt = round(ref_low * 0.982, 1)
    tier_50x_high = round(ref_low * 0.988, 1)
    tier_25x_purge = round(ref_low * 0.965, 1)
    tier_25x_high = round(ref_low * 0.972, 1)
    sl_price = round(tier_25x_purge * 0.995, 1)
    target_1 = round(current_price * 1.015, 1)
    target_2 = round(current_price * 1.025, 1)
    target_3 = round(current_price * 1.040, 1)
    
    return {
        "symbol": symbol,
        "base": base,
        "price": current_price,
        "local_high": local_high,
        "local_low": local_low,
        "drop_pct": drop_pct,
        "drop_range": drop_range,
        "spot_net_delta": spot_net_delta,
        "spot_cvd_ratio": spot_cvd_ratio,
        "fut_net_delta": fut_net_delta,
        "trap_status": trap_status,
        "funding_rate": funding_rate,
        "retail_long": curr_retail_long,
        "top_pos_long": curr_top_long,
        "curr_oi": curr_oi,
        "peak_oi": peak_oi_24h,
        "oi_drawdown": oi_drawdown,
        "purge_progress_pct": purge_progress_pct,
        "daily_options": daily_profile,
        "weekly_options": weekly_profile,
        "confluence": confluence,
        "floor_score": floor_score,
        "wick_ratio": wick_ratio,
        "net_bias": net_bias,
        "p_bounce": p_bounce,
        "p_break": p_break,
        "hunt_zones": {
            "tier_50x": tier_50x_hunt,
            "tier_50x_high": tier_50x_high,
            "tier_25x": tier_25x_purge,
            "tier_25x_high": tier_25x_high,
            "sl_price": sl_price,
            "target_1": target_1,
            "target_2": target_2,
            "target_3": target_3
        }
    }

def print_master_report(d):
    sep = "=" * 80
    print("\n" + sep)
    print(f"      INSTITUTIONAL QUANTUM ORACLE: {d['base']} FULL SPECTRUM DIAGNOSTIC      ")
    print(sep)
    print(f" Current Price: ${d['price']:,.2f}  |  24h Peak: ${d['local_high']:,.2f}  |  Local Low: ${d['local_low']:,.2f}")
    print(f" Drop Amplitude: -{d['drop_pct']:.2f}% (-${d['drop_range']:,.2f})  |  Funding: {d['funding_rate']*100:.4f}%")
    print("-" * 80)
    
    # 1. UNFAKEABLE FLOW
    print(" 1. UNFAKEABLE ORDER FLOW & ANTI-TRAP AUDIT:")
    print(f"    - Real Spot Cash Net Delta:  {d['spot_net_delta']:+,.2f} {d['base']} (CVD Ratio: {d['spot_cvd_ratio']:.2f})")
    print(f"    - Futures Paper Delta:       {d['fut_net_delta']:+,.2f} {d['base']}")
    print(f"    - Institutional Verdict:     {d['trap_status']}")

    # 2. DUAL-HORIZON OPTIONS GRAVITY
    print("\n 2. DUAL-HORIZON OPTIONS GRAVITATIONAL MAGNETS:")
    if d['daily_options']:
        print(f"    * DAILY Expiry ({d['daily_options']['date']}):   Max Pain ${d['daily_options']['max_pain']:,.0f} | OI: {d['daily_options']['total_oi']:,.1f} BTC | PCR: {d['daily_options']['pcr']:.2f}")
    if d['weekly_options']:
        print(f"    * WEEKLY Expiry ({d['weekly_options']['date']}):  Max Pain ${d['weekly_options']['max_pain']:,.0f} | OI: {d['weekly_options']['total_oi']:,.1f} BTC | PCR: {d['weekly_options']['pcr']:.2f}")
    if d['confluence']:
        print(f"    >>> CONFLUENCE: [PERFECT ALIGNMENT] Daily & Weekly lock at ${d['daily_options']['max_pain']:,.0f} Iron Floor!")

    # 3. RETAIL LIQUIDATION OVERLOAD & PURGE PROGRESS
    print("\n 3. RETAIL OVERLOAD & LIQUIDATION PURGE PROGRESS:")
    print(f"    - Retail Long Accounts:      {d['retail_long']:.2f}% ({'HEAVILY OVERLOADED (>60%)' if d['retail_long']>60 else 'BALANCED'})")
    print(f"    - Top Trader Position Long:  {d['top_pos_long']:.2f}%")
    print(f"    - Current Total OI:          {d['curr_oi']:,.1f} {d['base']} (Peak: {d['peak_oi']:,.1f} {d['base']})")
    print(f"    - Current OI Drawdown:       {d['oi_drawdown']:+,.1f} {d['base']}")
    print(f"    - Purge Completion Meter:    [{'#'*int(d['purge_progress_pct']//10)}{'.'*(10-int(d['purge_progress_pct']//10))}] {d['purge_progress_pct']:.1f}%")
    if d['purge_progress_pct'] < 40.0 and d['retail_long'] > 60.0:
        print(f"    >>> HUNT ALERT: Purge incomplete! Retail longs vulnerable to ${d['hunt_zones']['tier_50x']:,.0f} – ${d['hunt_zones']['tier_50x_high']:,.0f} hunt.")
    else:
        print("    >>> PURGE COMPLETE: Leverage reset finished. Ready for launch.")

    # 4. NEWTONIAN PHYSICS & PROBABILITIES
    print("\n 4. MARKET PHYSICS & SPRING ACCUMULATION:")
    print(f"    - Floor Hardness Score:      {d['floor_score']:.1f} / 100.0 (Lower Wick Absorption: {d['wick_ratio']*100:.1f}%)")
    print(f"    - Net Directional Vector:    {d['net_bias']:+.1f}% ({'BULLISH LIFT' if d['net_bias']>0 else 'BEARISH GRAVITY'})")
    print(f"    - Spring Reversal Probability:   {d['p_bounce']:.1f}%")
    print(f"    - Floor Breakdown Probability:   {d['p_break']:.1f}%")

    # 5. ACTIONABLE SNIPER SETUP
    print("-" * 80)
    print(" 5. ACTIONABLE SNIPER TRADE SETUP (THE EXECUTION BLUEPRINT):")
    print(f"    * 50x Retail Hunt Zone (Primary Entry):   ${d['hunt_zones']['tier_50x']:,.0f} – ${d['hunt_zones']['tier_50x_high']:,.0f}")
    print(f"    * 25x Full Purge Zone (Secondary Entry):  ${d['hunt_zones']['tier_25x']:,.0f} – ${d['hunt_zones']['tier_25x_high']:,.0f}")
    print(f"    * Invalidation / Hard Stop Loss (SL):     ${d['hunt_zones']['sl_price']:,.0f} (Below full liquidation floor)")
    print(f"    * Target 1 (Elastic Rebound / Range High):${d['hunt_zones']['target_1']:,.0f}")
    print(f"    * Target 2 (Structural Fair Value):       ${d['hunt_zones']['target_2']:,.0f}")
    print(f"    * Target 3 (Full Short Squeeze Blast-Off):${d['hunt_zones']['target_3']:,.0f}")
    print(sep + "\n")

if __name__ == "__main__":
    symbol = "BTCUSDT"
    if len(sys.argv) > 1 and sys.argv[1].startswith("--symbol="):
        symbol = sys.argv[1].split("=")[1].upper()
    data = run_master_analysis(symbol=symbol)
    print_master_report(data)
