import asyncio
import json
import time
import datetime
import sys
import collections
import statistics
import requests
import websockets
import threading

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
try:
    from coinbase_institutional_radar import analyze_coinbase_flow
except Exception:
    analyze_coinbase_flow = None

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Telegram Bot Credentials for Instant Direct Notices
TELEGRAM_BOT_TOKEN = "8918704289:AAFg33hZSpa0XrUTFah4TakDBx6ryrAHHgU"
TELEGRAM_CHAT_ID = "7736288854"

def _send_tg_sync(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass

def send_telegram_alert(text):
    """Non-blocking Telegram alert dispatcher to avoid dropping WebSocket ticks."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(asyncio.to_thread(_send_tg_sync, text))
    except RuntimeError:
        import threading
        threading.Thread(target=_send_tg_sync, args=(text,), daemon=True).start()

def send_telegram(text):
    send_telegram_alert(text)

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(CORE_DIR, "dragonfly_state.json")

def derive_dynamic_winrate(cips_score=50.0, synaptic_delta_z=0.0, vw_obi_20=0.0):
    dyn_conf = min(95.0, max(50.0, 50.0 + (cips_score - 50.0) * 0.4 + abs(synaptic_delta_z) * 5.0 + abs(vw_obi_20) * 20.0))
    win_rate = round(dyn_conf, 1)
    return win_rate, win_rate

def save_state(custom_dict=None):
    state_to_save = custom_dict if custom_dict is not None else {}
    tmp_path = f"{STATE_FILE}.tmp.{os.getpid()}_{time.time()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state_to_save, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, STATE_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

def refresh_macro_cortex(symbol="BTCUSDT"):
    brain = DragonflyTitanBrain(symbol)
    brain.refresh_macro_cortex()
    return {
        "dealing_range": {"high": brain.macro_h, "low": brain.macro_l},
        "equilibrium": brain.macro_eq,
        "institutional_demand": brain.demand_zone,
        "institutional_supply": brain.supply_zone,
        "macro_location": brain.macro_location,
        "macro_allowed": brain.macro_allowed
    }

class DragonflyTitanBrain:
    """
    =============================================================================
    🧬 DRAGONFLY TITAN BRAIN — APEX PREDATOR HIERARCHICAL QUANT ENGINE
    =============================================================================
    Integrated Architecture:
      Layer 3 (Macro Cortex):     HTF 4H/1D 4-Pillars & Coinbase Inflow Predictive Score (CIPS)
      Layer 2 (Tactical Memory):  MTF 15m/1H HPZ Order Blocks & Liquidity Sweeps (BSL / SSL)
      Layer 1 (Reflex Synapses):
        - Sub-Millisecond Tick Acceleration (TSDN Deque)
        - Real-Time Liquidation Cascade Sentinel (@forceOrder Interceptor)
        - Multi-Level Depth-20 VW-OBI & Spoof Wall Radar
        - Neuromorphic Adaptive Volatility Synapses (Dynamic Z-Scores)
      Notice Sentinel:
        - Direct Telegram & Terminal Alerts for Preparation & Execution Phases
    =============================================================================
    """
    def __init__(self, symbol="BTCUSDT"):
        self.symbol = symbol.lower()
        self.sym_upper = symbol.upper()
        # High-Speed Multi-Stream WebSocket (bookTicker + aggTrade + forceOrder)
        self.stream_url = (
            f"wss://fstream.binance.com/stream?streams="
            f"{self.symbol}@bookTicker/"
            f"{self.symbol}@aggTrade/"
            f"{self.symbol}@forceOrder"
        )
        
        # --- LAYER 1A: NEUROMORPHIC MICRO TICK BUFFER ---
        self.trade_window = collections.deque() # (timestamp, price, delta_usd)
        self.best_bid = 0.0
        self.best_ask = 0.0
        self.best_bid_qty = 0.0
        self.best_ask_qty = 0.0
        self.last_price = 0.0
        self.current_obi = 0.0 # Top-of-book L1 OBI
        self.total_ticks = 0
        self.last_signal_time = 0
        self.signal_cooldown = 3.5

        # --- LAYER 1B: MULTI-LEVEL DEPTH-20 & SPOOF WALL RADAR ---
        self.vw_obi_20 = 0.0 # Volume-Weighted OBI across top 20 levels
        self.bids_depth_20 = []
        self.asks_depth_20 = []
        self.active_walls = {} # price -> (side, size)
        self.spoof_alert_time = 0

        # --- LAYER 1C: REAL-TIME LIQUIDATION CASCADE SENTINEL ---
        self.liquidation_window = collections.deque() # (timestamp, side, qty, price, usd_val)
        self.long_liq_usd_15s = 0.0
        self.short_liq_usd_15s = 0.0
        self.last_liq_cascade_time = 0

        # --- LAYER 1D: NEUROMORPHIC ADAPTIVE SYNAPSES (Z-SCORES) ---
        self.synaptic_delta_vel_history = collections.deque(maxlen=150)
        self.synaptic_obi_history = collections.deque(maxlen=150)
        self.z_score_delta = 0.0
        self.z_score_obi = 0.0
        self.market_volatility_regime = "NORMAL" # CALM_MICRO, NORMAL, HIGH_STORM
        
        # --- LAYER 2: TACTICAL LIQUIDITY & OB MEMORY (15m/1H) ---
        self.demand_zone = (0.0, 0.0) # Dynamically calibrated from rolling dealing range
        self.supply_zone = (0.0, 0.0) # Dynamically calibrated from rolling dealing range
        self.recent_ssl = 0.0         # Dynamic rolling swept low
        self.recent_bsl = 0.0         # Dynamic rolling swept high
        self.tactical_state = "SCANNING"
        
        # --- LAYER 3: MACRO INSTITUTIONAL CORTEX (4H/1D & CIPS) ---
        self.cb_premium = -999.0
        self.cips_score = 50.0
        self.cb_obi_1pct = 0.0
        self.cb_velocity_5m = 0.0
        self.cb_tape_delta = 0.0
        self.cb_buy_ratio = 50.0
        self.cb_whale_count = 0
        self.cb_inflow_signal = "NEUTRAL"
        self.macro_eq = 0.0
        self.macro_h = 0.0
        self.macro_l = 0.0
        self.macro_location = "UNKNOWN"
        self.macro_allowed = "NEUTRAL"
        self.deribit_max_pain = 0.0
        self.last_macro_update = 0
        self.bn_spot_delta_4h = 0.0
        self.state_file_path = STATE_FILE

        # --- NOTICE SENTINEL TIMERS (Telegram & Terminal Alerts) ---
        self.last_prep_notice_time = 0
        self.last_exec_notice_time = 0
        self.last_bull_trap_notice_time = 0
        
        print("=" * 90, flush=True)
        print(f"🏛️ DRAGONFLY TITAN BRAIN [APEX PREDATOR + NOTICE SENTINEL] INITIALIZED ON [{self.sym_upper}]", flush=True)
        print("🦅 Layer 3 (Macro):    4H/1D 4-Pillars & Coinbase Inflow Predictive Score (CIPS)", flush=True)
        print("🎯 Layer 2 (Tactical): 15m/1H HPZ Order Blocks & Liquidity Sweeps (BSL / SSL)", flush=True)
        print("⚡ Layer 1 (Reflex):   Sub-ms Tick TSDN, Depth-20 VW-OBI, Liquidation Sentinel & Z-Synapses", flush=True)
        print("📢 Notice Sentinel:   Instant Telegram Alerts on Dual-Institutional Signals", flush=True)
        print("=" * 90, flush=True)

    def refresh_macro_cortex(self):
        """
        Layer 3: Macro Institutional Cortex
        Refreshes 4-Pillar macro truth & Coinbase Inflow Predictive Score (CIPS).
        Checks Dual-Institutional Alignment and Fires High-Priority Telegram Notices!
        """
        try:
            # 1. Binance Spot vs Coinbase Spot
            base_coin = self.sym_upper.replace("USDT", "")
            s_res = requests.get(f'https://api.binance.com/api/v3/ticker/price?symbol={self.sym_upper}', timeout=4).json()
            cb_res = requests.get(f'https://api.coinbase.com/v2/prices/{base_coin}-USD/spot', timeout=4).json()
            s_price = float(s_res['price']) if isinstance(s_res, dict) and 'price' in s_res else self.last_price
            cb_price = float(cb_res['data']['amount']) if isinstance(cb_res, dict) and 'data' in cb_res and 'amount' in cb_res['data'] else s_price
            self.cb_premium = round(cb_price - s_price, 2)
            
            # 2. 48H Dealing Range (50% Equilibrium) & Institutional Liquidity Zones
            url_k = f'https://fapi.binance.com/fapi/v1/klines?symbol={self.sym_upper}&interval=4h&limit=12'
            rk = requests.get(url_k, timeout=4).json()
            if isinstance(rk, list) and len(rk) > 0 and isinstance(rk[0], list):
                high_48h = max(float(x[2]) for x in rk)
                low_48h = min(float(x[3]) for x in rk)
                self.macro_h = high_48h
                self.macro_l = low_48h
                self.macro_eq = (high_48h + low_48h) / 2.0
                range_span = max(1.0, high_48h - low_48h)
                self.demand_zone = (low_48h, round(low_48h + range_span * 0.236, 1))
                self.supply_zone = (round(high_48h - range_span * 0.236, 1), high_48h)
                self.recent_ssl = low_48h
                self.recent_bsl = high_48h
            elif self.macro_eq == 0.0 and s_price > 0:
                self.macro_eq = s_price
                self.demand_zone = (round(s_price * 0.98, 1), round(s_price * 0.99, 1))
                self.supply_zone = (round(s_price * 1.01, 1), round(s_price * 1.02, 1))

            # 3. Binance 4h spot kline to track Real Cash Flow
            try:
                bn_spot_k = requests.get(f'https://api.binance.com/api/v3/klines?symbol={self.sym_upper}&interval=4h&limit=1', timeout=4).json()
                if isinstance(bn_spot_k, list) and len(bn_spot_k) > 0 and isinstance(bn_spot_k[0], list):
                    v = float(bn_spot_k[0][5])
                    tbv = float(bn_spot_k[0][9])
                    self.bn_spot_delta_4h = round(tbv - (v - tbv), 1)
            except Exception:
                pass

            # 4. Coinbase Institutional Inflow Radar (CIPS Engine)
            if analyze_coinbase_flow:
                try:
                    cips_data = analyze_coinbase_flow()
                    self.cips_score = cips_data.get("cips_score", 50.0)
                    self.cb_obi_1pct = cips_data.get("cb_obi_1pct", 0.0)
                    self.cb_velocity_5m = cips_data.get("premium_velocity_5m", 0.0)
                    self.cb_tape_delta = cips_data.get("last_100_delta_btc", 0.0)
                    self.cb_buy_ratio = cips_data.get("buy_ratio_pct", 50.0)
                    self.cb_whale_count = cips_data.get("whale_trades_count", 0)
                    self.cb_inflow_signal = cips_data.get("signal", "NEUTRAL")
                except Exception:
                    pass
            
            # 5. Macro Permission Evaluation
            if s_price < self.macro_eq:
                self.macro_location = f"DISCOUNT (< 50% EQ: ${self.macro_eq:,.0f})"
                if self.cips_score >= 75.0 or (self.cb_premium >= -35.0 and self.cb_velocity_5m >= 0):
                    self.macro_allowed = "BULLISH_ALLOWED"
                elif self.cips_score >= 60.0:
                    self.macro_allowed = "EARLY_ACCUMULATION_WATCH"
                else:
                    self.macro_allowed = "CAUTION_HEAVY_INSTITUTIONAL_SELL"
            else:
                self.macro_location = f"PREMIUM (> 50% EQ: ${self.macro_eq:,.0f})"
                self.macro_allowed = "BEARISH_ALLOWED"
                
            self.last_macro_update = time.time()
            now_ts = time.time()
            now_str = datetime.datetime.now().strftime("%I:%M %p | %d %b %Y")
            
            # -------------------------------------------------------------
            # DUAL-INSTITUTIONAL NOTICE DISPATCHER (Telegram & Terminal)
            # -------------------------------------------------------------
            # Case 1: PREPARATION NOTICE (Binance Spot accumulating in Discount, but Coinbase still lagging)
            if self.bn_spot_delta_4h >= 180.0 and self.macro_location.startswith("DISCOUNT") and self.cips_score < 60.0:
                if now_ts - self.last_prep_notice_time > 1800: # 30 min cooldown
                    self.last_prep_notice_time = now_ts
                    msg_prep = (
                        f"⚠️ <b>[DRAGONFLY NOTICE: BINANCE SPOT ACCUMULATION — PREPARATION PHASE]</b> ⚠️\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"⏱️ <b>সময়:</b> {now_str} (Dhaka Time)\n"
                        f"🪙 <b>অ্যাসেট:</b> #{self.sym_upper} | <b>প্রাইস:</b> <code>${s_price:,.1f}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"📊 <b>ফুটপ্রিন্ট পর্যবেক্ষণ:</b>\n"
                        f"├─ 🩸 <b>Binance Spot Cash:</b> <code>+{self.bn_spot_delta_4h:,.1f} BTC (ফ্লোরে ব্যাগ লোড হচ্ছে)</code>\n"
                        f"├─ 🇺🇸 <b>Coinbase Inflow:</b> <code>CIPS {self.cips_score:.1f}% (Prem: ${self.cb_premium:+.1f} USD)</code>\n"
                        f"└─ 🎯 <b>স্ট্যাটাস:</b> <code>PREPARATION_ONLY (কয়েনবেসের কনফার্মেশন এখনও বাকি)</code>\n\n"
                        f"💡 <b>বস, অ্যাকশন গাইড:</b>\n"
                        f"<i>বাইন্যান্স স্পটে বড় ফ্লোর তৈরি হচ্ছে। কোনো অবস্থাতেই লেট শর্ট নিবেন না! কয়েনবেসের আমেরিকান বায়ারদের সিগন্যাল (CIPS ≥ ৬৫%) আসা পর্যন্ত অপেক্ষা করুন।</i>"
                    )
                    send_telegram_alert(msg_prep)
                    print(f"\n📢 [DRAGONFLY NOTICE DISPATCHED] Binance Spot Accumulation Preparation Notice sent to Telegram!\n", flush=True)

            # Case 2: EXECUTION NOTICE (Both Binance and Coinbase Inflow in Full Agreement!)
            if self.bn_spot_delta_4h >= 150.0 and (self.cips_score >= 65.0 or self.cb_velocity_5m >= 15.0) and self.macro_location.startswith("DISCOUNT"):
                if now_ts - self.last_exec_notice_time > 1800:
                    self.last_exec_notice_time = now_ts
                    msg_exec = (
                        f"🚨 <b>[DRAGONFLY TITAN: DUAL-INSTITUTIONAL IGNITION — EXECUTION UNLOCKED!]</b> 🚨\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"⏱️ <b>সময়:</b> {now_str} (Dhaka Time)\n"
                        f"🪙 <b>অ্যাসেট:</b> #{self.sym_upper} | <b>প্রাইস:</b> <code>${s_price:,.1f}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"🏛️ <b>দ্বৈত প্রাতিষ্ঠানিক একুমুলেশন নিশ্চিত:</b>\n"
                        f"├─ 🟢 <b>Binance Spot Cash:</b> <code>+{self.bn_spot_delta_4h:,.1f} BTC (সাপোর্ট প্রস্তুত)</code>\n"
                        f"├─ 🇺🇸 <b>Coinbase Ignition:</b> <code>CIPS {self.cips_score:.1f}% | Vel: {self.cb_velocity_5m:+.1f} USD</code>\n"
                        f"├─ 🧲 <b>Order Book Depth:</b> <code>L1 OBI: {self.current_obi:+.2f} | D20: {self.vw_obi_20:+.2f}</code>\n"
                        f"└─ 🎯 <b>ট্রেড সিগন্যাল:</b> <code>BEAR TRAP REVERSAL LONG [HIGH CONVICTION]</code>\n\n"
                        f"💡 <b>বস, অ্যাকশন গাইড:</b>\n"
                        f"<i>বাইন্যান্স ও কয়েনবেস দুই জায়গাতেই আমেরিকান ও গ্লোবাল বায়াররা একযোগে বাইং শুরু করেছে। বিয়ার ট্র্যাপ কনফার্মড! আপনি নিরাপদভাবে রিভার্সাল লং সেটআপে ঢুকতে পারেন!</i>"
                    )
                    send_telegram_alert(msg_exec)
                    print(f"\n🚀 [DRAGONFLY EXECUTION NOTICE DISPATCHED] Dual-Institutional Long Execution Notice sent to Telegram!\n", flush=True)

            t_now_str = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{t_now_str}] 🧠 [MACRO CORTEX] CB Prem: ${self.cb_premium:+.2f} (Vel: {self.cb_velocity_5m:+.1f}) | CIPS: {self.cips_score:.1f}% | BN Spot: {self.bn_spot_delta_4h:+.1f} BTC | Gate: {self.macro_allowed}", flush=True)
            self.save_state()
        except Exception:
            pass

    def save_state(self):
        """Writes atomic JSON state to core/dragonfly_state.json adhering to PROJECT.md interface contract."""
        try:
            cur_p = self.last_price if self.last_price > 0 else (self.best_bid if self.best_bid > 0 else self.macro_eq)
            conf_val = round(min(95.0, max(50.0, 50.0 + (self.cips_score - 50.0) * 0.4 + abs(self.z_score_delta) * 5.0 + abs(self.vw_obi_20) * 20.0)), 1)
            state_data = {
                "symbol": self.sym_upper,
                "timestamp": time.time(),
                "last_price": round(cur_p, 2),
                "price": round(cur_p, 2),
                "macro_eq": round(self.macro_eq, 2),
                "gate": self.macro_allowed,
                "demand_zone": [round(self.demand_zone[0], 2), round(self.demand_zone[1], 2)],
                "supply_zone": [round(self.supply_zone[0], 2), round(self.supply_zone[1], 2)],
                "vw_obi_20": round(self.vw_obi_20, 4),
                "l1_obi": round(self.current_obi, 4),
                "ticks": self.total_ticks,
                "active_walls": {
                    "bids": [{"price": p, "qty": q} for p, (side, q) in self.active_walls.items() if side == 'BID'],
                    "asks": [{"price": p, "qty": q} for p, (side, q) in self.active_walls.items() if side == 'ASK']
                },
                "cips_score": round(self.cips_score, 1),
                "confidence_pct": conf_val,
                "status": "ONLINE"
            }
            tmp_path = f"{self.state_file_path}.tmp.{os.getpid()}_{threading.get_ident()}_{time.time()}"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)
            for attempt in range(3):
                try:
                    os.replace(tmp_path, self.state_file_path)
                    break
                except (OSError, PermissionError):
                    if attempt < 2:
                        time.sleep(0.05)
                    else:
                        raise
        except Exception:
            pass

    def _prune_windows(self, now):
        """Prunes tick buffer older than 4.5 seconds to cover depth worker interval"""
        while self.trade_window and now - self.trade_window[0][0] > 4.5:
            self.trade_window.popleft()

    def _prune_liquidation_window(self, now):
        """Prunes liquidation buffer older than 15.0 seconds"""
        while self.liquidation_window and now - self.liquidation_window[0][0] > 15.0:
            self.liquidation_window.popleft()

    async def depth_radar_worker(self):
        """Feature 2: Multi-Level Order Book Depth-20 & Spoof Wall Radar (Async 2.5s loop)"""
        url = f"https://fapi.binance.com/fapi/v1/depth?symbol={self.sym_upper}&limit=20"
        while True:
            try:
                r = await asyncio.to_thread(lambda: requests.get(url, timeout=3).json())
                if isinstance(r, dict):
                    bids = [(float(b[0]), float(b[1])) for b in r.get('bids', [])]
                    asks = [(float(a[0]), float(a[1])) for a in r.get('asks', [])]
                    
                    if bids and asks:
                        self.bids_depth_20 = bids
                        self.asks_depth_20 = asks

                        # Volume-Weighted Depth (Top 5: wt 1.0, 6-10: wt 0.8, 11-20: wt 0.5)
                        def calc_weighted(levels):
                            return sum(q * (1.0 if idx < 5 else (0.8 if idx < 10 else 0.5)) for idx, (p, q) in enumerate(levels))

                        w_bids = calc_weighted(bids)
                        w_asks = calc_weighted(asks)
                        tot_w = w_bids + w_asks
                        self.vw_obi_20 = (w_bids - w_asks) / tot_w if tot_w > 0 else 0.0

                        # Dynamic Spoof Wall Threshold:
                        # At least 30 BTC for BTC, or equivalent $1,000,000 USD for any asset
                        mid_p = (bids[0][0] + asks[0][0]) / 2.0 if bids and asks else self.last_price
                        min_wall_qty = 30.0 if self.sym_upper.startswith("BTC") else (max(1.0, 1_000_000.0 / mid_p) if mid_p > 0 else 30.0)

                        now = time.time()
                        current_walls = {}
                        for p, q in bids:
                            if q >= min_wall_qty: current_walls[p] = ('BID', q)
                        for p, q in asks:
                            if q >= min_wall_qty: current_walls[p] = ('ASK', q)

                        # Dynamic price radius calibrated to asset price (0.05% of price or at least $2.50)
                        price_radius = max(2.5, mid_p * 0.0005)

                        for p, (side, q) in list(self.active_walls.items()):
                            if p not in current_walls:
                                recent_vol = sum(abs(x[2]) for x in self.trade_window if abs(x[1] - p) <= price_radius)
                                if recent_vol < (q * p * 0.35):
                                    if now - self.spoof_alert_time > 4.0:
                                        self.spoof_alert_time = now
                                        now_str = datetime.datetime.now().strftime("%H:%M:%S")
                                        print(f"[{now_str}] 👻 [SPOOF WALL PULLED] Whales canceled {side} Wall of {q:.1f} at ${p:,.1f}!", flush=True)

                        self.active_walls = current_walls
            except Exception:
                pass
            await asyncio.sleep(2.5)

    def process_book_ticker(self, data):
        """Layer 1A: Micro-Order Book Imbalance (L1 OBI)"""
        t_recv = time.time()
        self.best_bid = float(data['b'])
        self.best_ask = float(data['a'])
        self.best_bid_qty = float(data['B'])
        self.best_ask_qty = float(data['A'])
        
        if self.last_price == 0.0:
            self.last_price = (self.best_bid + self.best_ask) / 2.0
            
        tot_qty = self.best_bid_qty + self.best_ask_qty
        self.current_obi = (self.best_bid_qty - self.best_ask_qty) / tot_qty if tot_qty > 0 else 0.0
        self.total_ticks += 1
        self._prune_windows(t_recv)

    def process_force_order(self, data):
        """Feature 1: Real-Time Liquidation Cascade Interceptor (@forceOrder)"""
        try:
            o = data.get('o', {})
            side = o.get('S', '') # SELL = Long liquidated, BUY = Short liquidated
            q = float(o.get('q', 0.0))
            p = float(o.get('p', 0.0))
            usd_val = p * q
            now = time.time()

            self.liquidation_window.append((now, side, q, p, usd_val))
            self._prune_liquidation_window(now)

            self.long_liq_usd_15s = sum(x[4] for x in self.liquidation_window if x[1] == 'SELL')
            self.short_liq_usd_15s = sum(x[4] for x in self.liquidation_window if x[1] == 'BUY')

            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            if usd_val >= 35_000:
                trader_type = "LONG LIQUIDATED (Forced Sell)" if side == "SELL" else "SHORT LIQUIDATED (Forced Buy)"
                print(f"[{now_str}] 💥 [LIQUIDATION EVENT] {q:.2f} BTC (${usd_val/1e3:,.1f}k) | {trader_type} @ ${p:,.1f}", flush=True)

            # Bear Trap Trigger: Massive Long Liquidations absorbed by Bid Walls
            if self.long_liq_usd_15s >= 75_000 and (self.current_obi >= 0.35 or self.vw_obi_20 >= 0.25) and (now - self.last_liq_cascade_time > 5.0):
                self.last_liq_cascade_time = now
                print("\n" + "🧲" * 45, flush=True)
                print(f"[{now_str}] 🚨 BEAR TRAP DETECTED: CAPITULATION ABSORPTION ACTIVE!", flush=True)
                print(f"Longs Flushed (15s):     ${self.long_liq_usd_15s/1e3:,.1f}k USD", flush=True)
                print(f"Order Book Absorption:   L1 OBI: {self.current_obi:+.2f} | Depth-20: {self.vw_obi_20:+.2f}", flush=True)
                print(f"Institutional Action:    🎯 BEAR TRAP REVERSAL LONG TRIGGER READY!", flush=True)
                print("🧲" * 45 + "\n", flush=True)

            # Bull Trap Trigger: Massive Short Squeeze rejected into Ask Walls
            elif self.short_liq_usd_15s >= 75_000 and (self.current_obi <= -0.35 or self.vw_obi_20 <= -0.25) and (now - self.last_liq_cascade_time > 5.0):
                self.last_liq_cascade_time = now
                print("\n" + "🧲" * 45, flush=True)
                print(f"[{now_str}] 🚨 BULL TRAP DETECTED: SHORT SQUEEZE EXHAUSTION ACTIVE!", flush=True)
                print(f"Shorts Flushed (15s):    ${self.short_liq_usd_15s/1e3:,.1f}k USD", flush=True)
                print(f"Order Book Resistance:   L1 OBI: {self.current_obi:+.2f} | Depth-20: {self.vw_obi_20:+.2f}", flush=True)
                print(f"Institutional Action:    🎯 BULL TRAP FADE SHORT TRIGGER READY!", flush=True)
                print("🧲" * 45 + "\n", flush=True)
        except Exception:
            pass

    def update_synaptic_weights(self, delta_velocity, obi):
        """Feature 4: Neuromorphic Adaptive Volatility Synapses (Dynamic Z-Scores)"""
        self.synaptic_delta_vel_history.append(delta_velocity)
        self.synaptic_obi_history.append(obi)

        if len(self.synaptic_delta_vel_history) < 15:
            self.z_score_delta = 0.0
            self.z_score_obi = 0.0
            return

        try:
            mean_dv = statistics.mean(self.synaptic_delta_vel_history)
            stdev_dv = statistics.stdev(self.synaptic_delta_vel_history)
            mean_obi = statistics.mean(self.synaptic_obi_history)
            stdev_obi = statistics.stdev(self.synaptic_obi_history)

            self.z_score_delta = (delta_velocity - mean_dv) / (stdev_dv + 1.0)
            self.z_score_obi = (obi - mean_obi) / (stdev_obi + 0.01)

            if stdev_dv > 65_000:
                self.market_volatility_regime = "HIGH_STORM"
            elif stdev_dv < 15_000:
                self.market_volatility_regime = "CALM_MICRO"
            else:
                self.market_volatility_regime = "NORMAL"
        except Exception:
            pass

    def process_trade(self, data):
        """Layer 1: TSDN Neurons (Delta Acceleration & Interception)"""
        t_recv = time.time()
        p = float(data['p'])
        q = float(data['q'])
        is_buyer_maker = bool(data['m'])
        
        delta_usd = (p * q) if not is_buyer_maker else -(p * q)
        self.last_price = p
        
        self.trade_window.append((t_recv, p, delta_usd))
        self.total_ticks += 1
        self._prune_windows(t_recv)
        
        self.evaluate_hierarchical_interception(t_recv, event_time_ms=data['T'])

    def evaluate_hierarchical_interception(self, now, event_time_ms):
        """
        MASTER COHERENCE GATE — APEX PREDICTIVE ENGINE
        Unifies Micro Reflex (L1), Depth-20 (L1B), Liquidation Sentinel (L1C),
        Tactical Zones (L2) & Macro CIPS (L3) into Bidirectional Sniper Locks!
        """
        if now - self.last_signal_time < self.signal_cooldown:
            return
            
        if len(self.trade_window) < 3:
            return
            
        sub_trades = [x for x in self.trade_window if now - x[0] <= 1.0]
        if len(sub_trades) < 2:
            return
            
        delta_sum = sum(x[2] for x in sub_trades)
        dt = now - sub_trades[0][0]
        if dt <= 0.03:
            return
            
        p_start = sub_trades[0][1]
        p_end = sub_trades[-1][1]
        delta_velocity = delta_sum / dt
        
        exchange_event_sec = event_time_ms / 1000.0
        reaction_latency_ms = max(0.4, (now - exchange_event_sec) * 1000.0)

        # Update Neuromorphic Synaptic Weights & Dynamic Z-Scores
        self.update_synaptic_weights(delta_velocity, self.current_obi)
        
        # Adaptive Thresholds (Regime-aware)
        z_thresh = 2.8 if self.market_volatility_regime == "HIGH_STORM" else (2.0 if self.market_volatility_regime == "CALM_MICRO" else 2.3)

        adaptive_bull = (self.z_score_delta >= z_thresh and (self.current_obi >= 0.40 or self.vw_obi_20 >= 0.30)) or (self.current_obi >= 0.65 and delta_velocity > 25_000)
        adaptive_bear = (self.z_score_delta <= -z_thresh and (self.current_obi <= -0.40 or self.vw_obi_20 <= -0.30)) or (self.current_obi <= -0.65 and delta_velocity < -25_000)
        
        if not (adaptive_bull or adaptive_bear):
            return

        ts_str = datetime.datetime.fromtimestamp(now).strftime("%H:%M:%S.%f")[:-3]

        # =========================================================================
        # CASE A: BULLISH EVENT (Check for Bear Trap Reversal vs Bull Trap vs Trend)
        # =========================================================================
        if adaptive_bull:
            self.last_signal_time = now
            in_demand = (self.demand_zone[1] > 0 and p_end <= self.demand_zone[1])
            is_bear_trap_reversal = (in_demand or self.long_liq_usd_15s >= 50_000 or self.cips_score >= 65.0)

            if is_bear_trap_reversal and (self.macro_allowed in ["BULLISH_ALLOWED", "EARLY_ACCUMULATION_WATCH", "NEUTRAL"]):
                dyn_conf = min(95.0, max(50.0, 50.0 + (self.cips_score - 50.0) * 0.4 + abs(self.z_score_delta) * 5.0 + abs(self.vw_obi_20) * 20.0))
                print("\n" + "🔥" * 45, flush=True)
                print(f"[{ts_str}] 🎯 TITAN SNIPER: [BEAR TRAP REVERSAL LONG LOCK]!", flush=True)
                print(f"Price:                ${p_end:,.2f} (Floor Liquidity Absorbed)", flush=True)
                print(f"Synaptic Z-Score:     Z_Delta: {self.z_score_delta:+.2f}σ | Z_OBI: {self.z_score_obi:+.2f}σ ({self.market_volatility_regime})", flush=True)
                print(f"Order Book Reflex:    L1 OBI: {self.current_obi:+.2f} | Depth-20 VW-OBI: {self.vw_obi_20:+.2f} (THICK BIDS)", flush=True)
                print(f"Liquidations (15s):   Longs Flushed: ${self.long_liq_usd_15s/1e3:,.1f}k | Latency: {reaction_latency_ms:.1f}ms", flush=True)
                print(f"Layer 3 Macro:        {self.macro_location} | CB Prem: ${self.cb_premium:+.2f} | CIPS: {self.cips_score:.1f}%", flush=True)
                print(f"Dynamic Confidence:   {dyn_conf:.1f}% (Capitulation Sweep Absorption via CIPS & Synapses)", flush=True)
                print("🔥" * 45 + "\n", flush=True)
            elif not is_bear_trap_reversal and self.macro_allowed == "CAUTION_HEAVY_INSTITUTIONAL_SELL":
                # Contradiction: Micro pump rejected into overhead ask walls!
                print(f"[{ts_str}] 🚨 [BULL TRAP ALERT] Micro-pump rejected into Ask Walls! (Opportunity: FADE SHORT @ ${p_end:,.1f})", flush=True)
            else:
                print(f"[{ts_str}] 🚀 TITAN MOMENTUM: [TREND EXPANSION LONG] @ ${p_end:,.1f} (Z: {self.z_score_delta:+.2f}σ)", flush=True)

        # =========================================================================
        # CASE B: BEARISH EVENT (Check for Bull Trap Fade vs Trend Continuation)
        # =========================================================================
        elif adaptive_bear:
            self.last_signal_time = now
            in_supply = (self.supply_zone[0] > 0 and p_end >= self.supply_zone[0])
            is_bull_trap_fade = (in_supply or self.short_liq_usd_15s >= 50_000 or self.macro_allowed == "CAUTION_HEAVY_INSTITUTIONAL_SELL")

            if is_bull_trap_fade:
                dyn_conf = min(95.0, max(50.0, 50.0 + (self.cips_score - 50.0) * 0.4 + abs(self.z_score_delta) * 5.0 + abs(self.vw_obi_20) * 20.0))
                print("\n" + "🔻" * 45, flush=True)
                print(f"[{ts_str}] 🎯 TITAN SNIPER: [BULL TRAP FADE SHORT LOCK]!", flush=True)
                print(f"Price:                ${p_end:,.2f} (Retail Longs Trapped in Overhead Supply)", flush=True)
                print(f"Synaptic Z-Score:     Z_Delta: {self.z_score_delta:+.2f}σ | Z_OBI: {self.z_score_obi:+.2f}σ ({self.market_volatility_regime})", flush=True)
                print(f"Order Book Reflex:    L1 OBI: {self.current_obi:+.2f} | Depth-20 VW-OBI: {self.vw_obi_20:+.2f} (HEAVY ASKS)", flush=True)
                print(f"Liquidations (15s):   Shorts Flushed: ${self.short_liq_usd_15s/1e3:,.1f}k | Latency: {reaction_latency_ms:.1f}ms", flush=True)
                print(f"Layer 3 Macro:        {self.macro_location} | CB Prem: ${self.cb_premium:+.2f} | CIPS: {self.cips_score:.1f}%", flush=True)
                print(f"Dynamic Confidence:   {dyn_conf:.1f}% (Bull Trap Overhead Rejection via CIPS & Synapses)", flush=True)
                print("🔻" * 45 + "\n", flush=True)

                # Send Bull Trap Fade Short Notice to Telegram (30 min cooldown)
                if now - self.last_bull_trap_notice_time > 1800:
                    self.last_bull_trap_notice_time = now
                    now_str_tg = datetime.datetime.now().strftime("%I:%M %p | %d %b %Y")
                    msg_bt = (
                        f"🚨 <b>[DRAGONFLY TITAN: BULL TRAP FADE SHORT TRIGGER!]</b> 🚨\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"⏱️ <b>সময়:</b> {now_str_tg} (Dhaka Time)\n"
                        f"🪙 <b>অ্যাসেট:</b> #{self.sym_upper} | <b>প্রাইস:</b> <code>${p_end:,.1f}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"🔻 <b>বুল ট্র্যাপ রিজেকশন সিগনেচার:</b>\n"
                        f"├─ 🛑 <b>সাপ্লাই রিজেকশন:</b> <code>ওভারহেড আস্ক ওয়ালে ধাক্কা খেয়েছে</code>\n"
                        f"├─ 🇺🇸 <b>Coinbase Flow:</b> <code>Prem: ${self.cb_premium:+.1f} (আমেরিকান কোনো স্পট সাপোর্ট নেই)</code>\n"
                        f"├─ 📉 <b>Order Book:</b> <code>L1 OBI: {self.current_obi:+.2f} | D20: {self.vw_obi_20:+.2f}</code>\n"
                        f"└─ 🎯 <b>ট্রেড সিগন্যাল:</b> <code>BULL TRAP FADE SHORT [HIGH CONVICTION]</code>\n\n"
                        f"💡 <b>বস, অ্যাকশন গাইড:</b>\n"
                        f"<i>রিটেইলাররা ফেক বাউন্সে লং ফেঁসে গেছে। তিমিরা উপরের ওয়ালে সেল অফলোড করছে। শর্ট অপরচুনিটি প্রস্তুত!</i>"
                    )
                    send_telegram_alert(msg_bt)
                    print(f"\n📢 [DRAGONFLY NOTICE DISPATCHED] Bull Trap Fade Short Notice sent to Telegram!\n", flush=True)
            else:
                print(f"[{ts_str}] 🛡️ [TITAN SHIELD] Micro Short Suppressed into Deep Floor!", flush=True)

    async def run(self, max_runtime_seconds=None):
        start_time = time.time()
        heartbeat_timer = time.time()
        macro_timer = time.time()
        
        # Initialize Layer 3 Macro
        await asyncio.to_thread(self.refresh_macro_cortex)

        # Start Depth-20 Radar Worker Task
        depth_task = asyncio.create_task(self.depth_radar_worker())
        
        try:
            while True:
                if max_runtime_seconds and time.time() - start_time >= max_runtime_seconds:
                    print(f"\n✅ Titan Brain Apex Session Completed! Processed {self.total_ticks} Micro-Ticks.", flush=True)
                    return
                try:
                    print(f"Connecting to Binance Apex Multi-Feed for [{self.sym_upper}]...", flush=True)
                    rem_sec = (max_runtime_seconds - (time.time() - start_time)) if max_runtime_seconds else None
                    conn_timeout = min(15, max(1, int(rem_sec))) if rem_sec is not None else 15
                    async with websockets.connect(self.stream_url, ping_interval=20, ping_timeout=15, open_timeout=conn_timeout) as ws:
                        print("✅ TITAN BRAIN APEX PREDATOR ARMED! Tracking Multi-Depth, Liquidations & Synaptic Flow...\n", flush=True)
                        
                        while True:
                            if max_runtime_seconds and time.time() - start_time >= max_runtime_seconds:
                                print(f"\n✅ Titan Brain Apex Session Completed! Processed {self.total_ticks} Micro-Ticks.", flush=True)
                                return
                            try:
                                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            except asyncio.TimeoutError:
                                if max_runtime_seconds and time.time() - start_time >= max_runtime_seconds:
                                    print(f"\n✅ Titan Brain Apex Session Completed! Processed {self.total_ticks} Micro-Ticks.", flush=True)
                                    return
                                continue

                            data = json.loads(msg)
                            stream_name = data.get('stream', '')
                            payload = data.get('data', {})
                            
                            if 'bookTicker' in stream_name:
                                self.process_book_ticker(payload)
                            elif 'aggTrade' in stream_name:
                                self.process_trade(payload)
                            elif 'forceOrder' in stream_name:
                                self.process_force_order(payload)
                                
                            # Async periodic refresh of Macro Cortex (every 60s)
                            if time.time() - macro_timer >= 60.0:
                                macro_timer = time.time()
                                await asyncio.to_thread(self.refresh_macro_cortex)
                                
                            # Terminal Radar Telemetry every 5 seconds
                            if time.time() - heartbeat_timer >= 5.0:
                                heartbeat_timer = time.time()
                                self.save_state()
                                bar_len = min(12, int(abs(self.current_obi) * 12))
                                obi_bar = "█" * bar_len
                                side_label = "BUY " if self.current_obi >= 0 else "SELL"
                                now_str = datetime.datetime.now().strftime("%H:%M:%S")
                                mid_p = (self.best_bid + self.best_ask) / 2.0 if self.best_bid > 0 else self.last_price
                                print(
                                    f"[{now_str}] 🦅 [TITAN RADAR] Mid: ${mid_p:,.1f} | "
                                    f"Gate: {self.macro_allowed[:12]} | "
                                    f"L1: {self.current_obi:+.2f} [{side_label} {obi_bar}] | "
                                    f"D20: {self.vw_obi_20:+.2f} | "
                                    f"Z: {self.z_score_delta:+.1f}σ | "
                                    f"Liq: ${self.long_liq_usd_15s/1e3:.0f}k/${self.short_liq_usd_15s/1e3:.0f}k | "
                                    f"Ticks: {self.total_ticks}",
                                    flush=True
                                )
                                
                            if max_runtime_seconds and time.time() - start_time >= max_runtime_seconds:
                                print(f"\n✅ Titan Brain Apex Session Completed! Processed {self.total_ticks} Micro-Ticks.", flush=True)
                                return
                except Exception as e:
                    print(f"WebSocket reconnecting ({e})...", flush=True)
                    if max_runtime_seconds and time.time() - start_time >= max_runtime_seconds:
                        print(f"\n✅ Titan Brain Apex Session Completed! Processed {self.total_ticks} Micro-Ticks.", flush=True)
                        return
                    sleep_time = min(2.0, max(0.1, max_runtime_seconds - (time.time() - start_time))) if max_runtime_seconds else 2.0
                    await asyncio.sleep(sleep_time)
                    if max_runtime_seconds and time.time() - start_time >= max_runtime_seconds:
                        print(f"\n✅ Titan Brain Apex Session Completed! Processed {self.total_ticks} Micro-Ticks.", flush=True)
                        return
        finally:
            depth_task.cancel()
            try:
                await depth_task
            except (asyncio.CancelledError, Exception):
                pass
            self.save_state()

if __name__ == "__main__":
    runtime = None
    if len(sys.argv) > 1:
        try:
            val = int(sys.argv[1])
            runtime = val if val > 0 else None
        except:
            runtime = None
            
    brain = DragonflyTitanBrain("BTCUSDT")
    asyncio.run(brain.run(max_runtime_seconds=runtime))
