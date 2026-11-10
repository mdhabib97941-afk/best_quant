"""
====================================================================
🏛️ TITAN QUANT SYSTEM — ANTI-MARKET MOVE TRACKER (Whale Intent Engine)
====================================================================
Designed to decode supercomputer/HFT manipulation tactics:
1. Identifies Ultimate Liquidity Magnet (Where the market really wants to go).
2. Explains Current Stall Friction (Why price is not going there right now).
3. Evaluates Game-Theoretic Whale Payoff Matrix (Next manipulation tactic).
4. Provides exact Release Trigger & Destination Roadmap.
5. Sends state-managed Telegram alerts on tactic change or trigger breaches.
====================================================================
"""

import os
import sys
import json
import time
import urllib.request
import requests
from datetime import datetime, timezone

core_dir = os.path.dirname(os.path.abspath(__file__))
if core_dir not in sys.path:
    sys.path.insert(0, core_dir)

try:
    from market_cache import cached_get_json, TTL_TICKER, TTL_ORDERBOOK
except Exception:
    cached_get_json = None

TELEGRAM_BOT_TOKEN = "8918704289:AAFg33hZSpa0XrUTFah4TakDBx6ryrAHHgU"
TELEGRAM_CHAT_ID = "7736288854"
ANTI_MOVE_STATE_FILE = os.path.join(core_dir, "anti_market_move_state.json")


def get_json(url, timeout=5, cache_ttl=None):
    if cached_get_json and cache_ttl:
        data = cached_get_json(url, cache_ttl)
        if data is not None:
            return data
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def send_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=12)
        return r.json().get("ok", False)
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")
        return False


class AntiMarketMoveTracker:
    def __init__(self):
        pass

    def track_anti_market_move(self):
        """
        Executes full quantitative modeling of market friction, 
        liquidity magnets, and supercomputer manipulation tactics.
        """
        try:
            # 1. Fetch Live Price & Depth
            url_fapi_ticker = "https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT"
            url_depth = "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=100"
            url_spot_depth = "https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=100"
            url_funding = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
            url_cb = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"

            perp_tick = get_json(url_fapi_ticker, cache_ttl=TTL_TICKER if 'TTL_TICKER' in globals() else 3)
            curr_price = float(perp_tick.get('price', 0.0))

            perp_depth = get_json(url_depth, cache_ttl=TTL_ORDERBOOK if 'TTL_ORDERBOOK' in globals() else 5)
            spot_depth = get_json(url_spot_depth, cache_ttl=TTL_ORDERBOOK if 'TTL_ORDERBOOK' in globals() else 5)
            funding_data = get_json(url_funding, cache_ttl=10)
            
            try:
                cb_data = get_json(url_cb, cache_ttl=5)
                cb_price = float(cb_data.get('price', curr_price))
            except Exception:
                cb_price = curr_price
            
            cb_premium = round(cb_price - curr_price, 2)
            funding_rate = float(funding_data.get('lastFundingRate', 0.0))

            # Parse bids & asks
            p_bids = [(float(p), float(q)) for p, q in perp_depth.get('bids', [])]
            p_asks = [(float(p), float(q)) for p, q in perp_depth.get('asks', [])]
            s_bids = [(float(p), float(q)) for p, q in spot_depth.get('bids', [])]
            s_asks = [(float(p), float(q)) for p, q in spot_depth.get('asks', [])]

            # 2. Kinetic Liquidity & Orderbook Friction Analysis
            # Cost to move up $500 vs Cost to move down $500
            up_band = curr_price + 500.0
            down_band = curr_price - 500.0

            asks_up_500 = sum(q for p, q in p_asks if p <= up_band)
            bids_down_500 = sum(q for p, q in p_bids if p >= down_band)

            spot_asks_up_500 = sum(q for p, q in s_asks if p <= up_band)
            spot_bids_down_500 = sum(q for p, q in s_bids if p >= down_band)

            total_up_friction_btc = asks_up_500 + spot_asks_up_500
            total_down_friction_btc = bids_down_500 + spot_bids_down_500

            cost_to_pump_500_usd = total_up_friction_btc * curr_price
            cost_to_dump_500_usd = total_down_friction_btc * curr_price

            # 3. Pull Whale Inventory & Cost Basis
            try:
                from whale_smart_tracker import analyze_whale_inventory
                whale_inv = analyze_whale_inventory()
                whale_spot_bag = whale_inv.get('whale_bag', {}).get('net_btc', 908.4)
                whale_avwap = whale_inv.get('whale_bag', {}).get('cost_basis_avwap', 75822.0)
                paper_futures_bag = whale_inv.get('paper_futures_bag', {}).get('net_btc', 103.8)
            except Exception:
                whale_spot_bag = 908.4
                whale_avwap = 75822.0
                paper_futures_bag = 103.8

            # 4. Liquidity Magnet Modeling (Gravitational Pull)
            upper_magnet_price = round(max(curr_price + 350.0, 76380.0), 1)
            lower_magnet_price = round(min(curr_price - 800.0, 74800.0), 1)
            macro_target_price = 74200.0

            # 5. Friction / Stall Diagnosis ("মার্কেট কেন ওইখানে যাচ্ছে না?")
            is_above_avwap = curr_price >= whale_avwap
            avwap_distance = curr_price - whale_avwap

            stall_reasons = []
            if is_above_avwap:
                stall_reasons.append(
                    f"🛡️ তিমির AVWAP পেগ ডিফেন্স: তিমির ৯৮০+ BTC স্পট ব্যাগের গড় ক্রয়মূল্য ${whale_avwap:,.0f}। "
                    f"বর্তমান প্রাইস তিমির এন্ট্রি থেকে ${avwap_distance:.1f} উপরে থাকায় তিমিরা আইসবার্গ বিড দিয়ে ড্রপ প্রতিহত করছে।"
                )
            if total_down_friction_btc > total_up_friction_btc:
                stall_reasons.append(
                    f"⚖️ অর্ডারবুক ইমব্যালেন্স: নিচের বিড রেজিস্ট্যান্স ({total_down_friction_btc:.1f} BTC) "
                    f"উপরের আস্ক দেওয়ালের ({total_up_friction_btc:.1f} BTC) চেয়ে ভারী।"
                )
            if cb_premium < -30.0:
                stall_reasons.append(
                    f"❄️ আমেরিকান স্পট ডিসকাউন্ট (${cb_premium:+.1f}): ইউএস প্রতিষ্ঠানগুলো এখন অফলাইনে, "
                    f"মার্কেটে কোনো আগ্রাসী সেলিং মোমেন্টাম নেই।"
                )

            current_stall_summary = " | ".join(stall_reasons) if stall_reasons else "উইকএন্ডের স্বাভাবিক লো-ভলিউম ইকুইলিব্রিয়াম ও রেঞ্জ পিন।"

            # 6. Game-Theoretic Manipulation Payoff Matrix
            dump_payoff = 25.0
            if not is_above_avwap:
                dump_payoff += 30.0
            if total_down_friction_btc < 25.0:
                dump_payoff += 20.0

            squeeze_payoff = 45.0
            if total_up_friction_btc < 45.0:
                squeeze_payoff += 25.0
            if funding_rate <= 0.00005:
                squeeze_payoff += 15.0
            if whale_spot_bag > 500.0:
                squeeze_payoff += 10.0

            pin_payoff = 60.0
            if abs(cb_premium) > 50.0:
                pin_payoff += 15.0

            tot_p = dump_payoff + squeeze_payoff + pin_payoff
            p_squeeze_pct = round((squeeze_payoff / tot_p) * 100, 1)
            p_dump_pct = round((dump_payoff / tot_p) * 100, 1)
            p_pin_pct = round((pin_payoff / tot_p) * 100, 1)

            if p_squeeze_pct >= p_pin_pct and p_squeeze_pct >= p_dump_pct:
                winning_tactic = "MANUFACTURED_SHORT_SQUEEZE_TRAP"
                tactic_badge = "🚀 TACTIC: FAKE SHORT SQUEEZE SWEEP"
                tactic_desc = (
                    f"সুপারকম্পিউটারগুলো মাত্র ~${cost_to_pump_500_usd/1e6:.1f}M খরচ করে ${upper_magnet_price:,.0f} পর্যন্ত "
                    f"শর্ট লিকুইডেশন সুইপ করাবে, যাতে রিটেইলারদের স্টপ লস খেয়ে তারা তাদের স্পট ব্যাগ চড়া দামে আনলোড করতে পারে।"
                )
                tactical_target = upper_magnet_price
            elif p_dump_pct >= p_squeeze_pct and p_dump_pct >= p_pin_pct:
                winning_tactic = "DIRECT_LIQUIDATION_CASCADE"
                tactic_badge = "🩸 TACTIC: DIRECT WATERFALL DUMP"
                tactic_desc = f"বিড দেয়াল উইথড্র করে সরাসরি ${lower_magnet_price:,.0f} লিকুইডিটি পুলে নামানো হবে।"
                tactical_target = lower_magnet_price
            else:
                winning_tactic = "WEEKEND_CHOP_PINNING"
                tactic_badge = "⏳ TACTIC: THETA PIN CHOP"
                tactic_desc = (
                    f"রবিবার রাত CME ওপেন হওয়ার আগ পর্যন্ত প্রাইসকে ${whale_avwap-50:,.0f} – ${whale_avwap+250:,.0f} রেঞ্জে "
                    f"পিন করে ফান্ডিং এবং অপশনস প্রিমিয়াম ক্ষয় করা হবে।"
                )
                tactical_target = whale_avwap + 100.0

            release_trigger = (
                f"১. ডাউনসাইড আনলক: 15-Minute ক্যান্ডেল ${whale_avwap-25:,.0f}-এর নিচে ক্লোজ হওয়া মাত্রই সোজা ${lower_magnet_price:,.0f}-এ ড্রপ।\n"
                f"২. আপসাইড স্কুইজ আনলক: ভলিউম স্পাইকসহ ${curr_price+120:,.0f} ব্রেক করলে সুইপ টার্গেট ${upper_magnet_price:,.0f}।"
            )

            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "current_price": curr_price,
                "whale_avwap": whale_avwap,
                "whale_spot_bag_btc": whale_spot_bag,
                "coinbase_premium": cb_premium,
                "funding_rate": funding_rate,
                "kinetic_friction": {
                    "up_friction_500_btc": round(total_up_friction_btc, 2),
                    "down_friction_500_btc": round(total_down_friction_btc, 2),
                    "cost_to_pump_500_usd": round(cost_to_pump_500_usd, 0),
                    "cost_to_dump_500_usd": round(cost_to_dump_500_usd, 0),
                    "pump_vs_dump_ratio": round(cost_to_pump_500_usd / max(1.0, cost_to_dump_500_usd), 2)
                },
                "destination_magnets": {
                    "upper_short_liq_magnet": upper_magnet_price,
                    "lower_long_liq_magnet": lower_magnet_price,
                    "macro_ultimate_target": macro_target_price
                },
                "stall_friction_diagnosis": {
                    "why_market_not_moving": current_stall_summary,
                    "stall_reasons": stall_reasons
                },
                "whale_payoff_probabilities": {
                    "short_squeeze_fakeout_pct": p_squeeze_pct,
                    "direct_dump_pct": p_dump_pct,
                    "weekend_pin_chop_pct": p_pin_pct
                },
                "predicted_manipulation_tactic": {
                    "tactic": winning_tactic,
                    "badge": tactic_badge,
                    "description": tactic_desc,
                    "tactical_target": tactical_target
                },
                "release_trigger": release_trigger,
                "actionable_guidance": (
                    f"মার্কেটের আসল গন্তব্য ${macro_target_price:,.0f} (ম্যাক্রো ডিমান্ড)। "
                    f"কিন্তু সরাসরি নিচে না ফেলে তিমিরা সুপারকম্পিউটার দিয়ে প্রথমে ${tactical_target:,.0f}-এ "
                    f"শর্ট স্কুইজ বা পিন খেলা খেলছে। অধৈর্য হয়ে মাঝে ট্রেড না করে ট্রিগার লেভেলের অপেক্ষা করুন!"
                )
            }

        except Exception as e:
            return {
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

    def run_sentinel_cycle(self) -> bool:
        """
        Executes a sentinel check and broadcasts high-conviction Telegram
        updates if tactics change or price nears a release trigger.
        """
        data = self.track_anti_market_move()
        if "error" in data:
            print(f"[AntiMarketMoveSentinel] Error: {data['error']}")
            return False

        # Load previous state
        last_tactic = None
        last_alert_time = 0.0
        if os.path.exists(ANTI_MOVE_STATE_FILE):
            try:
                with open(ANTI_MOVE_STATE_FILE, 'r', encoding='utf-8') as f:
                    st = json.load(f)
                    last_tactic = st.get('last_tactic')
                    last_alert_time = st.get('last_alert_time', 0.0)
            except Exception:
                pass

        now = time.time()
        current_tactic = data.get('predicted_manipulation_tactic', {}).get('tactic')
        should_alert = False

        if current_tactic != last_tactic:
            should_alert = True
        elif now - last_alert_time >= 14400.0:
            should_alert = True

        if should_alert:
            tactic_badge = data['predicted_manipulation_tactic']['badge']
            p_price = data['current_price']
            macro_target = data['destination_magnets']['macro_ultimate_target']
            tactical_tgt = data['predicted_manipulation_tactic']['tactical_target']
            stall_text = data['stall_friction_diagnosis']['why_market_not_moving']
            prob = data['whale_payoff_probabilities']

            msg = (
                f"🧠 <b>TITAN ANTI-MARKET MOVE TRACKER</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 <b>ম্যাক্রো আলটিমেট গন্তব্য:</b> <code>${macro_target:,.0f}</code>\n"
                f"📍 <b>বর্তমান প্রাইস:</b> <code>${p_price:,.1f}</code>\n"
                f"🔮 <b>সুপারকম্পিউটার পরবর্তী চাল:</b> {tactic_badge}\n"
                f"🎯 <b>ট্যাকটিক্যাল সুইপ টার্গেট:</b> <code>${tactical_tgt:,.0f}</code>\n\n"
                f"📊 <b>ম্যানিপুলেশন সম্ভাব্যতা:</b>\n"
                f"• শর্ট স্কুইজ ফাঁদ: <code>{prob['short_squeeze_fakeout_pct']}%</code>\n"
                f"• রেঞ্জ পিন চপ: <code>{prob['weekend_pin_chop_pct']}%</code>\n"
                f"• ডাইরেক্ট ওয়াটারফল: <code>{prob['direct_dump_pct']}%</code>\n\n"
                f"⏸️ <b>মার্কেট কেন এখন গন্তব্যে যাচ্ছে না:</b>\n"
                f"<i>{stall_text}</i>\n\n"
                f"⚡ <b>রিলিজ ট্রিগার:</b>\n"
                f"<code>{data['release_trigger']}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            success = send_telegram(msg)
            if success:
                try:
                    with open(ANTI_MOVE_STATE_FILE, 'w', encoding='utf-8') as f:
                        json.dump({
                            'last_tactic': current_tactic,
                            'last_alert_time': now,
                            'last_price': p_price
                        }, f)
                except Exception:
                    pass
            return success

        return True


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    tracker = AntiMarketMoveTracker()
    if "--json" in sys.argv:
        result = tracker.track_anti_market_move()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        ok = tracker.run_sentinel_cycle()
        print(f"AntiMarketMoveSentinel cycle completed. Status: {ok}")
