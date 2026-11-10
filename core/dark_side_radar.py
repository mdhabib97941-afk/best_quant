import os
import sys
import urllib.request
import json
import time
from collections import defaultdict

core_dir = os.path.dirname(os.path.abspath(__file__))
if core_dir not in sys.path:
    sys.path.insert(0, core_dir)

try:
    from market_cache import cached_get_json, TTL_OPTIONS, TTL_CME
except Exception:
    cached_get_json = None
    TTL_OPTIONS = 60
    TTL_CME = 120

def fetch_dark_side_intelligence(curr_price=78500.0):
    deribit_status = "ONLINE"
    try:
        # 1. Fetch Deribit Live Options Summary
        deribit_url = 'https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option'
        deribit_data = cached_get_json(deribit_url, ttl_seconds=TTL_OPTIONS, timeout=8) if cached_get_json else None
        if not deribit_data:
            req_d = urllib.request.Request(deribit_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req_d, timeout=8) as resp_d:
                deribit_data = json.loads(resp_d.read().decode('utf-8'))
        deribit_raw = deribit_data.get('result', []) if isinstance(deribit_data, dict) else []
        if not deribit_raw:
            raise ValueError("Empty Deribit options data")
        
        all_calls = defaultdict(float)
        all_puts = defaultdict(float)
        strikes = set()
        underlying_p = curr_price
        
        for item in deribit_raw:
            parts = item.get('instrument_name', '').split('-')
            if len(parts) == 4:
                strike = float(parts[2])
                kind = parts[3]
                oi = float(item.get('open_interest', 0.0))
                strikes.add(strike)
                if kind == 'C':
                    all_calls[strike] += oi
                else:
                    all_puts[strike] += oi
                if item.get('underlying_price'):
                    underlying_p = float(item.get('underlying_price'))
        
        # Calculate Max Pain across strikes around price
        eval_strikes = sorted([s for s in strikes if (underlying_p * 0.7) <= s <= (underlying_p * 1.3)])
        min_loss = float('inf')
        max_pain_strike = underlying_p
        
        for s in eval_strikes:
            loss = 0.0
            for k, oi in all_calls.items():
                if s > k: loss += (s - k) * oi
            for k, oi in all_puts.items():
                if s < k: loss += (k - s) * oi
            if loss < min_loss:
                min_loss = loss
                max_pain_strike = s
                
        total_call_oi = sum(all_calls.values())
        total_put_oi = sum(all_puts.values())
        total_options_oi = total_call_oi + total_put_oi
        pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 1.0
        
        dist_to_max_pain = round(underlying_p - max_pain_strike, 1)
        gamma_regime = "POSITIVE_GAMMA" if abs(dist_to_max_pain) < 1500.0 else "NEGATIVE_GAMMA"
        gamma_desc = (
            f"মার্কেট মেকাররা পজিটিভ গামায় আছে — দাম ${max_pain_strike:,.0f} ম্যাক্স পেইন স্ট্রাইকে পিন করে রাখা হচ্ছে।"
            if gamma_regime == "POSITIVE_GAMMA" else
            f"মার্কেট মেকাররা নেগেটিভ গামায় ঝুঁকছে — ম্যাক্স পেইন থেকে {abs(dist_to_max_pain):,.0f} পয়েন্ট দূরে, বড় লিকুইডেশন উইকের ঝুঁকি!"
        )
        gamma_color = "var(--cyan)" if gamma_regime == "POSITIVE_GAMMA" else "var(--crimson)"
        gamma_badge = "🧲 POSITIVE GAMMA (MAX PAIN PINNING)" if gamma_regime == "POSITIVE_GAMMA" else "⚡ NEGATIVE GAMMA (VOLATILITY EXPLOSION)"
        
    except Exception as e:
        print("Deribit fetch error:", e)
        deribit_status = "DATA_OFFLINE"
        max_pain_strike = None
        dist_to_max_pain = None
        total_call_oi = None
        total_put_oi = None
        total_options_oi = None
        pcr = None
        underlying_p = curr_price
        gamma_regime = "DATA_OFFLINE"
        gamma_desc = "Deribit অপশন ডাটা অফলাইন — কোনো মক ডাটা ব্যবহার করা হচ্ছে না।"
        gamma_color = "var(--text-muted)"
        gamma_badge = "⚠️ OPTIONS DATA UNAVAILABLE"

    # 2. Fetch CME Bitcoin Futures
    cme_status = "ONLINE"
    try:
        cme_url = 'https://query1.finance.yahoo.com/v8/finance/chart/BTC=F?interval=1h&range=5d'
        cme_data = cached_get_json(cme_url, ttl_seconds=TTL_CME, timeout=6) if cached_get_json else None
        if not cme_data:
            req_c = urllib.request.Request(cme_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req_c, timeout=6) as resp_c:
                cme_data = json.loads(resp_c.read().decode('utf-8'))
        
        chart = cme_data['chart']['result'][0]
        meta = chart['meta']
        cme_price = float(meta.get('regularMarketPrice', curr_price))
        cme_prev_close = float(meta.get('chartPreviousClose', cme_price))
        
        cme_basis = round(cme_price - curr_price, 1)
        cme_basis_pct = round((cme_basis / curr_price) * 100.0, 2)
        cme_annualized_pct = round(cme_basis_pct * (365.0 / 25.0), 1)  # approx monthly basis
        
        has_cme_gap = abs(cme_prev_close - cme_price) > 800.0
        cme_gap_level = cme_prev_close if has_cme_gap else None
        cme_gap_status = f"🚨 CME GAP AT ${cme_prev_close:,.0f}" if has_cme_gap else "✅ NO UNFILLED IMMEDIATE CME GAP"
        
        cme_arb_mode = "CASH_AND_CARRY_HEDGE" if cme_basis > 30.0 else ("BACKWARDATION_DUMP" if cme_basis < -30.0 else "NEUTRAL_BASIS")
        cme_arb_desc = (
            f"ওয়াল স্ট্রিট ক্যাশ-অ্যান্ড-ক্যারি আরবিট্রেজ চালু রেখেছে (CME প্রিমিয়াম: +${cme_basis:.1f} / {cme_annualized_pct:.1f}% বার্ষিক)। তারা স্পটে ইটিএফ কিনে CME-তে শর্ট হেজ করছে।"
            if cme_arb_mode == "CASH_AND_CARRY_HEDGE" else
            "CME ডিসকাউন্টে চলছে — প্রাতিষ্ঠানিক শর্ট সেলিং তীব্র।"
        )
        cme_status = "ONLINE"
    except Exception as e:
        print("CME fetch error:", e)
        cme_status = "DATA_OFFLINE"
        cme_price = None
        cme_basis = None
        cme_basis_pct = None
        cme_annualized_pct = None
        cme_gap_status = "⚠️ CME DATA OFFLINE"
        cme_gap_level = None
        cme_arb_mode = "DATA_OFFLINE"
        cme_arb_desc = "CME ফিউচার্স ডাটা অফলাইন — কোনো মক ডাটা ব্যবহার করা হচ্ছে না।"

    if deribit_status == "ONLINE" and cme_status == "ONLINE":
        overall_status = "ONLINE"
    elif deribit_status == "ONLINE" or cme_status == "ONLINE":
        overall_status = "DEGRADED"
    else:
        overall_status = "DATA_OFFLINE"

    return {
        "deribit": {
            "status": deribit_status,
            "max_pain_strike": max_pain_strike,
            "dist_to_max_pain": dist_to_max_pain,
            "underlying_price": round(underlying_p, 1) if underlying_p is not None else None,
            "pcr": pcr,
            "total_call_oi_btc": round(total_call_oi, 1) if total_call_oi is not None else None,
            "total_put_oi_btc": round(total_put_oi, 1) if total_put_oi is not None else None,
            "total_options_oi_btc": round(total_options_oi, 1) if total_options_oi is not None else None,
            "gamma_regime": gamma_regime,
            "gamma_badge": gamma_badge,
            "gamma_desc": gamma_desc,
            "gamma_color": gamma_color
        },
        "cme": {
            "status": cme_status,
            "cme_price": cme_price,
            "cme_basis_usd": cme_basis,
            "cme_basis_pct": cme_basis_pct,
            "cme_annualized_basis": cme_annualized_pct,
            "cme_gap_status": cme_gap_status,
            "cme_gap_level": cme_gap_level,
            "cme_arb_mode": cme_arb_mode,
            "cme_arb_desc": cme_arb_desc
        },
        "status": overall_status
    }

if __name__ == '__main__':
    data = fetch_dark_side_intelligence(78538.0)
    print(json.dumps(data, indent=2))
