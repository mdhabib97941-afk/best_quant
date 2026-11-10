import os
import re
import datetime
import requests
import json
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

core_dir = os.path.dirname(os.path.abspath(__file__))
if core_dir not in sys.path:
    sys.path.insert(0, core_dir)

try:
    from market_cache import cached_get_json, TTL_KLINES, TTL_TICKER, TTL_OPTIONS
except Exception:
    cached_get_json = None
    TTL_KLINES = 15
    TTL_TICKER = 3
    TTL_OPTIONS = 60

MONTH_MAP = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
             'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}

def parse_deribit_expiry(exp_str):
    try:
        m = re.match(r'^(\d{1,2})([A-Z]{3})(\d{2})$', exp_str.upper())
        if not m:
            return None
        day = int(m.group(1))
        mon = MONTH_MAP.get(m.group(2))
        year = int(m.group(3)) + 2000
        if not mon:
            return None
        return datetime.datetime(year, mon, day, 8, 0, 0, tzinfo=datetime.timezone.utc)
    except Exception:
        return None

def compute_max_pain_from_strikes(strikes_oi):
    all_strikes = set(strikes_oi.keys())
    calls_by_strike = {s: v.get("call", 0.0) for s, v in strikes_oi.items()}
    puts_by_strike = {s: v.get("put", 0.0) for s, v in strikes_oi.items()}
    min_loss = float('inf')
    best_strike = None
    for candidate in sorted(all_strikes):
        loss = 0.0
        for s, oi in calls_by_strike.items():
            if candidate > s:
                loss += (candidate - s) * oi
        for s, oi in puts_by_strike.items():
            if candidate < s:
                loss += (s - candidate) * oi
        if loss < min_loss:
            min_loss = loss
            best_strike = candidate
    return float(best_strike) if best_strike is not None else None

def audit_market(symbol="BTCUSDT"):
    base = symbol.replace("USDT", "")
    
    # 1. Prices & Coinbase Premium
    bn_f_price = float(requests.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}", timeout=6).json()['price'])
    bn_s_price = float(requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=6).json()['price'])
    
    cb_symbol = f"{base}-USD"
    try:
        cb_price = float(requests.get(f"https://api.coinbase.com/v2/prices/{cb_symbol}/spot", timeout=6).json()['data']['amount'])
        cb_prem = cb_price - bn_s_price
    except Exception:
        cb_price = bn_s_price
        cb_prem = 0.0

    # 2. Spot vs Futures CVD (1h and 4h)
    f_kl = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit=4", timeout=6).json()
    s_kl = requests.get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=4", timeout=6).json()
    
    f_delta_4h = sum((float(c[9]) - (float(c[5]) - float(c[9]))) for c in f_kl)
    s_delta_4h = sum((float(c[9]) - (float(c[5]) - float(c[9]))) for c in s_kl)
    
    # 3. Open Interest & Top Long/Short
    oi_data = requests.get(f"https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period=1h&limit=5", timeout=6).json()
    cur_oi = float(oi_data[-1]['sumOpenInterest'])
    prev_oi = float(oi_data[0]['sumOpenInterest'])
    oi_diff = cur_oi - prev_oi
    
    ls_top = requests.get(f"https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol={symbol}&period=5m&limit=1", timeout=6).json()[0]
    ls_ratio = float(ls_top['longShortRatio'])
    top_long_pct = float(ls_top['longAccount']) * 100.0

    # 4. Deribit Options (Dynamic Expiry, True Max Pain & PCR)
    daily_pain = None
    pcr = None
    nearest_exp_str = None
    options_status = "ONLINE"
    try:
        opt_url = f"https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency={base}&kind=option"
        opt_data = cached_get_json(opt_url, ttl_seconds=TTL_OPTIONS, timeout=6) if cached_get_json else None
        if not opt_data:
            opt_res = requests.get(opt_url, timeout=6).json()
            opt_data = opt_res.get('result', [])
        else:
            opt_data = opt_data.get('result', []) if isinstance(opt_data, dict) else opt_data

        if not isinstance(opt_data, list) or len(opt_data) == 0:
            raise ValueError("Empty Deribit options data")

        # Find all unique active expiration strings
        expiries_map = {}
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        for item in opt_data:
            inst = item.get('instrument_name', '')
            parts = inst.split('-')
            if len(parts) == 4:
                exp_str = parts[1]
                if exp_str not in expiries_map:
                    dt = parse_deribit_expiry(exp_str)
                    if dt and dt >= now_utc - datetime.timedelta(hours=8):
                        expiries_map[exp_str] = dt

        if not expiries_map:
            raise ValueError("No active future option expiries found")

        # Sort expiries chronologically to pick the nearest active expiry
        sorted_expiries = sorted(expiries_map.items(), key=lambda x: x[1])
        nearest_exp_str, _ = sorted_expiries[0]

        # Aggregate Calls / Puts open interest by strike for the nearest expiry
        calls_by_strike = {}
        puts_by_strike = {}
        all_strikes = set()
        calls_oi = 0.0
        puts_oi = 0.0

        for item in opt_data:
            inst = item.get('instrument_name', '')
            parts = inst.split('-')
            if len(parts) == 4 and parts[1] == nearest_exp_str:
                strike = float(parts[2])
                call_put = parts[3]
                oi = float(item.get('open_interest', 0.0))
                all_strikes.add(strike)
                if call_put == 'C':
                    calls_by_strike[strike] = calls_by_strike.get(strike, 0.0) + oi
                    calls_oi += oi
                else:
                    puts_by_strike[strike] = puts_by_strike.get(strike, 0.0) + oi
                    puts_oi += oi

        if calls_oi > 0:
            pcr = round(puts_oi / calls_oi, 2)
        elif puts_oi > 0:
            pcr = 2.0
        else:
            pcr = 1.0

        # Calculate true Max Pain strike via dollar loss minimization
        min_loss = float('inf')
        best_strike = None
        for candidate in sorted(all_strikes):
            loss = 0.0
            for k, oi in calls_by_strike.items():
                if candidate > k:
                    loss += (candidate - k) * oi
            for k, oi in puts_by_strike.items():
                if candidate < k:
                    loss += (k - candidate) * oi
            if loss < min_loss:
                min_loss = loss
                best_strike = candidate

        daily_pain = float(best_strike) if best_strike is not None else None
    except Exception:
        options_status = "DATA_OFFLINE"
        daily_pain = None
        pcr = None
        nearest_exp_str = None

    # 5. Dealing Range (24h)
    dr_kl = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit=24", timeout=6).json()
    dr_h = max(float(c[2]) for c in dr_kl)
    dr_l = min(float(c[3]) for c in dr_kl)
    dr_eq = (dr_h + dr_l) / 2.0
    zone = "DISCOUNT (< 50% EQ)" if bn_f_price < dr_eq else "PREMIUM (> 50% EQ)"

    # Trap Audit Logic
    trap_status = "ORGANIC"
    if s_delta_4h < -100 and f_delta_4h > 150:
        trap_status = "🚨 BULL TRAP (Paper Longing while Spot Cash is Dumping!)"
    elif s_delta_4h > 100 and f_delta_4h < -150:
        trap_status = "🛡️ BEAR TRAP (Paper Shorting while Spot Cash is Accumulating!)"
    elif cb_prem < -40:
        trap_status = "🚨 US INSTITUTIONAL SPOT DUMP (Coinbase Heavy Discount)"
    elif s_delta_4h < 0 and f_delta_4h < 0:
        trap_status = "🔴 ACTIVE DOWNTREND (Spot & Futures Sync Dump)"
    elif s_delta_4h > 0 and f_delta_4h > 0:
        trap_status = "🟢 ACTIVE UPTREND (Spot & Futures Sync Pump)"

    return {
        'symbol': symbol,
        'fut_price': bn_f_price,
        'spot_price': bn_s_price,
        'cb_price': cb_price,
        'cb_premium': round(cb_prem, 2),
        'fut_delta_4h': round(f_delta_4h, 1),
        'spot_delta_4h': round(s_delta_4h, 1),
        'cur_oi': round(cur_oi, 1),
        'oi_diff_4h': round(oi_diff, 1),
        'top_ls_ratio': ls_ratio,
        'top_long_pct': round(top_long_pct, 1),
        'daily_pain': daily_pain,
        'pcr': pcr,
        'nearest_expiry': nearest_exp_str,
        'options_status': options_status,
        'range_high': dr_h,
        'range_low': dr_l,
        'range_eq': round(dr_eq, 1),
        'location': zone,
        'trap_status': trap_status
    }

if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    res = audit_market(sym)
    print(json.dumps(res, indent=2, ensure_ascii=False))
