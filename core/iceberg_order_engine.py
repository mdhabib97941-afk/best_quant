"""
Coinbase Institutional Iceberg Order Engine (US Smart Money Only)
=================================================================
Tracks real-time hidden refill orders EXCLUSIVELY on Coinbase Spot (US Institutions).
Binance futures algo noise is completely excluded.
Features:
- Coinbase Spot L2 Order Book & Trade Flow Micro-Refill Scanning
- Real-time Binance Equivalent Price Calculation (cb_price + cb_discount)
- Coinbase Net Iceberg Imbalance & Power Split (US Spot Buy vs Sell)
- Institutional Iceberg Anchors for Sniper Entry, Tight SL, and Precise TP
- Anti-Spam Telegram Notice Dispatch (Strict 45m global cooldown, 2h zone cooldown)
"""

import os
import sys
import json
import time
import urllib.request
import datetime
import threading

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

TELEGRAM_BOT_TOKEN = "8918704289:AAFg33hZSpa0XrUTFah4TakDBx6ryrAHHgU"
TELEGRAM_CHAT_ID = "7736288854"

_FILE_LOCK = threading.RLock()

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
BUFFER_FILE = os.path.join(CORE_DIR, "iceberg_rolling_buffer.json")
ALERT_STATE_FILE = os.path.join(CORE_DIR, "iceberg_alert_state.json")

try:
    from market_cache import get_market_cache, TTL_ORDERBOOK
except ImportError:
    try:
        from core.market_cache import get_market_cache, TTL_ORDERBOOK
    except ImportError:
        get_market_cache = None

def robust_get_json(url, timeout=6):
    cache = get_market_cache() if get_market_cache else None
    if cache:
        res = cache.cached_get_json(url, timeout=timeout, ttl=TTL_ORDERBOOK)
        if res is not None:
            return res
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception:
        return None

def load_json_file(filepath, default_val):
    with _FILE_LOCK:
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return default_val

def save_json_file(filepath, data):
    tmp_path = f"{filepath}.tmp.{os.getpid()}_{threading.get_ident()}_{time.time()}"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        for attempt in range(3):
            try:
                with _FILE_LOCK:
                    os.replace(tmp_path, filepath)
                break
            except (OSError, PermissionError) as pe:
                if attempt < 2:
                    time.sleep(0.01)
                else:
                    raise pe
        return True
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False

def send_telegram_alert(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            return res.get("ok", False)
    except Exception as e:
        print(f"Error sending Coinbase Iceberg Telegram alert: {e}")
        return False

def scan_live_icebergs(curr_price=80000.0, cb_discount=0.0):
    """
    Scans recent trades and L2 depth EXCLUSIVELY on Coinbase Spot (US Institutions).
    Calculates Binance Equivalent price for every level so the user can execute on Binance.
    """
    detected = []
    
    try:
        cb_trades = robust_get_json('https://api.exchange.coinbase.com/products/BTC-USD/trades?limit=150')
        cb_book = robust_get_json('https://api.exchange.coinbase.com/products/BTC-USD/book?level=2')
        if cb_trades and cb_book:
            cb_bids = cb_book.get('bids', [])[:150]
            cb_asks = cb_book.get('asks', [])[:150]
            
            # Determine dynamic Coinbase discount if not passed
            if cb_bids and cb_asks:
                mid_cb = (float(cb_bids[0][0]) + float(cb_asks[0][0])) / 2.0
                calc_discount = curr_price - mid_cb if curr_price > 0 else 0.0
            else:
                calc_discount = cb_discount
                
            cb_bids_map = {round(float(b[0]), 1): float(b[1]) for b in cb_bids}
            cb_asks_map = {round(float(a[0]), 1): float(a[1]) for a in cb_asks}
            
            from collections import defaultdict
            buy_v_p = defaultdict(float)
            buy_c_p = defaultdict(int)
            sell_v_p = defaultdict(float)
            sell_c_p = defaultdict(int)
            
            for t in cb_trades:
                p_val = round(float(t['price']), 1)
                s_val = float(t['size'])
                if t['side'] == 'buy':
                    buy_v_p[p_val] += s_val
                    buy_c_p[p_val] += 1
                else:
                    sell_v_p[p_val] += s_val
                    sell_c_p[p_val] += 1
                    
            # 1. Coinbase Iceberg Asks (Hidden Sell Walls being hit by buyers)
            for p_val, v_tot in buy_v_p.items():
                cnt = buy_c_p[p_val]
                vis = cb_asks_map.get(p_val, 0.1)
                ratio = v_tot / max(0.04, vis)
                # Institutional thresholds on Coinbase spot
                if (v_tot >= 0.20 and cnt >= 3 and ratio >= 2.0) or (v_tot >= 0.60 and ratio >= 1.5) or (v_tot >= 1.20):
                    bn_p = round(p_val + calc_discount, 1)
                    detected.append({
                        'id': f"CB_SELL_{p_val}",
                        'exchange': 'COINBASE',
                        'side': 'ICEBERG_SELL',
                        'badge': '🏛️ CB ICEBERG SELL (Hidden Ask Wall)',
                        'color': 'var(--crimson)',
                        'price': p_val,
                        'cb_price': p_val,
                        'bn_equiv': bn_p,
                        'executed_btc': round(v_tot, 2),
                        'visible_btc': round(vis, 2),
                        'refill_ratio': round(ratio, 1),
                        'fills_count': cnt,
                        'timestamp': int(time.time())
                    })
                    
            # 2. Coinbase Iceberg Bids (Hidden Buy Cushions being hit by sellers)
            for p_val, v_tot in sell_v_p.items():
                cnt = sell_c_p[p_val]
                vis = cb_bids_map.get(p_val, 0.1)
                ratio = v_tot / max(0.04, vis)
                if (v_tot >= 0.20 and cnt >= 3 and ratio >= 2.0) or (v_tot >= 0.60 and ratio >= 1.5) or (v_tot >= 1.20):
                    bn_p = round(p_val + calc_discount, 1)
                    detected.append({
                        'id': f"CB_BUY_{p_val}",
                        'exchange': 'COINBASE',
                        'side': 'ICEBERG_BUY',
                        'badge': '🏛️ CB ICEBERG BUY (Hidden Bid Cushion)',
                        'color': 'var(--emerald)',
                        'price': p_val,
                        'cb_price': p_val,
                        'bn_equiv': bn_p,
                        'executed_btc': round(v_tot, 2),
                        'visible_btc': round(vis, 2),
                        'refill_ratio': round(ratio, 1),
                        'fills_count': cnt,
                        'timestamp': int(time.time())
                    })
    except Exception as e:
        print(f"Error scanning Coinbase institutional icebergs: {e}")
        
    return detected

def update_rolling_buffer(raw_detected, curr_price):
    """
    Maintains a rolling 20-minute persistent buffer of Coinbase icebergs.
    Prunes broken/consumed levels and updates volume upon refills.
    """
    buffer_data = load_json_file(BUFFER_FILE, {"icebergs": {}, "last_update": 0})
    icebergs = buffer_data.get("icebergs", {})
    now_ts = int(time.time())
    
    # 1. Update/Add newly detected Coinbase icebergs (Purge any old Binance icebergs)
    for d in raw_detected:
        if d.get('exchange') != 'COINBASE':
            continue
        k = d['id']
        if k in icebergs:
            existing = icebergs[k]
            existing['executed_btc'] = round(existing.get('executed_btc', 0.0) + d['executed_btc'], 2)
            existing['refill_ratio'] = max(existing.get('refill_ratio', 1.0), d['refill_ratio'])
            existing['fills_count'] = existing.get('fills_count', 0) + d['fills_count']
            existing['bn_equiv'] = d.get('bn_equiv', existing.get('bn_equiv', d['price']))
            existing['last_refill'] = now_ts
            existing['status'] = 'ACTIVE'
        else:
            d['first_detected'] = now_ts
            d['last_refill'] = now_ts
            d['status'] = 'ACTIVE'
            icebergs[k] = d

    # 2. Check for barrier breaches / consumption & age pruning
    to_delete = []
    for k, item in list(icebergs.items()):
        # Purge any stale non-Coinbase items
        if item.get('exchange') != 'COINBASE':
            to_delete.append(k)
            continue
            
        p_eval = item.get('bn_equiv', item['price'])
        side = item['side']
        age = now_ts - item.get('last_refill', now_ts)
        
        # Invalidation logic on Binance price scale:
        if side == 'ICEBERG_SELL' and curr_price > (p_eval + 65.0):
            item['status'] = 'CONSUMED'
        elif side == 'ICEBERG_BUY' and curr_price < (p_eval - 65.0):
            item['status'] = 'BROKEN'
        else:
            if item.get('status') in ['CONSUMED', 'BROKEN']:
                if side == 'ICEBERG_SELL' and curr_price <= (p_eval + 45.0):
                    item['status'] = 'ACTIVE'
                elif side == 'ICEBERG_BUY' and curr_price >= (p_eval - 45.0):
                    item['status'] = 'ACTIVE'

        # Prune inactive items older than 25 minutes (1500s)
        if age > 1500 or (item['status'] != 'ACTIVE' and age > 400):
            to_delete.append(k)

    for k in to_delete:
        del icebergs[k]
        
    buffer_data["icebergs"] = icebergs
    buffer_data["last_update"] = now_ts
    save_json_file(BUFFER_FILE, buffer_data)
    
    return list(icebergs.values())

def compute_true_accumulation_distribution(curr_price, cb_premium, cb_obi, cb_tape_delta, buy_vol, sell_vol, vwap_sell, vwap_buy):
    """
    Mathematical synthesis model (IADI: Iceberg Institutional Accumulation vs Distribution Index).
    Computes whether Coinbase Icebergs represent TRUE ACCUMULATION or TRUE DISTRIBUTION.
    Range: -100.0 (Extreme Distribution / Dump) to +100.0 (Aggressive Spot Accumulation / Pump).
    """
    tot_vol = buy_vol + sell_vol
    
    # Factor 1: Iceberg Volume Imbalance (weight: 35 pts)
    r_ice = (buy_vol - sell_vol) / max(0.1, tot_vol)
    s_ice = r_ice * 35.0

    # Factor 2: Coinbase Premium / Spot Pricing Reality (weight: 30 pts)
    if cb_premium >= 15.0:
        s_prem = 30.0
        p_desc = f"Coinbase Premium +${cb_premium:.1f} (US Whales Buying at Premium)"
    elif cb_premium >= 0.0:
        s_prem = 20.0
        p_desc = f"Coinbase Premium +${cb_premium:.1f} (Positive Smart Money Inflow)"
    elif cb_premium >= -30.0:
        s_prem = 5.0
        p_desc = f"Coinbase Premium ${cb_premium:.1f} (Fair Value Neutral Spread)"
    elif cb_premium >= -65.0:
        s_prem = -15.0
        p_desc = f"Coinbase Discount ${cb_premium:.1f} (Moderate Spot Discount Selling)"
    elif cb_premium >= -110.0:
        s_prem = -25.0
        p_desc = f"Coinbase Discount ${cb_premium:.1f} (Heavy Institutional Outflow)"
    else:
        s_prem = -30.0
        p_desc = f"Coinbase Deep Discount ${cb_premium:.1f} (Severe Spot Dumping / Liquidation)"

    # Factor 3: Barrier Impact & Price Action / Kyle's Lambda (weight: 20 pts)
    if vwap_buy and (curr_price <= vwap_buy + 30.0) and cb_premium < -50.0:
        s_res = -15.0
        r_desc = f"Passive Buy Cushion ($BN {vwap_buy:,.1f}) under relentless sell attack"
    elif vwap_sell and (curr_price >= vwap_sell - 35.0) and cb_premium < -50.0:
        s_res = -20.0
        r_desc = f"Price capped below Coinbase Sell Wall ($BN {vwap_sell:,.1f})"
    elif vwap_buy and (curr_price > vwap_buy + 50.0) and cb_tape_delta > 0.0:
        s_res = 20.0
        r_desc = f"Cushion ($BN {vwap_buy:,.1f}) successfully deflected sells & ignited bounce"
    else:
        s_res = 0.0
        r_desc = "Price oscillating between institutional barriers"

    # Factor 4: L2 Order Book Fortress Imbalance (weight: 15 pts)
    s_obi = max(-15.0, min(15.0, cb_obi * 15.0))
    obi_desc = f"CB L2 1% Depth OBI: {cb_obi*100:+.1f}% ({'Bids Dominant' if cb_obi > 0 else 'Asks Dominant'})"

    # Total Mathematical IADI
    iadi = round(s_ice + s_prem + s_res + s_obi, 1)
    
    # Classification & Action Matrix
    if iadi <= -35.0:
        regime_type = "TRUE_DISTRIBUTION"
        badge = f"🔴 TRUE DISTRIBUTION ({iadi:+.1f} Score)"
        color = "var(--crimson)"
        bias = "SHORT"
        verdict = "ইউএস প্রাতিষ্ঠানিক ডিস্ট্রিবিউশন (সেলারদের ডাম্প প্রেশার নিশ্চিত)"
        explanation = f"Coinbase-এ গভীর ডিসকাউন্টে (${cb_premium:.1f}) আসল স্পট বিটকয়েন ডাম্প হচ্ছে। বায়াররা সামান্য লিমিট বিড কুশন দিয়ে ঠেকানোর চেষ্টা করলেও সেলিং প্রেশার অপ্রতিরোধ্য। এটি আসল একুমুলেশন নয়, বরং স্পষ্ট ডিস্ট্রিবিউশন!"
        action = "লং এন্ট্রি সম্পূর্ণ নিষিদ্ধ! প্রতিটি বাউন্সে আইসবার্গ সেল ওয়ালে শর্ট নিন।"
    elif iadi >= 35.0:
        regime_type = "TRUE_ACCUMULATION"
        badge = f"🟢 TRUE ACCUMULATION ({iadi:+.1f} Score)"
        color = "var(--emerald)"
        bias = "LONG"
        verdict = "ইউএস প্রাতিষ্ঠানিক আসল একুমুলেশন (স্পট ক্যাশ বাই সক্রিয়)"
        explanation = f"Coinbase Spot-এ আসল ক্যাশ ডলার দিয়ে বিটকয়েন কেনা হচ্ছে, প্রিমিয়াম পজিটিভ এবং বায়াররা সেলারদের ডিপ সম্পূর্ণ অ্যাবজর্ব করে প্রাইস ডিফেন্ড করছে।"
        action = "আইসবার্গ বাই কুশনে নিরাপদে লং এন্ট্রি নিন।"
    elif s_prem <= -20.0:
        regime_type = "BEARISH_PASSIVE_CUSHION"
        badge = f"⚠️ PASSIVE CUSHION ({iadi:+.1f} Score)"
        color = "var(--amber)"
        bias = "SHORT"
        verdict = "প্যাসিভ বিড কুশন (ডাম্প প্রেশারের মুখে সাময়িক সাপোর্ট)"
        explanation = f"বায়াররা নিচে প্যাসিভ বিড কুশন রেখেছে (Buy Vol: {buy_vol:.1f} BTC), কিন্তু ইউএস স্পট ডিসকাউন্ট (${cb_premium:.1f}) নির্দেশ করে সেলাররা এখনো বাজার নিয়ন্ত্রণ করছে। এই কুশন ভাঙলে দ্রুত নিচে ফল করবে!"
        action = "শর্ট ট্রেড ধরে রাখুন। কুশনে ৫০% প্রফিট বুক করে স্টপলস এন্ট্রিতে লক করুন।"
    else:
        regime_type = "RANGE_EQUILIBRIUM"
        badge = f"⚪ CONSOLIDATION ({iadi:+.1f} Score)"
        color = "var(--cyan)"
        bias = "NEUTRAL"
        verdict = "রেঞ্জ কনসোলিডেশন (দ্বিমুখী ব্যালেন্সড লড়াই)"
        explanation = f"Coinbase Spot-এ ক্রেতা ও বিক্রেতাদের মধ্যে টানাপোড়েন চলছে। ব্রেকআউটের জন্য অপেক্ষা করুন।"
        action = "রেঞ্জের চরম সীমায় (উইক বা আইসবার্গ দেয়াল) ছোট স্ক্যাল্প ছাড়া বড় পজিশন নেওয়া ঝুঁকিপূর্ণ।"

    return {
        "iadi_score": iadi,
        "regime_type": regime_type,
        "badge": badge,
        "color": color,
        "bias": bias,
        "verdict": verdict,
        "explanation": explanation,
        "action": action,
        "math_breakdown": {
            "iceberg_score": round(s_ice, 1),
            "premium_score": round(s_prem, 1),
            "resilience_score": round(s_res, 1),
            "obi_score": round(s_obi, 1),
            "premium_desc": p_desc,
            "resilience_desc": r_desc,
            "obi_desc": obi_desc,
            "formula": "IADI = Iceberg_Imbalance(35%) + CB_Premium(30%) + Barrier_Resilience(20%) + L2_Fortress(15%)"
        }
    }

def compute_iceberg_analytics(iceberg_list, curr_price, cb_premium=0.0, cb_obi=0.0, cb_tape_delta=0.0):
    """
    Computes Net Coinbase Iceberg Imbalance, Power Split, VWAP Anchors,
    and runs the True Accumulation vs Distribution Mathematical Engine.
    """
    cb_only = [x for x in iceberg_list if x.get('exchange') == 'COINBASE']
    active_buys = [x for x in cb_only if x.get('status') == 'ACTIVE' and 'BUY' in x.get('side', '')]
    active_sells = [x for x in cb_only if x.get('status') == 'ACTIVE' and 'SELL' in x.get('side', '')]
    
    buy_vol = sum(x.get('executed_btc', 0.0) for x in active_buys)
    sell_vol = sum(x.get('executed_btc', 0.0) for x in active_sells)
    total_vol = buy_vol + sell_vol
    
    if total_vol > 0:
        buy_pct = round((buy_vol / total_vol) * 100.0, 1)
        sell_pct = round(100.0 - buy_pct, 1)
    else:
        buy_pct = 50.0
        sell_pct = 50.0
        
    # Anchors: Volume-weighted average price (VWAP) projected on Binance futures scale
    sells_above = [x for x in active_sells if x.get('bn_equiv', x['price']) >= curr_price - 25.0]
    buys_below = [x for x in active_buys if x.get('bn_equiv', x['price']) <= curr_price + 25.0]
    
    if sells_above:
        vwap_sell = sum(x.get('bn_equiv', x['price']) * x.get('executed_btc', 1.0) for x in sells_above) / sum(x.get('executed_btc', 1.0) for x in sells_above)
    else:
        vwap_sell = None
        
    if buys_below:
        vwap_buy = sum(x.get('bn_equiv', x['price']) * x.get('executed_btc', 1.0) for x in buys_below) / sum(x.get('executed_btc', 1.0) for x in buys_below)
    else:
        vwap_buy = None

    all_active = active_buys + active_sells
    max_refill_item = max(all_active, key=lambda x: x.get('refill_ratio', 0.0)) if all_active else None

    # Run Mathematical Accumulation vs Distribution Engine
    true_regime = compute_true_accumulation_distribution(
        curr_price=curr_price,
        cb_premium=cb_premium,
        cb_obi=cb_obi,
        cb_tape_delta=cb_tape_delta,
        buy_vol=buy_vol,
        sell_vol=sell_vol,
        vwap_sell=vwap_sell,
        vwap_buy=vwap_buy
    )

    return {
        "active_count": len(all_active),
        "total_buy_vol_btc": round(buy_vol, 2),
        "total_sell_vol_btc": round(sell_vol, 2),
        "total_vol_btc": round(total_vol, 2),
        "buy_power_pct": buy_pct,
        "sell_power_pct": sell_pct,
        "vwap_sell_anchor": round(vwap_sell, 1) if vwap_sell else None,
        "vwap_buy_anchor": round(vwap_buy, 1) if vwap_buy else None,
        "max_refill_item": max_refill_item,
        "status_code": true_regime["regime_type"],
        "badge": true_regime["badge"],
        "bias": true_regime["bias"],
        "color": true_regime["color"],
        "desc": true_regime["explanation"],
        "true_regime": true_regime,
        "active_icebergs": sorted(all_active, key=lambda x: x.get('refill_ratio', 0), reverse=True)
    }

def calibrate_sniper_setup(curr_price, market_regime, def_ceiling, def_floor, macro_l, macro_u, poc_wick, iceberg_analytics):
    """
    Injects Coinbase Iceberg Anchors into Entry, Stop Loss, and TP logic for sniper precision.
    """
    vwap_sell = iceberg_analytics.get("vwap_sell_anchor")
    vwap_buy = iceberg_analytics.get("vwap_buy_anchor")
    
    if market_regime == "BEARISH_DUMP_REGIME":
        # Anchor short to Coinbase Iceberg Sell Wall or Ceiling
        if vwap_sell and (vwap_sell >= curr_price - 25.0) and (vwap_sell <= curr_price + 350.0):
            entry_high = round(vwap_sell, 1)
            entry_low = round(vwap_sell - 60.0, 1)
            sl_price = round(entry_high + 50.0, 1) # Surgical tight stop above Coinbase wall!
            is_iceberg_anchored = True
            anchor_desc = f"Anchored to Coinbase Institutional Sell Wall (BN: ${vwap_sell:,.1f})"
        else:
            entry_high = round(def_ceiling, 1)
            entry_low = round(def_ceiling - 150.0, 1)
            sl_price = round(entry_high + 80.0, 1)
            is_iceberg_anchored = False
            anchor_desc = "Anchored to 6H Defense Ceiling & Wick"

        # TP1: If a Coinbase Iceberg Buy Cushion exists below price, target it!
        if vwap_buy and (vwap_buy <= curr_price - 30.0):
            tp1_p = round(vwap_buy, 1)
            tp1_label = f"🎯 TP1 (${tp1_p:,.1f} — Coinbase Buy Cushion De-Risk)"
        else:
            tp1_p = round(min(poc_wick, curr_price - 250.0), 1)
            tp1_label = f"🎯 TP1 (${tp1_p:,.1f} — POC Equilibrium)"
            
        tp2_p = round(macro_l, 1)
        tp3_p = round(macro_l - 600.0, 1)
        
        if curr_price >= sl_price:
            risk_pts = max(1.0, curr_price - sl_price)
            reward_pts = 0.0
            rr_ratio = 0.0
        else:
            risk_pts = max(1.0, sl_price - curr_price)
            raw_reward = curr_price - tp1_p
            if raw_reward <= 0:
                reward_pts = 0.0
                rr_ratio = 0.0
            else:
                reward_pts = raw_reward
                rr_ratio = reward_pts / risk_pts
        
        return {
            "is_iceberg_anchored": is_iceberg_anchored,
            "anchor_desc": anchor_desc,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "sl_price": sl_price,
            "tp1_p": tp1_p,
            "tp1_label": tp1_label,
            "tp2_p": tp2_p,
            "tp3_p": tp3_p,
            "risk_pts": round(risk_pts, 1),
            "reward_pts": round(reward_pts, 1),
            "rr_ratio": round(rr_ratio, 2)
        }
    else: # BULLISH
        if vwap_buy and (vwap_buy <= curr_price + 25.0) and (vwap_buy >= curr_price - 350.0):
            entry_low = round(vwap_buy, 1)
            entry_high = round(vwap_buy + 60.0, 1)
            sl_price = round(entry_low - 50.0, 1) # Tight stop below Coinbase cushion
            is_iceberg_anchored = True
            anchor_desc = f"Anchored to Coinbase Institutional Buy Cushion (BN: ${vwap_buy:,.1f})"
        else:
            entry_low = round(def_floor, 1)
            entry_high = round(def_floor + 150.0, 1)
            sl_price = round(entry_low - 80.0, 1)
            is_iceberg_anchored = False
            anchor_desc = "Anchored to 6H Defense Floor & Wick"

        if vwap_sell and (vwap_sell >= curr_price + 30.0):
            tp1_p = round(vwap_sell, 1)
            tp1_label = f"🎯 TP1 (${tp1_p:,.1f} — Coinbase Sell Resistance De-Risk)"
        else:
            tp1_p = round(max(poc_wick, curr_price + 250.0), 1)
            tp1_label = f"🎯 TP1 (${tp1_p:,.1f} — POC Equilibrium)"
            
        tp2_p = round(macro_u, 1)
        tp3_p = round(macro_u + 600.0, 1)
        
        if curr_price <= sl_price:
            risk_pts = max(1.0, sl_price - curr_price)
            reward_pts = 0.0
            rr_ratio = 0.0
        else:
            risk_pts = max(1.0, curr_price - sl_price)
            raw_reward = tp1_p - curr_price
            if raw_reward <= 0:
                reward_pts = 0.0
                rr_ratio = 0.0
            else:
                reward_pts = raw_reward
                rr_ratio = reward_pts / risk_pts
        
        return {
            "is_iceberg_anchored": is_iceberg_anchored,
            "anchor_desc": anchor_desc,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "sl_price": sl_price,
            "tp1_p": tp1_p,
            "tp1_label": tp1_label,
            "tp2_p": tp2_p,
            "tp3_p": tp3_p,
            "risk_pts": round(risk_pts, 1),
            "reward_pts": round(reward_pts, 1),
            "rr_ratio": round(rr_ratio, 2)
        }

def check_and_send_iceberg_alert(curr_price, cb_premium, sniper_setup, iceberg_analytics, force_send=False):
    """
    Sends a high-priority Sniper Iceberg Telegram Notice ONLY for genuine
    Coinbase Institutional Spot Icebergs (US Smart Money).
    Enforces a strict 45-minute global cooldown and 2-hour zone cooldown.
    """
    alert_state = load_json_file(ALERT_STATE_FILE, {"alerted_icebergs": {}, "last_alert_time": 0})
    alerted = alert_state.get("alerted_icebergs", {})
    now_ts = int(time.time())
    now_str = datetime.datetime.now().strftime("%I:%M %p | %d %b %Y")
    
    # 🛑 1. STRICT GLOBAL COOLDOWN (Minimum 45 minutes / 2700s between ANY alerts)
    last_global = alert_state.get("last_alert_time", 0)
    if not force_send and (now_ts - last_global < 2700):
        return False
    
    candidates = []
    # Filter ONLY Coinbase icebergs
    cb_icebergs = [x for x in iceberg_analytics.get("active_icebergs", []) if x.get("exchange") == "COINBASE"]
    
    for ice in cb_icebergs:
        refill = ice.get("refill_ratio", 0.0)
        vol = ice.get("executed_btc", 0.0)
        p = ice.get("price", curr_price)
        p_zone = round(p / 100.0) * 100 # Group into $100 price zone
        zone_key = f"COINBASE_{ice['side']}_ZONE_{p_zone:.0f}"
        
        # 🏛️ 2. STRICT COINBASE INSTITUTIONAL THRESHOLD (Real Spot Block: >= 3.0x refill AND >= 0.5 BTC, OR >= 1.5 BTC)
        is_inst_iceberg = (refill >= 3.0 and vol >= 0.5) or (vol >= 1.5)
        
        if is_inst_iceberg:
            last_zone_sent = alerted.get(zone_key, 0)
            if force_send or (now_ts - last_zone_sent > 7200): # 2-hour zone cooldown
                candidates.append((zone_key, ice))

    if not candidates and not force_send:
        return False

    # Pick the most prominent candidate
    if candidates:
        top_key, target_ice = max(candidates, key=lambda x: x[1].get('executed_btc', 0.0))
    elif force_send and cb_icebergs:
        target_ice = cb_icebergs[0]
        top_key = target_ice.get("id", "TEST_CB_ICEBERG")
    else:
        return False

    is_sell = "SELL" in target_ice.get("side", "")
    side_icon = "🔴" if is_sell else "🟢"
    action_type = "SHORT" if is_sell else "LONG"
    
    bn_equiv_p = target_ice.get('bn_equiv', curr_price)
    
    msg = (
        f"🏛️ {side_icon} <b>[COINBASE INSTITUTIONAL ICEBERG — US SPOT SMART MONEY]</b> {side_icon} 🏛️\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ <b>সময়:</b> {now_str} (Dhaka Time)\n"
        f"🪙 <b>অ্যাসেট:</b> #BTCUSDT | <b>বর্তমান ফিউচার্স প্রাইস:</b> <code>${curr_price:,.1f}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🇺🇸 <b>Coinbase Spot প্রাতিষ্ঠানিক অর্ডার ডিটেইলস:</b>\n"
        f"├─ 🏛️ <b>Coinbase Spot Level:</b> <code>${target_ice['price']:,.1f}</code>\n"
        f"├─ 🎯 <b>Binance Equivalent Level:</b> <code>${bn_equiv_p:,.1f}</code> (এক্সিকিউশন লেভেল)\n"
        f"├─ 🔄 <b>হিডেন রিফিল রেশিও:</b> <code>{target_ice['refill_ratio']}x REFILL</code> (ভিজিবল স্পটের {target_ice['refill_ratio']} গুণ!)\n"
        f"├─ 📦 <b>রিয়েল স্পট ভলিউম:</b> <code>{target_ice['executed_btc']} BTC</code> ({target_ice['fills_count']} বার রিফিল)\n"
        f"├─ 🇺🇸 <b>Coinbase Premium:</b> <code>${cb_premium:+.1f} USD</code>\n"
        f"└─ ⚖️ <b>CB পাওয়ার স্প্লিট:</b> <code>{iceberg_analytics['sell_power_pct']:.0f}% SELL vs {iceberg_analytics['buy_power_pct']:.0f}% BUY</code>\n\n"
        f"🎯 <b>স্নাইপার ট্রেড এক্সিকিউশন প্ল্যান ({action_type}):</b>\n"
        f"├─ 📥 <b>স্নাইপার এন্ট্রি জোন:</b> <code>${sniper_setup['entry_low']:,.1f} — ${sniper_setup['entry_high']:,.1f}</code>\n"
        f"├─ 🛑 <b>টাইট স্টপলস (SL):</b> <code>${sniper_setup['sl_price']:,.1f}</code> (Coinbase দেয়ালের মাত্র <code>{sniper_setup['risk_pts']} pts</code> উপরে!)\n"
        f"├─ 🎯 <b>টার্গেট ১ (TP1):</b> <code>${sniper_setup['tp1_p']:,.1f}</code> (৫০% প্রফিট বুক + এসএল এন্ট্রিতে লক)\n"
        f"├─ 🎯 <b>টার্গেট ২ (TP2):</b> <code>${sniper_setup['tp2_p']:,.1f}</code> (ম্যাক্রো উইক এক্সপেনশন)\n"
        f"└─ ⚖️ <b>Risk-to-Reward:</b> <code>1 : {sniper_setup['rr_ratio']}</code> (হাই উইন-রেট সেটআপ)\n\n"
        f"💡 <b>বস, অ্যাকশন সামারি:</b>\n"
        f"<i>{('Coinbase Spot-এ ইউএস প্রতিষ্ঠানগুলো এই প্রাইসে হিডেন সেল দেয়াল দিয়ে বাউন্স অ্যাবজর্ব করছে। টাইট স্টপলসে তিমিদের সাথে শর্ট নিন!' if is_sell else 'Coinbase Spot-এ প্রতিষ্ঠানগুলো ডিপে গোপনে আসল ক্যাশ স্পট একুমুলেট করছে। বাউন্সে লং সাপোর্ট ভ্যালিড!')}</i>"
    )

    if send_telegram_alert(msg):
        print(f"🚀 Successfully broadcasted Coinbase Iceberg alert for {top_key} to Telegram!")
        alerted[top_key] = now_ts
        alert_state["alerted_icebergs"] = alerted
        alert_state["last_alert_time"] = now_ts
        save_json_file(ALERT_STATE_FILE, alert_state)
        return True
    return False

if __name__ == '__main__':
    print("Testing Coinbase Exclusive Iceberg Order Engine...")
    ticker_data = robust_get_json('https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT', timeout=4)
    live_p = float(ticker_data["price"]) if ticker_data and "price" in ticker_data else 79880.0
    detected = scan_live_icebergs(live_p, -150.0)
    print(f"Coinbase Icebergs Detected: {len(detected)}")
    for d in detected:
        print(" ", d)
    buffered = update_rolling_buffer(detected, live_p)
    print(f"Buffered count: {len(buffered)}")
    analytics = compute_iceberg_analytics(buffered, live_p)
    print(f"Analytics: Buy Vol: {analytics['total_buy_vol_btc']} BTC ({analytics['buy_power_pct']}%) | Sell Vol: {analytics['total_sell_vol_btc']} BTC ({analytics['sell_power_pct']}%)")
    print(f"VWAP Sell: {analytics['vwap_sell_anchor']} | VWAP Buy: {analytics['vwap_buy_anchor']}")
    
    sniper = calibrate_sniper_setup(live_p, "BEARISH_DUMP_REGIME", live_p + 270.0, live_p - 230.0, live_p - 560.0, live_p + 1070.0, live_p + 20.0, analytics)
    print("Sniper Setup:", json.dumps(sniper, indent=2))
