import urllib.request
import json
import time
import datetime
import sys
import os

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SYMBOL = "BTCUSDT"
INTERVAL = "15m"
CHECK_EVERY_SEC = 10  # check every 10 seconds

TELEGRAM_BOT_TOKEN = "8918704289:AAFg33hZSpa0XrUTFah4TakDBx6ryrAHHgU"
TELEGRAM_CHAT_ID = "7736288854"

def send_telegram_alert(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }).encode('utf-8')
    req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        print(f"\n  [TELEGRAM ERR] {e}")
        return False

def fetch_klines(limit=3):
    url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval={INTERVAL}&limit={limit}"
    with urllib.request.urlopen(url, timeout=8) as r:
        return json.loads(r.read())

def fetch_backend():
    try:
        with urllib.request.urlopen("http://localhost:8585/api/market-pulse", timeout=5) as r:
            return json.loads(r.read())
    except:
        return {}

def parse_candle(c):
    ts     = int(c[0])
    o      = float(c[1])
    h      = float(c[2])
    l      = float(c[3])
    cl     = float(c[4])
    vol    = float(c[5])       # total volume BTC
    tbv    = float(c[9])       # taker buy base vol (BTC)
    tsv    = vol - tbv          # taker sell vol (BTC)
    delta  = tbv - tsv
    buy_r  = (tbv / vol * 100) if vol else 50

    body   = abs(cl - o)
    rng    = h - l if h != l else 1
    bpct   = body / rng * 100
    uwk    = h - max(o, cl)
    lwk    = min(o, cl) - l
    upct   = uwk / rng * 100
    lpct   = lwk / rng * 100
    dir_   = "BULL" if cl >= o else "BEAR"
    chg    = ((cl - o) / o) * 100

    return dict(
        ts=ts, o=o, h=h, l=l, cl=cl,
        vol=vol, tbv=tbv, tsv=tsv, delta=delta, buy_r=buy_r,
        body=body, rng=rng, bpct=bpct,
        uwk=uwk, lwk=lwk, upct=upct, lpct=lpct,
        dir=dir_, chg=chg
    )

def strength_label(buy_r, bpct, dir_, delta, vol, avg_vol):
    vr = vol / avg_vol if avg_vol else 1
    score = 0

    if dir_ == "BULL":
        if bpct >= 60 and buy_r >= 55: score += 3
        elif bpct >= 40 and buy_r >= 52: score += 2
        elif bpct >= 30: score += 1
        if buy_r < 45: score -= 2
        if vr >= 1.4: score += 1
        if delta > 0: score += 1
    else:
        if bpct >= 60 and buy_r <= 45: score += 3
        elif bpct >= 40 and buy_r <= 48: score += 2
        elif bpct >= 30: score += 1
        if buy_r > 55: score -= 2
        if vr >= 1.4: score += 1
        if delta < 0: score += 1

    if score >= 4:   return "STRONG " + dir_
    elif score >= 2: return "MOD    " + dir_
    elif score >= 1: return "WEAK   " + dir_
    elif score <= -1: return "FAKE   TRAP"
    else:            return "INDECISION"

def bar(pct, width=16):
    filled = int(float(pct) / 100 * width)
    filled = max(0, min(width, filled))
    return "[" + "#" * filled + "." * (width - filled) + f"] {pct:.1f}%"

def print_report(closed_candle, prev_candles, backend):
    c    = closed_candle
    now  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ctime = datetime.datetime.utcfromtimestamp(c["ts"] / 1000).strftime("%H:%M UTC")

    # avg vol from prev candles
    avg_vol = sum(p["vol"] for p in prev_candles) / max(len(prev_candles), 1)
    vr = c["vol"] / avg_vol if avg_vol else 1

    strength = strength_label(c["buy_r"], c["bpct"], c["dir"], c["delta"], c["vol"], avg_vol)

    # Backend data
    b    = backend.get("binance", {})
    cb   = backend.get("coinbase", {})
    ice  = backend.get("iceberg_radar", {})
    di   = backend.get("distribution_intelligence", {})
    rsb  = backend.get("whale_ledger", {}).get("real_spot_bag", {})

    curr_price   = float(b.get("lastPrice", c["cl"]))
    cb_premium   = float(cb.get("current_premium", 0))
    twap_dump    = cb.get("is_twap_dump", False)
    ice_bias     = ice.get("bias", "N/A")
    ice_buy_pct  = float(ice.get("buy_power_pct", 50))
    oi_1h        = float(b.get("oi1hDelta", 0))
    cb_spot_net  = float(rsb.get("coinbase_spot_delta", 0.0))
    rem_btc      = di.get("net_remaining_btc") or rsb.get("net_remaining_btc") or (f"{rsb.get('net_btc', 0.0):+,.1f} BTC" if 'net_btc' in rsb else "N/A")

    sep = "=" * 62

    print(f"\n{sep}")
    print(f"  CANDLE CLOSE REPORT  |  {ctime}  |  BDT {now}")
    print(sep)

    print(f"\n  Symbol     : BTC/USDT  [{INTERVAL}]")
    print(f"  Open       : ${c['o']:>10,.2f}")
    print(f"  High       : ${c['h']:>10,.2f}")
    print(f"  Low        : ${c['l']:>10,.2f}")
    print(f"  Close      : ${c['cl']:>10,.2f}   ({c['chg']:+.3f}%)")
    print(f"  Direction  : {c['dir']}  |  Body: {c['bpct']:.1f}%  |  UpperWick: {c['upct']:.1f}%  |  LowerWick: {c['lpct']:.1f}%")

    print(f"\n  ---- VOLUME BREAKDOWN ----")
    print(f"  Total Volume : {c['vol']:>9.3f} BTC  ({vr:.1f}x avg)")
    print(f"  BUY  Volume  : {c['tbv']:>9.3f} BTC  {bar(c['buy_r'])}")
    print(f"  SELL Volume  : {c['tsv']:>9.3f} BTC  {bar(100 - c['buy_r'])}")
    print(f"  Net Delta    : {c['delta']:>+9.3f} BTC  ({'BUYERS' if c['delta'] > 0 else 'SELLERS'} won)")

    if c["delta"] > 0:
        flow_story = f"{c['tbv']:.2f} BTC kena hoye - {c['tsv']:.2f} BTC becha hoye = +{c['delta']:.2f} BTC net BUY"
    else:
        flow_story = f"{c['tbv']:.2f} BTC kena hoye - {c['tsv']:.2f} BTC becha hoye = {c['delta']:.2f} BTC net SELL"
    print(f"  Flow Story   : {flow_story}")

    print(f"\n  ---- CANDLE STRENGTH ----")
    print(f"  Verdict      : {strength}")
    print(f"  Vol vs Avg   : {vr:.2f}x  ({'HIGH - institutional!' if vr > 1.5 else 'Normal' if vr > 0.7 else 'LOW - weak move'})")

    print(f"\n  ---- BACKEND SIGNALS ----")
    print(f"  BTC Price    : ${curr_price:,.2f}")
    print(f"  CB Premium   : ${cb_premium:+.2f}  ({'SELL pressure' if cb_premium < 0 else 'BUY pressure'})")
    print(f"  TWAP Dump    : {'YES - institution selling!' if twap_dump else 'No'}")
    print(f"  Iceberg Bias : {ice_bias}  |  Buy Power: {ice_buy_pct:.1f}%")
    print(f"  OI 1h Delta  : {oi_1h:+.1f} BTC  ({'Longs CLOSING' if oi_1h < 0 else 'Longs building'})")

    # Combined signal
    bull = 0; bear = 0
    if c["buy_r"] >= 55: bull += 2
    if c["buy_r"] <= 45: bear += 2
    if c["dir"] == "BULL" and c["bpct"] >= 60: bull += 1
    if c["dir"] == "BEAR" and c["bpct"] >= 60: bear += 1
    if c["delta"] > 30: bull += 1
    if c["delta"] < -30: bear += 1
    if twap_dump: bear += 2
    if cb_premium < -100: bear += 1
    if ice_bias == "LONG": bull += 1
    if ice_bias == "SHORT": bear += 1
    if oi_1h < -50: bear += 1
    if vr > 1.5 and c["dir"] == "BULL": bull += 1
    if vr > 1.5 and c["dir"] == "BEAR": bear += 1

    if bull > bear + 1:
        sig = "🟢 BUY SIGNAL - Bulls strong, follow up"
    elif bear > bull + 1:
        sig = "🔴 SELL SIGNAL - Bears strong, avoid long"
    else:
        sig = "⚪ WAIT - Mixed, no clear edge"

    print(f"\n  ---- COMBINED SIGNAL ----")
    print(f"  Bull Points  : {bull}")
    print(f"  Bear Points  : {bear}")
    print(f"  >> {sig}")
    print(sep)
    sys.stdout.flush()

    # -------------------------------------------------------------
    # 📱 DISPATCH DIRECT TELEGRAM NOTICE ON CANDLE CLOSE
    # -------------------------------------------------------------
    dir_emoji = "🟢 BULL CANDLE" if c["dir"] == "BULL" else "🔴 BEAR CANDLE"
    delta_emoji = "🟢" if c["delta"] > 0 else "🔴"
    
    tg_msg = (
        f"📊 <b>[BTC 15M CANDLE CLOSE REPORT]</b> {dir_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ <b>টাইম:</b> {now} (Dhaka) | {ctime}\n"
        f"🪙 <b>অ্যাসেট:</b> #BTCUSDT | <b>ক্লোজ:</b> <code>${c['cl']:,.2f}</code> ({c['chg']:+.2f}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📈 <b>ক্যান্ডেল বিবরণ:</b>\n"
        f"├─ <b>Open/High/Low:</b> <code>${c['o']:,.1f} / ${c['h']:,.1f} / ${c['l']:,.1f}</code>\n"
        f"├─ <b>Body / Wick:</b> <code>Body {c['bpct']:.0f}% | Wick {c['upct']:.0f}%/{c['lpct']:.0f}%</code>\n"
        f"└─ <b>শক্তি পরীক্ষা:</b> <b>{strength}</b> ({vr:.1f}x Volume)\n\n"
        f"📦 <b>ভলিউম ও ফ্লো বিশ্লেষণ:</b>\n"
        f"├─ 🟢 <b>Taker Buy:</b> <code>{c['tbv']:,.1f} BTC ({c['buy_r']:.1f}%)</code>\n"
        f"├─ 🔴 <b>Taker Sell:</b> <code>{c['tsv']:,.1f} BTC ({100 - c['buy_r']:.1f}%)</code>\n"
        f"└─ {delta_emoji} <b>Net Delta:</b> <code>{c['delta']:+,.2f} BTC</code>\n\n"
        f"🏛️ <b>প্রাতিষ্ঠানিক ব্যাকিং ও সিগন্যাল:</b>\n"
        f"├─ 🇺🇸 <b>Coinbase Prem:</b> <code>${cb_premium:+.1f} USD</code> ({'ডিসকাউন্টে ডাম্প' if cb_premium < 0 else 'প্রিমিয়ামে বাই'})\n"
        f"├─ 💼 <b>Coinbase Net Spot:</b> <code>{cb_spot_net:+,.1f} BTC</code>\n"
        f"├─ 🧊 <b>Iceberg Bias:</b> <code>{ice_bias} (Buy Power: {ice_buy_pct:.0f}%)</code>\n"
        f"├─ 💼 <b>Remaining BTC Bag:</b> <code>{rem_btc}</code>\n"
        f"└─ 🎯 <b>মার্কেট সিগন্যাল:</b> <b>{sig}</b>\n\n"
        f"💡 <b>বস, অ্যাকশন সামারি:</b>\n"
        f"<i>{flow_story}. {'রিটেল বায়ারদের ফাঁদে ফেলার পর তিমিরা হালকা হচ্ছে।' if (c['dir'] == 'BULL' and cb_premium < -50) else 'বর্তমান ফ্লোতে তিমিদের সক্রিয় অবস্থান পর্যবেক্ষণ করুন।'}</i>"
    )
    
    if send_telegram_alert(tg_msg):
        print(f"  [TELEGRAM] 15m Candle Close Notice sent to Telegram successfully!")
        sys.stdout.flush()

def get_candle_slot(ts_ms):
    return ts_ms // (15 * 60 * 1000)

def run_reporter_loop():
    print("=" * 62)
    print("  BTC 15m CANDLE CLOSE AUTO-REPORTER + TELEGRAM NOTICES [STARTED]")
    print(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} BDT")
    print("  Checking every 10 seconds...")
    print("=" * 62)
    sys.stdout.flush()

    last_reported_slot = None
    history = []

    while True:
        try:
            klines = fetch_klines(limit=5)
            if not klines or len(klines) < 2:
                time.sleep(CHECK_EVERY_SEC)
                continue

            closed_raw   = klines[-2]
            current_raw  = klines[-1]
            closed       = parse_candle(closed_raw)
            current      = parse_candle(current_raw)
            closed_slot  = get_candle_slot(closed["ts"])

            if len(history) == 0 or history[-1]["ts"] != closed["ts"]:
                history.append(closed)
                if len(history) > 12:
                    history.pop(0)

            if last_reported_slot != closed_slot:
                backend = fetch_backend()
                prev = history[:-1] if len(history) > 1 else history
                print_report(closed, prev, backend)
                last_reported_slot = closed_slot

            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            forming_chg = (current["cl"] - current["o"]) / current["o"] * 100
            next_close_ms = current["ts"] + 15 * 60 * 1000
            secs_left = max(0, (next_close_ms - int(time.time() * 1000)) // 1000)
            mins_left = secs_left // 60
            secs_rem  = secs_left % 60

            print(f"  [{now_str}] Forming: ${current['cl']:,.2f} "
                  f"| Buy:{current['tbv']:.2f} Sell:{current['tsv']:.2f} "
                  f"| Delta:{current['delta']:+.2f} "
                  f"| {mins_left:02d}m{secs_rem:02d}s to close...",
                  end="\r")
            sys.stdout.flush()

        except KeyboardInterrupt:
            print("\n\n[STOPPED] Auto-reporter stopped.")
            break
        except Exception as e:
            print(f"\n  [ERR] {e}")

        time.sleep(CHECK_EVERY_SEC)

if __name__ == "__main__":
    run_reporter_loop()

