"""
Coinbase Institutional Inflow Radar (CIPS Engine)
-------------------------------------------------
Quantitatively detects whether US Institutional Buying is imminent or active on Coinbase Pro / Exchange.

Key Microstructure Signals:
1. CB-OBI (Coinbase L2 Order Book Imbalance within 1% depth)
2. Premium Velocity (d(Premium)/dt: Rate of discount compression)
3. Taker Tape Delta (CVD on Coinbase last 100 fills)
4. Institutional Whale Trades (Trade size >= 0.5 BTC)
5. CIPS (Coinbase Inflow Predictive Score 0-100%)
"""

import requests
import time
from datetime import datetime

COINBASE_SPREAD_BASELINE = -125.0  # Statistical USDT vs USD offset

def analyze_coinbase_flow():
    headers = {'User-Agent': 'CoinbaseFlowRadar/1.0'}
    
    bids = []
    asks = []
    mid_cb, bids_1pct, asks_1pct, cb_obi = 0.0, 0.0, 0.0, 0.0
    trades = []
    buy_vol, sell_vol, tape_delta, buy_ratio = 0.0, 0.0, 0.0, 0.5
    whale_trades, whale_buy_vol, whale_sell_vol = [], 0.0, 0.0
    bn_spot = 0.0
    current_premium = 0.0
    relative_premium = 0.0
    premium_velocity_5m = 0.0

    # 1. Fetch Coinbase L2 Depth (Level 2 Book)
    try:
        book_res = requests.get('https://api.exchange.coinbase.com/products/BTC-USD/book?level=2', headers=headers, timeout=5)
        if book_res.status_code == 200:
            book = book_res.json()
            if isinstance(book, dict):
                bids = [(float(b[0]), float(b[1])) for b in book.get('bids', []) if len(b) >= 2]
                asks = [(float(a[0]), float(a[1])) for a in book.get('asks', []) if len(a) >= 2]
                if bids and asks:
                    mid_cb = (bids[0][0] + asks[0][0]) / 2.0
                    bids_1pct = sum(qty for p, qty in bids if p >= mid_cb * 0.99)
                    asks_1pct = sum(qty for p, qty in asks if p <= mid_cb * 1.01)
                    cb_obi = (bids_1pct - asks_1pct) / (bids_1pct + asks_1pct) if (bids_1pct + asks_1pct) > 0 else 0.0
    except Exception as e:
        pass

    # 2. Fetch Coinbase Tape & Whale Trade Clustering
    try:
        trades_res = requests.get('https://api.exchange.coinbase.com/products/BTC-USD/trades', headers=headers, timeout=5)
        if trades_res.status_code == 200:
            raw_trades = trades_res.json()
            if isinstance(raw_trades, list):
                trades = raw_trades
                buy_vol = sum(float(t['size']) for t in trades if isinstance(t, dict) and t.get('side') == 'buy')
                sell_vol = sum(float(t['size']) for t in trades if isinstance(t, dict) and t.get('side') == 'sell')
                tape_delta = buy_vol - sell_vol
                total_vol = buy_vol + sell_vol
                buy_ratio = (buy_vol / total_vol) if total_vol > 0 else 0.5
                whale_trades = [t for t in trades if isinstance(t, dict) and float(t.get('size', 0)) >= 0.5]
                whale_buy_vol = sum(float(t['size']) for t in whale_trades if t.get('side') == 'buy')
                whale_sell_vol = sum(float(t['size']) for t in whale_trades if t.get('side') == 'sell')
    except Exception as e:
        pass

    # 3. Premium Velocity (Compare CB with Binance Spot)
    try:
        bn_res = requests.get('https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT', timeout=5).json()
        if isinstance(bn_res, dict) and 'price' in bn_res:
            bn_spot = float(bn_res['price'])
            if mid_cb == 0.0 and bn_spot > 0:
                mid_cb = bn_spot
            current_premium = mid_cb - bn_spot if (mid_cb > 0 and bn_spot > 0) else 0.0
            relative_premium = current_premium - COINBASE_SPREAD_BASELINE
    except Exception as e:
        pass

    # Historical 1m candle spread velocity (last 5 min)
    try:
        cb_c = {c[0]: c for c in requests.get('https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=60', headers=headers, timeout=5).json()[:6]}
        bn_c = requests.get('https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=6', timeout=5).json()
        
        spreads = []
        for k in bn_c:
            t_sec = k[0] // 1000
            if t_sec in cb_c:
                c_cb = cb_c[t_sec][4]
                c_bn = float(k[4])
                spreads.append((t_sec, c_cb - c_bn))
        
        spreads.sort(key=lambda x: x[0])
        if len(spreads) >= 2:
            premium_velocity_5m = spreads[-1][1] - spreads[0][1] # change over 5m
        else:
            premium_velocity_5m = 0.0
    except Exception as e:
        premium_velocity_5m = 0.0

    # 3.5 Calculate Institutional Ask & Bid Wall Clusters ($50 buckets)
    from collections import defaultdict
    ask_b = defaultdict(float)
    for p, q in asks:
        if p <= mid_cb + 2500:
            ask_b[round(p/50.0)*50.0] += q
            
    bid_b = defaultdict(float)
    for p, q in bids:
        if p >= mid_cb - 2500:
            bid_b[round(p/50.0)*50.0] += q
            
    top_a = sorted(ask_b.items(), key=lambda x: x[1], reverse=True)[:5]
    top_b = sorted(bid_b.items(), key=lambda x: x[1], reverse=True)[:5]
    cb_discount_val = bn_spot - mid_cb if (bn_spot > 0 and mid_cb > 0) else 0.0
    
    top_ask_walls = [{'cb_price': p, 'bn_equiv': round(p + cb_discount_val, 1), 'btc': round(q, 1), 'usd_m': round(q*p/1e6, 2)} for p, q in sorted(top_a, key=lambda x: x[0])]
    top_bid_walls = [{'cb_price': p, 'bn_equiv': round(p + cb_discount_val, 1), 'btc': round(q, 1), 'usd_m': round(q*p/1e6, 2)} for p, q in sorted(top_b, key=lambda x: x[0], reverse=True)]

    # 3.6 Real-Time Coinbase L2 Iceberg Order Detection
    cb_icebergs = []
    try:
        from collections import defaultdict
        cb_bids_map = {round(b[0], 1): b[1] for b in bids[:50]}
        cb_asks_map = {round(a[0], 1): a[1] for a in asks[:50]}
        
        buy_v_p = defaultdict(float)
        buy_c_p = defaultdict(int)
        sell_v_p = defaultdict(float)
        sell_c_p = defaultdict(int)
        
        for t in trades:
            p_val = round(float(t['price']), 1)
            s_val = float(t['size'])
            if t['side'] == 'buy':
                buy_v_p[p_val] += s_val
                buy_c_p[p_val] += 1
            else:
                sell_v_p[p_val] += s_val
                sell_c_p[p_val] += 1
                
        # Iceberg Asks (Hidden Sell Orders being repeatedly reloaded as buyers hit ask)
        for p_val, v_tot in buy_v_p.items():
            cnt = buy_c_p[p_val]
            vis = cb_asks_map.get(p_val, 0.2)
            ratio = v_tot / max(0.05, vis)
            if (v_tot >= 1.0 and cnt >= 3 and ratio >= 2.0) or (v_tot >= 2.5 and ratio >= 1.5):
                cb_icebergs.append({
                    'exchange': 'COINBASE',
                    'side': 'ICEBERG_SELL',
                    'badge': '🧊 CB ICEBERG SELL (Hidden Ask)',
                    'color': 'var(--crimson)',
                    'price': p_val,
                    'bn_equiv': round(p_val + cb_discount_val, 1),
                    'executed_btc': round(v_tot, 2),
                    'visible_btc': round(vis, 2),
                    'refill_ratio': round(ratio, 1),
                    'fills_count': cnt
                })
                
        # Iceberg Bids (Hidden Buy Orders being repeatedly reloaded as sellers hit bid)
        for p_val, v_tot in sell_v_p.items():
            cnt = sell_c_p[p_val]
            vis = cb_bids_map.get(p_val, 0.2)
            ratio = v_tot / max(0.05, vis)
            if (v_tot >= 1.0 and cnt >= 3 and ratio >= 2.0) or (v_tot >= 2.5 and ratio >= 1.5):
                cb_icebergs.append({
                    'exchange': 'COINBASE',
                    'side': 'ICEBERG_BUY',
                    'badge': '🧊 CB ICEBERG BUY (Hidden Bid)',
                    'color': 'var(--emerald)',
                    'price': p_val,
                    'bn_equiv': round(p_val + cb_discount_val, 1),
                    'executed_btc': round(v_tot, 2),
                    'visible_btc': round(vis, 2),
                    'refill_ratio': round(ratio, 1),
                    'fills_count': cnt
                })
    except Exception as e:
        cb_icebergs = []


    # 4. Calculate CIPS (Coinbase Inflow Predictive Score: 0 to 100)
    score = 50.0 # Base neutral
    
    # Factor A: CB-OBI (Order book fortress) - weight 25 pts
    score += (cb_obi * 25.0)
    
    # Factor B: Tape Delta & Buy Ratio - weight 25 pts
    tape_factor = (buy_ratio - 0.5) * 2.0 # -1.0 to +1.0
    score += (tape_factor * 25.0)
    
    # Factor C: Normalized Institutional Premium & Velocity - weight 30 pts
    # Relative Premium > 0 means Coinbase Spot is trading ABOVE normalized baseline (Institutions Paying Premium)
    if relative_premium >= +40.0:
        score += 20.0
    elif relative_premium >= +15.0:
        score += 12.0
    elif relative_premium >= 0.0:
        score += 5.0
    elif relative_premium <= -30.0:
        score -= 15.0
        
    if premium_velocity_5m > +15.0: # Rapid compression (Bullish front-running)
        score += 15.0
    elif premium_velocity_5m < -15.0: # Deepening discount (Bearish dump)
        score -= 15.0

    # Factor D: Whale Blocks (>= 0.5 BTC) - weight 20 pts
    if whale_buy_vol > whale_sell_vol:
        score += min(20.0, (whale_buy_vol - whale_sell_vol) * 5.0)
    elif whale_sell_vol > whale_buy_vol:
        score -= min(20.0, (whale_sell_vol - whale_buy_vol) * 5.0)

    # 5. Algorithmic TWAP Execution Detector (Catches Sliced Micro-Orders)
    # If Coinbase discount is deep (< -$40) and taker buy ratio < 46%, 
    # it is an INSTITUTIONAL TWAP DUMPING PROGRAM disguised as small trades!
    is_twap_dump = False
    is_twap_accum = False
    
    # When relative_premium < -25 (deep discount vs baseline) + heavy selling: TWAP Dump
    if relative_premium < -25.0 and buy_ratio < 0.46:
        is_twap_dump = True
        twap_status = "INSTITUTIONAL_ALGORITHMIC_TWAP_DUMP"
        twap_badge = "🚨 INSTITUTIONAL TWAP DUMP (Sliced Orders)"
        twap_desc = "মার্কিন ফান্ডরা ক্ষুদ্র ক্ষুদ্র অর্ডারে (TWAP) নিঃশব্দে আসল স্পট ডাম্প করছে! রিটেইল ভেবে ভুল করবেন না।"
        score = min(score, 18.0) # Hard-cap score to heavy outflow
    # When relative_premium > +20 (elevated buying above baseline) + buy_ratio > 0.52: TWAP Accumulation
    elif relative_premium > +20.0 and buy_ratio > 0.52:
        is_twap_accum = True
        twap_status = "INSTITUTIONAL_ALGORITHMIC_TWAP_ACCUMULATION"
        twap_badge = "🟢 INSTITUTIONAL TWAP ACCUMULATION (Stealth Buy)"
        twap_desc = "মার্কিন প্রতিষ্ঠানগুলো সাইলেন্ট অ্যালগরিদমিক স্পট বাই প্রোগ্রাম চালাচ্ছে।"
        score = max(score, 75.0)
    else:
        twap_status = "ORGANIC_FLOW"
        twap_badge = "⚪ ORGANIC / BALANCED FLOW"
        twap_desc = "কোনো বিশেষ অ্যালগরিদমিক স্পট এক্সিকিউশন শনাক্ত হয়নি।"

    score = max(0.0, min(100.0, score))
    
    # State evaluation
    if score >= 75.0:
        signal = "🟢 INSTITUTIONAL INFLOW ACTIVE (High Conviction Buying)"
    elif score >= 60.0:
        signal = "🟡 ACCUMULATION EARLY SIGNS (Bids Thickening / Velocity Compressing)"
    elif score <= 25.0:
        signal = "🔴 HEAVY INSTITUTIONAL OUTFLOW (Spot Dumping Dominant)"
    elif score <= 40.0:
        signal = "🟠 ABSORPTION ABSENT / BEARISH SKEW"
    else:
        signal = "⚪ NEUTRAL CONSOLIDATION"

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cb_mid": mid_cb,
        "bn_spot": bn_spot,
        "current_premium": round(relative_premium, 2),
        "raw_premium": round(current_premium, 2),
        "relative_premium": round(relative_premium, 2),
        "premium_velocity_5m": premium_velocity_5m,
        "cb_obi_1pct": cb_obi,
        "bids_1pct_btc": bids_1pct,
        "asks_1pct_btc": asks_1pct,
        "last_100_delta_btc": tape_delta,
        "buy_ratio_pct": buy_ratio * 100.0,
        "whale_trades_count": len(whale_trades),
        "whale_buy_btc": whale_buy_vol,
        "whale_sell_btc": whale_sell_vol,
        "twap_status": twap_status,
        "twap_badge": twap_badge,
        "twap_desc": twap_desc,
        "is_twap_dump": is_twap_dump,
        "cips_score": round(score, 1),
        "signal": signal,
        "top_ask_walls": top_ask_walls,
        "top_bid_walls": top_bid_walls,
        "active_icebergs": cb_icebergs
    }

if __name__ == '__main__':
    res = analyze_coinbase_flow()
    import json
    print(json.dumps(res, indent=2))
