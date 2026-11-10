import os
import sys
import urllib.request
import json
import requests
from datetime import datetime, timezone

core_dir = os.path.dirname(os.path.abspath(__file__))
if core_dir not in sys.path:
    sys.path.insert(0, core_dir)

try:
    from market_cache import cached_get_json, TTL_KLINES
except Exception:
    cached_get_json = None
    TTL_KLINES = 15

def get_json(url):
    if cached_get_json:
        data = cached_get_json(url, ttl_seconds=TTL_KLINES, timeout=8)
        if data is not None:
            return data
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return []

def compute_retention_ratio(p1_spot_delta, p2_spot_delta):
    if p1_spot_delta <= 0:
        return 0.0
    retained_spot = p1_spot_delta + p2_spot_delta
    retention_ratio_pct = round((retained_spot / p1_spot_delta) * 100.0, 2)
    return max(-100.0, min(100.0, retention_ratio_pct))

def find_anchor_cycle_low(klines_bn_spot, min_window=24):
    """
    Anchor to the cycle low across the dataset with minimum lookback window.
    Enforce a minimum window of at least 24 bars (2 hours) so a fresh low
    in recent candles does not collapse accumulation context.
    Returns (min_idx, min_low).
    """
    if not klines_bn_spot:
        return 0, 0.0

    eff_min_window = min_window if len(klines_bn_spot) >= min_window else len(klines_bn_spot)
    search_slice = klines_bn_spot[:-eff_min_window] if len(klines_bn_spot) > eff_min_window else klines_bn_spot

    min_idx = 0
    min_low = float('inf')
    for i, k in enumerate(search_slice):
        l = float(k[3]) if isinstance(k, (list, tuple)) else float(k.get('low', k.get('l', 0.0)))
        if l < min_low:
            min_low = l
            min_idx = i

    if len(klines_bn_spot) - min_idx < eff_min_window:
        min_idx = max(0, len(klines_bn_spot) - eff_min_window)
        k_at = klines_bn_spot[min_idx]
        min_low = float(k_at[3]) if isinstance(k_at, (list, tuple)) else float(k_at.get('low', k_at.get('l', 0.0)))

    return min_idx, min_low

def analyze_whale_inventory():
    """
    REAL SPOT & INSTITUTIONAL WHALE TRACKER
    --------------------------------------
    Distinguishes REAL Settled Spot Bitcoins (Coinbase Spot + Binance Spot) 
    from VIRTUAL Paper Futures Leverage (Binance Perps).
    """
    # 1. Binance Spot 5m Klines (Real Spot Cash BTC)
    try:
        klines_bn_spot = get_json('https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=300')
    except Exception as e:
        print(f"Error fetching Binance spot: {e}")
        klines_bn_spot = []

    # 2. Coinbase Spot 5m Candles (Real US Institutional Spot)
    try:
        cb_candles = get_json('https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=300')[:300]
    except Exception as e:
        print(f"Error fetching Coinbase candles: {e}")
        cb_candles = []

    # 3. Binance Futures 5m Klines (Virtual Paper Leverage Contracts)
    try:
        klines_perp = get_json('https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=5m&limit=300')
    except Exception as e:
        print(f"Error fetching Binance perps: {e}")
        klines_perp = []

    if not klines_bn_spot or not klines_perp:
        return {}

    min_idx, min_low = find_anchor_cycle_low(klines_bn_spot, min_window=24)

    anchor_spot = klines_bn_spot[min_idx:]
    anchor_perp = klines_perp[min_idx:] if min_idx < len(klines_perp) else klines_perp[-len(anchor_spot):]
    
    current_price = float(anchor_spot[-1][4])
    anchor_time = datetime.fromtimestamp(anchor_spot[0][0]/1000, timezone.utc)

    # 1. Real Binance Spot Delta
    bn_spot_buy = sum(float(k[9]) for k in anchor_spot)
    bn_spot_vol = sum(float(k[5]) for k in anchor_spot)
    bn_spot_sell = bn_spot_vol - bn_spot_buy
    bn_spot_delta = bn_spot_buy - bn_spot_sell

    # 2. Real Coinbase Spot Delta (Directional intra-bar volume)
    cb_spot_delta = 0.0
    cb_spot_vol = 0.0
    # Map by timestamp
    start_ts_sec = anchor_spot[0][0] // 1000
    for c in cb_candles:
        # c: [time, low, high, open, close, volume]
        c_time = c[0]
        if c_time >= start_ts_sec:
            v = float(c[5])
            o = float(c[3])
            cl = float(c[4])
            h = float(c[2])
            l = float(c[1])
            cb_spot_vol += v
            if h > l:
                cb_spot_delta += v * ((cl - o) / (h - l))

    # Real Spot Total Whale Bag
    real_spot_bag_btc = bn_spot_delta + cb_spot_delta
    real_spot_usd_val = real_spot_bag_btc * current_price
    real_spot_usd_millions = real_spot_usd_val / 1e6

    # 3. Virtual Paper Futures Leverage Delta
    perp_buy = sum(float(k[9]) for k in anchor_perp)
    perp_vol = sum(float(k[5]) for k in anchor_perp)
    perp_sell = perp_vol - perp_buy
    perp_paper_delta = perp_buy - perp_sell

    # Anchored Spot VWAP
    tot_vol_price = sum(((float(k[2])+float(k[3])+float(k[4]))/3.0)*float(k[5]) for k in anchor_spot)
    anchored_spot_vwap = (tot_vol_price / bn_spot_vol) if bn_spot_vol > 0 else current_price

    # Spot vs Paper Divergence Verdict
    if real_spot_bag_btc < -100.0 and perp_paper_delta > +200.0:
        divergence_status = "FAKE_PAPER_PUMP_TRAP"
        divergence_badge = "🚨 FAKE PAPER TRAP (SPOT DUMPING)"
        divergence_desc = "সাবধান! ফিউচার্সে ভার্চুয়াল পেপার লং হলেও আসল স্পটে (Coinbase/Binance) কোটি কোটি টাকার বিটকয়েন ডাম্প হচ্ছে!"
    elif real_spot_bag_btc > +100.0 and perp_paper_delta < -100.0:
        divergence_status = "GENUINE_SPOT_ACCUMULATION"
        divergence_badge = "🚀 INSTITUTIONAL SPOT ACCUMULATION"
        divergence_desc = "আসল স্পট বিটকয়েন ক্যাশ দিয়ে কেনা হচ্ছে, ফিউচার্স শর্টদের ফাঁদে ফেলার জোরালো সম্ভাবনা!"
    elif real_spot_bag_btc >= 0:
        divergence_status = "HEALTHY_SPOT_INFLOW"
        divergence_badge = "🟢 REAL SPOT INFLOW ACTIVE"
        divergence_desc = "স্পট মার্কেটে আসল বিটকয়েন বায়াররা পজিটিভ অবস্থায় আছে।"
    else:
        divergence_status = "SPOT_OUTFLOW"
        divergence_badge = "🔴 REAL SPOT OUTFLOW"
        divergence_desc = "স্পট মার্কেটে নিট সেলিং প্রেসার চলমান।"

    # PnL status of real spot bag
    if real_spot_bag_btc > 0:
        pnl_usd = real_spot_bag_btc * (current_price - anchored_spot_vwap)
        pnl_pct = ((current_price - anchored_spot_vwap) / anchored_spot_vwap * 100.0) if anchored_spot_vwap > 0 else 0.0
        pnl_status = "IN_PROFIT" if pnl_usd >= 0 else "UNDERWATER"
        pnl_badge = "🟢 IN PROFIT" if pnl_usd >= 0 else "🔴 UNDERWATER"
    else:
        # Whales dumped spot inventory (Net Negative Spot Delta)
        pnl_usd = 0.0
        pnl_pct = 0.0
        pnl_status = "NET_DUMPED"
        pnl_badge = "🔴 NET DUMPED"

    # Phase Partitioning:
    # Identify swing peak within the anchor cycle
    peak_idx = 0
    peak_high = -float('inf')
    for i, k in enumerate(anchor_spot):
        h = float(k[2])
        if h > peak_high:
            peak_high = h
            peak_idx = i

    if peak_idx >= len(anchor_spot) - 1:
        # Currently at or near cycle high: Phase 1 active, Phase 2 beginning
        p1_spot = anchor_spot
        p2_spot = []
        p1_perp = anchor_perp
        p2_perp = []
    elif peak_idx == 0:
        # High was at start of window
        p1_spot = anchor_spot[:1]
        p2_spot = anchor_spot[1:]
        p1_perp = anchor_perp[:1]
        p2_perp = anchor_perp[1:]
    else:
        p1_spot = anchor_spot[:peak_idx + 1]
        p2_spot = anchor_spot[peak_idx + 1:]
        p1_perp = anchor_perp[:peak_idx + 1]
        p2_perp = anchor_perp[peak_idx + 1:]

    # Phase 1 metrics
    p1_perp_buy = sum(float(k[9]) for k in p1_perp) if p1_perp else 0.0
    p1_perp_vol = sum(float(k[5]) for k in p1_perp) if p1_perp else 0.0
    p1_perp_sell = p1_perp_vol - p1_perp_buy
    p1_perp_delta = p1_perp_buy - p1_perp_sell

    p1_spot_buy = sum(float(k[9]) for k in p1_spot) if p1_spot else 0.0
    p1_spot_vol = sum(float(k[5]) for k in p1_spot) if p1_spot else 0.0
    p1_spot_sell = p1_spot_vol - p1_spot_buy
    p1_spot_delta = p1_spot_buy - p1_spot_sell
    p1_duration = len(p1_spot) * 5

    # Phase 2 metrics
    p2_perp_buy = sum(float(k[9]) for k in p2_perp) if p2_perp else 0.0
    p2_perp_vol = sum(float(k[5]) for k in p2_perp) if p2_perp else 0.0
    p2_perp_sell = p2_perp_vol - p2_perp_buy
    p2_perp_delta = p2_perp_buy - p2_perp_sell

    p2_spot_buy = sum(float(k[9]) for k in p2_spot) if p2_spot else 0.0
    p2_spot_vol = sum(float(k[5]) for k in p2_spot) if p2_spot else 0.0
    p2_spot_sell = p2_spot_vol - p2_spot_buy
    p2_spot_delta = p2_spot_buy - p2_spot_sell
    p2_duration = len(p2_spot) * 5
    p2_released = p2_spot_delta + p2_perp_delta

    # Genuine retention ratio calculation:
    # Measures the percentage of Phase 1 accumulated spot inventory retained through Phase 2
    if p1_spot_delta > 0:
        retention_ratio_pct = compute_retention_ratio(p1_spot_delta, p2_spot_delta)
    else:
        retention_ratio_pct = round((real_spot_bag_btc / max(1.0, bn_spot_vol)) * 100.0, 2)
        retention_ratio_pct = max(-100.0, min(100.0, retention_ratio_pct))

    confidence_pct = round(min(98.0, max(60.0, 72.0 + (min(len(anchor_spot), 120) / 120.0) * 15.0 + (10.0 if abs(real_spot_bag_btc) > 20 else 0.0))), 1)

    result = {
        "anchor_low": round(min_low, 1),
        "peak_high": round(peak_high, 1),
        "anchor_time_utc": anchor_time.strftime("%Y-%m-%d %H:%M:%S"),
        "current_price": current_price,
        "anchored_vwap": round(anchored_spot_vwap, 1),
        
        # Primary Real Spot Inventory Bag
        "real_spot_bag": {
            "net_btc": round(real_spot_bag_btc, 1),
            "usd_value": round(real_spot_usd_val, 0),
            "usd_millions": round(real_spot_usd_millions, 2),
            "coinbase_spot_delta": round(cb_spot_delta, 1),
            "binance_spot_delta": round(bn_spot_delta, 1),
            "cost_basis_avwap": round(anchored_spot_vwap, 1),
            "unrealized_pnl_usd": round(pnl_usd, 0),
            "unrealized_pnl_pct": round(pnl_pct, 2),
            "pnl_status": pnl_status,
            "pnl_badge": pnl_badge
        },
        
        # Virtual Paper Futures Leverage Bag
        "paper_futures_bag": {
            "net_btc": round(perp_paper_delta, 1),
            "note": "Virtual Synthetic Leverage Contracts (Not Real Settled BTC)"
        },
        
        # Spot vs Paper Divergence Engine
        "divergence": {
            "status": divergence_status,
            "badge": divergence_badge,
            "desc": divergence_desc
        },
        
        # Backward compatibility aliases for existing dashboard keys
        "whale_bag": {
            "net_btc": round(real_spot_bag_btc, 1),
            "usd_value": round(real_spot_usd_val, 0),
            "usd_millions": round(real_spot_usd_millions, 2),
            "cost_basis_avwap": round(anchored_spot_vwap, 1),
            "unrealized_pnl_usd": round(pnl_usd, 0),
            "unrealized_pnl_pct": round(pnl_pct, 2),
            "pnl_status": pnl_status,
            "pnl_badge": pnl_badge,
            "is_real_spot": True
        },
        "inventory_ledger": {
            "net_retained_btc": round(real_spot_bag_btc, 1),
            "retention_ratio_pct": retention_ratio_pct
        },
        "phase1_accumulation": {
            "duration_minutes": p1_duration,
            "perp_taker_buy": round(p1_perp_buy, 1),
            "perp_taker_sell": round(p1_perp_sell, 1),
            "perp_net_delta": round(p1_perp_delta, 1),
            "spot_net_delta": round(p1_spot_delta, 1),
            "combined_net_accumulated": round(p1_spot_delta + p1_perp_delta, 1)
        },
        "phase2_pullback_dump": {
            "duration_minutes": p2_duration,
            "perp_taker_buy": round(p2_perp_buy, 1),
            "perp_taker_sell": round(p2_perp_sell, 1),
            "perp_net_delta": round(p2_perp_delta, 1),
            "spot_net_delta": round(p2_spot_delta, 1),
            "combined_net_released": round(p2_released, 1)
        },
        "diagnostic": {
            "classification": divergence_status,
            "confidence_pct": confidence_pct,
            "reasons": [divergence_desc]
        }
    }
    return result

if __name__ == "__main__":
    res = analyze_whale_inventory()
    print(json.dumps(res, indent=2))
