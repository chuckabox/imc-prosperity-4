"""
trader_final.py — Data-driven rewrite after full historical analysis
=====================================================================
 
KEY FINDINGS from prices_round_2_day_{-1,0,1}.csv analysis:
 
PEPPER (INTARIAN_PEPPER_ROOT):
  • Drift is EXACTLY +0.001 per timestamp tick (confirmed across all 3 days)
  • Day -1: +998 over 100k ticks. Day 0: +1001.5. Day 1: +999.5
  • This drift is ULTRA STABLE — no reversals. It always goes up.
  • Typical spread: ~14 ticks. Tick noise (|Δmid|): mean=3.1
  • Early slope (first 200 ticks): already +18-21 units, clearly positive
  • Monte Carlo simulation: stop-loss NEVER fires on real data (0% of ticks
    have 20-tick slope < -20 threshold). The stop in v8/v3 is spurious.
  • The t=3000 crash in the 6893-run was the PASSIVE ORDER getting lifted
    while building position — the stop cost ~82 PnL.
  • Theoretical max PEPPER PnL: ~79,960/day
  • Current algo gets ~6,444/day on PEPPER — massive gap due to:
    (a) delayed entry (warmup=1200 ticks wasted), (b) false stops
  
  FIX: 
  • Remove the stop-loss entirely for PEPPER. On real data it NEVER helps.
  • Enter immediately (no warmup needed — drift is visually obvious by t=100)
  • Use a simple "always buy" strategy: the price is ALWAYS going up
  • Monte Carlo shows fast_track at ANY value (50-500) gives same result
    because the drift signal is present from tick 1.
 
OSMIUM (ASH_COATED_OSMIUM):
  • True mean = 10,000. Mean deviation from 10k: only 3-4 ticks (stdev=3)
  • Price NEVER goes more than ±20 from 10,000 in any day
  • ATR (EMA30 of |Δmid|): 2.25 ticks — very calm
  • 465 trades/day, ~5.1 units each = 2372 total market volume
  • Our efficiency: 38% of theoretical MM PnL (~449 actual vs ~1186 max)
  • The variance in OSMIUM PnL (+600 to +100) is inventory drift risk
  • OSMIUM ended at position -80 (maxed short) in the last run
 
  FIX:
  • OBI bias (proven): keep it
  • Tighter anchor: 10,000 is the exact true mean, use weight 0.85
  • Since ATR ≈ 2.25, half-spread of 1 tick is correct — keep it
  • Improve MM efficiency: quote more aggressively (FRONT=45, SECOND=35)
  • Add inventory-mean-reversion pressure: when pos > 20, lean quotes
  • The flat-soft-drift thing is noise — OSMIUM has max deviation of 20 
    ever, so the watchdog should only trip at streak of 50 (not 120+)
 
MONTE CARLO / SIMULATION INSIGHT:
  The "Monte Carlo" approach for this problem is: simulate what WOULD have 
  happened under different parameter choices using the real price data.
  The simulation shows:
  • Any entry within first 500 ticks gives ~same PEPPER PnL as first 50
  • The drift is so strong (+1000/day) that what matters is BEING IN, not
    WHEN you enter in the first few hundred ticks
  • What actually hurts: (1) the stop-loss (dumps position early for no reason)
    and (2) the warmup period (leaves 80+ units undeployed for 1200 ticks)
 
MAF bid: 4,000 (same — 8k/day gross is realistic)
"""
 
import json
from typing import Dict, List
 
from datamodel import Order, OrderDepth, TradingState, Symbol
 
 
PEPPER = "INTARIAN_PEPPER_ROOT"
OSMIUM = "ASH_COATED_OSMIUM"
 
 
def _median(vals: list) -> float:
    n = len(vals)
    if n == 0:
        return 0.0
    s = sorted(vals)
    mid = n // 2
    return float(s[mid]) if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0
 
 
class Trader:
    LIMIT = 80
 
    # ── PEPPER constants ──────────────────────────────────────────────────────
    # Data confirms drift = +0.001/tick on every single day, no exceptions.
    # The regime detector just needs to confirm "is it still going up".
    # We use a very short warmup — by tick 50, drift is already unmistakable.
 
    PEP_WARMUP_TICKS      = 50     # was 200/1200 — data shows drift visible by t=50
    PEP_FAST_TRACK_TICKS  = 50     # same — enter ASAP
 
    # Slope thresholds (drift/tick * 100). Data shows drift ≈ 0.10, use 0.02
    # as threshold so we never fail to detect it, but still filter noise
    PEP_SLOPE_STRONG_FAST = 0.02   # was 0.05 — data shows 0.10 typical
    PEP_SLOPE_STRONG      = 0.02
    PEP_SLOPE_MODERATE    = 0.005
    PEP_SLOPE_WEAK        = -0.005
 
    PEP_CAP_STRONG    = 80
    PEP_CAP_MODERATE  = 65
    PEP_CAP_WEAK      = 40
    PEP_CAP_NEGATIVE  =  0
    PEP_CAP_TENTATIVE = 60   # was 25 — we KNOW drift is up, start with big cap
 
    # Sizing: hit hard immediately
    PEP_TAKE_STRONG  = 40    # was 32 — grab more aggressively at open
    PEP_TAKE_NORMAL  = 25    # was 18
    PEP_PASSIVE_MAX  = 80    # was 65 — passive at full cap
 
    # Stop-loss: DATA SHOWS this NEVER fires on real data (0% of ticks
    # have slope < -20 over any 20-tick window). It only causes false exits.
    # We keep it as a safety net but with extreme thresholds so it only 
    # fires in true catastrophe (e.g. price reversal of 100+ ticks).
    PEP_STOP_BREACH_COUNT = 5     # was 3 — need 5 consecutive breaches
    PEP_STOP_STRONG    = -60      # was -20 — only fire on massive reversal
    PEP_STOP_MODERATE  = -40      # was -10
    PEP_STOP_WEAK      = -20      # was -7
    PEP_RESUME_STRONG  =  10      # was 5
    PEP_RESUME_MODERATE=  10
    PEP_RESUME_WEAK    =   7
 
    PEP_SPREAD_PASSIVE_SCALE = 0.9   # was 0.75 — don't cut passive much
    PEP_TAKE_CROSS_EDGE      = 3.0   # was 2.0 — accept wider takes
 
    # ── OSMIUM constants ──────────────────────────────────────────────────────
    # Data confirms: true mean = exactly 10,000. Max deviation ever = ±20.
    # ATR ≈ 2.25 ticks. Spread ≈ 16 ticks wide. Our quotes at ±1 from fair.
 
    OSM_ANCHOR         = 10_000
    OSM_ANCHOR_WEIGHT  = 0.85       # was 0.70 — data confirms 10k is THE anchor
    OSM_FAIR_EMA_ALPHA = 2.0 / 51.0 # was 2/101 — faster EMA for tighter MM
    OSM_ATR_ALPHA      = 2.0 / 21.0 # was 2/31 — faster ATR
    OSM_ATR_MIN        = 1.0
    OSM_ATR_MAX        = 4.0        # was 5 — data max ATR ≈ 3
 
    # Soft drift: price rarely goes above 8 from anchor, so set lower threshold
    OSM_SOFT_DRIFT_THRESHOLD  = 6.0    # was 8 — more responsive
    OSM_SOFT_DRIFT_MIN_WEIGHT = 0.55   # was 0.45
 
    # Watchdog: data shows max deviation = 20, so only trip at 15+ for 50 ticks
    # (was 120 ticks — far too slow to respond)
    OSM_DRIFT_THRESHOLD    = 15
    OSM_DRIFT_STREAK_TRIP  = 50         # was 120 — much faster response
    OSM_DRIFT_FLATTEN_TARGET = 30       # was 35
 
    OSM_TOXICITY       = 30            # was 35 — slightly more sensitive
    OSM_EDGE_POS_STEP  = 25            # was 30 — tighter edge scaling
    OSM_TAKE_EDGE_MAX  = 2             # was 3 — don't over-take
 
    OSM_SKEW_SOFT      = 12            # was 15 — earlier inventory skew
    OSM_SKEW_HARD      = 30            # was 35
    OSM_FLATTEN_HARD   = 55            # was 58
    OSM_FLATTEN_TARGET = 45            # was 50
 
    # More aggressive quoting — data shows we're only at 38% efficiency
    OSM_QUOTE_FRONT    = 45            # was 38
    OSM_QUOTE_SECOND   = 35            # was 28
 
    def __init__(self):
        self.history: Dict = {}
 
    def bid(self) -> int:
        return 4_000
 
    # ─────────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────────
    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        else:
            self.history = {}
 
        # PEPPER
        self.history.setdefault("pp", [])
        self.history.setdefault("pp_base", [])
        self.history.setdefault("pp_t0", None)
        self.history.setdefault("pp_cap", None)
        self.history.setdefault("pp_breach", 0)
        self.history.setdefault("pp_stopped", False)
        self.history.setdefault("pp_prev_spread", None)
        # OSMIUM
        self.history.setdefault("osm_last_mid", None)
        self.history.setdefault("osm_vwap_ema", None)
        self.history.setdefault("osm_atr_ema", 1.0)
        self.history.setdefault("osm_drift_streak", 0)
 
    def _save(self) -> str:
        return json.dumps(self.history, separators=(",", ":"))
 
    # ─────────────────────────────────────────────────────────────────────────
    # Book helpers
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _best_bid(od: OrderDepth):
        if not od.buy_orders:
            return None, 0
        bp = max(od.buy_orders.keys())
        return bp, od.buy_orders[bp]
 
    @staticmethod
    def _best_ask(od: OrderDepth):
        if not od.sell_orders:
            return None, 0
        ap = min(od.sell_orders.keys())
        return ap, -od.sell_orders[ap]
 
    @staticmethod
    def _second_bid(od: OrderDepth, best):
        ks = sorted([p for p in od.buy_orders.keys() if p != best], reverse=True)
        if not ks:
            return None, 0
        return ks[0], od.buy_orders[ks[0]]
 
    @staticmethod
    def _second_ask(od: OrderDepth, best):
        ks = sorted([p for p in od.sell_orders.keys() if p != best])
        if not ks:
            return None, 0
        return ks[0], -od.sell_orders[ks[0]]
 
    @staticmethod
    def _ema(prev, x, alpha):
        if prev is None:
            return float(x)
        return prev + alpha * (x - prev)
 
    # ─────────────────────────────────────────────────────────────────────────
    # PEPPER — aggressive trend-follower, no warmup, no false stops
    # ─────────────────────────────────────────────────────────────────────────
    def _pepper(self, state: TradingState, od: OrderDepth) -> List[Order]:
        orders: List[Order] = []
        pos = state.position.get(PEPPER, 0)
 
        bb, bbv = self._best_bid(od)
        ba, bav = self._best_ask(od)
        if bb is None or ba is None:
            return orders
 
        mid    = (bb + ba) / 2.0
        spread = ba - bb
        ts     = state.timestamp
 
        # History — keep 120 mids, use for slope and regime
        hist = self.history["pp"]
        hist.append(mid)
        if len(hist) > 120:
            hist = hist[-120:]
        self.history["pp"] = hist
 
        # Accumulate base samples (first 15 mids only)
        base_samples = self.history["pp_base"]
        if len(base_samples) < 15:
            base_samples.append(mid)
            self.history["pp_base"] = base_samples
 
        if self.history["pp_t0"] is None:
            self.history["pp_t0"] = ts
        start_ts = self.history["pp_t0"]
        elapsed  = ts - start_ts
 
        # Spread momentum
        prev_spread = self.history["pp_prev_spread"]
        if prev_spread is None:
            prev_spread = spread
        spread_widening = spread > prev_spread
        self.history["pp_prev_spread"] = spread
 
        # ── Regime detection ──────────────────────────────────────────────────
        # Uses median-drift: fast, reliable. Low thresholds since drift ≈ 0.10.
        cap = self.history["pp_cap"]
 
        if len(base_samples) >= 15 and len(hist) >= 15:
            base_mean    = _median(base_samples)
            current_mean = _median(hist[-15:])
            dt    = max(1, elapsed)
            drift = (current_mean - base_mean) / dt * 100.0
 
            fast_track = elapsed >= self.PEP_FAST_TRACK_TICKS
            warmed_up  = elapsed >= self.PEP_WARMUP_TICKS
 
            if fast_track and drift >= self.PEP_SLOPE_STRONG_FAST:
                new_cap = self.PEP_CAP_STRONG
            elif warmed_up:
                if drift > self.PEP_SLOPE_STRONG:
                    new_cap = self.PEP_CAP_STRONG
                elif drift > self.PEP_SLOPE_MODERATE:
                    new_cap = self.PEP_CAP_MODERATE
                elif drift > self.PEP_SLOPE_WEAK:
                    new_cap = self.PEP_CAP_WEAK
                else:
                    new_cap = self.PEP_CAP_NEGATIVE
            else:
                new_cap = cap
 
            if cap is None:
                cap = new_cap if new_cap is not None else self.PEP_CAP_TENTATIVE
            elif new_cap is not None and new_cap > cap:
                cap = new_cap
            elif warmed_up and new_cap is not None and new_cap < cap:
                cap = new_cap
 
            self.history["pp_cap"] = cap
 
        effective_cap = cap if cap is not None else self.PEP_CAP_TENTATIVE
 
        # ── Stop-loss (extreme thresholds — fires only in true catastrophe) ───
        # Monte Carlo on real data: 0% of ticks breach these thresholds.
        # Kept purely as safety net for synthetic/adversarial scenarios.
        if effective_cap == self.PEP_CAP_STRONG:
            stop_th, resume_th = self.PEP_STOP_STRONG, self.PEP_RESUME_STRONG
        elif effective_cap == self.PEP_CAP_WEAK:
            stop_th, resume_th = self.PEP_STOP_WEAK, self.PEP_RESUME_WEAK
        else:
            stop_th, resume_th = self.PEP_STOP_MODERATE, self.PEP_RESUME_MODERATE
 
        breach_count  = int(self.history["pp_breach"])
        drift_stopped = bool(self.history["pp_stopped"])
 
        if len(hist) >= 20:
            local_slope = hist[-1] - hist[-20]
            if local_slope < stop_th:
                breach_count += 1
            else:
                breach_count = 0
            if breach_count >= self.PEP_STOP_BREACH_COUNT:
                drift_stopped = True
            elif drift_stopped and local_slope > resume_th:
                drift_stopped = False
 
        self.history["pp_breach"]  = breach_count
        self.history["pp_stopped"] = drift_stopped
 
        # ── Stopped or neutral: orderly unwind ───────────────────────────────
        if drift_stopped or effective_cap == 0:
            if pos > 0:
                qty = min(pos, 25)
                qty = min(qty, bbv)
                if qty > 0:
                    orders.append(Order(PEPPER, int(bb), -qty))
            elif pos < 0:
                qty = min(-pos, 25)
                qty = min(qty, bav)
                if qty > 0:
                    orders.append(Order(PEPPER, int(ba), qty))
            return orders
 
        # ── Active: buy aggressively into uptrend ────────────────────────────
        rem_cap    = effective_cap - pos
        take_limit = (self.PEP_TAKE_STRONG if effective_cap == self.PEP_CAP_STRONG
                      else self.PEP_TAKE_NORMAL)
 
        if rem_cap > 0:
            budget = min(rem_cap, take_limit)
            # Cross the ask if within PEP_TAKE_CROSS_EDGE of mid
            for ask in sorted(od.sell_orders.keys()):
                if budget <= 0:
                    break
                if ask <= mid + self.PEP_TAKE_CROSS_EDGE:
                    qty = min(budget, -od.sell_orders[ask])
                    if qty > 0:
                        orders.append(Order(PEPPER, ask, qty))
                        budget  -= qty
                        rem_cap -= qty
 
            # Passive: join best bid + 1 when spread wide, or at best bid
            if rem_cap > 0:
                passive_qty = min(rem_cap, self.PEP_PASSIVE_MAX)
                if spread_widening:
                    passive_qty = int(passive_qty * self.PEP_SPREAD_PASSIVE_SCALE)
                if passive_qty > 0:
                    px = bb + (1 if spread >= 3 else 0)
                    orders.append(Order(PEPPER, int(px), passive_qty))
 
        # Light de-risk only when VERY overloaded and spread widening
        if spread_widening and pos > effective_cap * 0.95 and pos > 70:
            sell_qty = min(pos - int(effective_cap * 0.85), 5)
            if sell_qty > 0 and bav > 0:
                orders.append(Order(PEPPER, int(ba - 1), -sell_qty))
 
        return orders
 
    # ─────────────────────────────────────────────────────────────────────────
    # OSMIUM — tight MM, anchored firmly at 10000, fast watchdog
    # ─────────────────────────────────────────────────────────────────────────
    def _osmium(self, state: TradingState, od: OrderDepth) -> List[Order]:
        orders: List[Order] = []
        pos = state.position.get(OSMIUM, 0)
 
        bb, bbv = self._best_bid(od)
        ba, bav = self._best_ask(od)
        if bb is None or ba is None:
            return orders
 
        mid = (bb + ba) / 2.0
 
        # VWAP from top-2 levels
        sb, sbv = self._second_bid(od, bb)
        sa, sav = self._second_ask(od, ba)
        num = bb * bbv + ba * bav
        den = bbv + bav
        if sb is not None:
            num += sb * sbv; den += sbv
        if sa is not None:
            num += sa * sav; den += sav
        vwap = num / den if den > 0 else mid
 
        # Update EMAs
        self.history["osm_vwap_ema"] = self._ema(
            self.history["osm_vwap_ema"], vwap, self.OSM_FAIR_EMA_ALPHA)
        last = self.history["osm_last_mid"]
        if last is not None:
            self.history["osm_atr_ema"] = self._ema(
                self.history["osm_atr_ema"], abs(mid - last), self.OSM_ATR_ALPHA)
        self.history["osm_last_mid"] = mid
 
        atr      = max(self.OSM_ATR_MIN, min(self.OSM_ATR_MAX, self.history["osm_atr_ema"]))
        vwap_ema = self.history["osm_vwap_ema"] or vwap
 
        # ── Drift watchdog (fast: trip at 50 streak, not 120) ─────────────────
        drift  = vwap_ema - self.OSM_ANCHOR
        streak = self.history["osm_drift_streak"]
        if abs(drift) > self.OSM_DRIFT_THRESHOLD:
            streak = min(streak + 1, 1000)
        else:
            streak = max(streak - 2, 0)
        self.history["osm_drift_streak"] = streak
        in_drift = streak >= self.OSM_DRIFT_STREAK_TRIP
 
        # ── Adaptive anchor weight ─────────────────────────────────────────────
        # Data: max price deviation from 10k is only 20 ticks. 
        # Anchor weight stays high; only reduce in confirmed drift regime.
        if in_drift:
            anchor_w = 0.0
        elif abs(drift) > self.OSM_SOFT_DRIFT_THRESHOLD:
            t = min(1.0, (abs(drift) - self.OSM_SOFT_DRIFT_THRESHOLD) /
                    (self.OSM_DRIFT_THRESHOLD - self.OSM_SOFT_DRIFT_THRESHOLD))
            anchor_w = self.OSM_ANCHOR_WEIGHT * (1.0 - t) + self.OSM_SOFT_DRIFT_MIN_WEIGHT * t
        else:
            anchor_w = self.OSM_ANCHOR_WEIGHT
 
        fair = anchor_w * self.OSM_ANCHOR + (1.0 - anchor_w) * vwap_ema
 
        # OBI micro-bias (proven alpha: shifts fair ±0.6 when |OBI| ≥ 0.3)
        total_vol = bbv + bav
        obi = (bbv - bav) / total_vol if total_vol > 0 else 0.0
        if abs(obi) >= 0.3:
            fair += 0.6 * (1.0 if obi > 0 else -1.0)
 
        # Toxicity filter
        toxic_buys  = bbv >= self.OSM_TOXICITY
        toxic_sells = bav >= self.OSM_TOXICITY
 
        # Position-indexed take edge (reduced — data shows rare mispricing)
        edge_from_pos = min(self.OSM_TAKE_EDGE_MAX,
                            abs(pos) // self.OSM_EDGE_POS_STEP)
        take_edge = self.OSM_TAKE_EDGE_MAX - edge_from_pos
 
        rb = self.LIMIT - pos
        rs = self.LIMIT + pos
 
        # ── Cross-take on mispriced levels ────────────────────────────────────
        if not toxic_sells and ba <= fair - take_edge and rb > 0:
            q = min(rb, bav, 25)
            if q > 0:
                orders.append(Order(OSMIUM, int(ba), q))
                rb -= q; pos += q
 
        if not toxic_buys and bb >= fair + take_edge and rs > 0:
            q = min(rs, bbv, 25)
            if q > 0:
                orders.append(Order(OSMIUM, int(bb), -q))
                rs -= q; pos -= q
 
        # ── Hard flatten ──────────────────────────────────────────────────────
        flatten_target = self.OSM_DRIFT_FLATTEN_TARGET if in_drift else self.OSM_FLATTEN_TARGET
        flatten_hard   = flatten_target + 15
 
        if pos > flatten_hard and rs > 0:
            exit_px = bb if in_drift else int(round(fair))
            qty = min(pos - flatten_target + 5, rs)
            if qty > 0:
                orders.append(Order(OSMIUM, exit_px, -qty))
                rs -= qty; pos -= qty
        elif pos < -flatten_hard and rb > 0:
            exit_px = ba if in_drift else int(round(fair))
            qty = min(-pos - flatten_target + 5, rb)
            if qty > 0:
                orders.append(Order(OSMIUM, exit_px, qty))
                rb += qty; pos += qty
 
        # ── Adaptive quoting (ATR-scaled, more aggressive) ────────────────────
        half_spread = max(1, int(round(0.4 * atr)))
        bp = int(round(fair - half_spread))
        ap = int(round(fair + half_spread))
 
        if bp >= ba: bp = ba - 1
        if ap <= bb: ap = bb + 1
 
        # Inventory skew — earlier and stronger (data: std=3, so ±12 is ±4σ)
        if pos > self.OSM_SKEW_HARD:
            bp -= 1; ap -= 1
        elif pos > self.OSM_SKEW_SOFT:
            ap = max(bb + 1, ap - 1)
        elif pos < -self.OSM_SKEW_HARD:
            bp += 1; ap += 1
        elif pos < -self.OSM_SKEW_SOFT:
            bp = min(ba - 1, bp + 1)
 
        suppress_buy  = in_drift and drift < 0
        suppress_sell = in_drift and drift > 0
 
        front  = self.OSM_QUOTE_FRONT
        second = self.OSM_QUOTE_SECOND
        if in_drift:
            front  = max(3, front  // 2)
            second = max(2, second // 2)
 
        if rb > 0 and not toxic_buys and not suppress_buy:
            q = min(rb, front)
            orders.append(Order(OSMIUM, bp, q))
            rb -= q
            if rb > 0:
                orders.append(Order(OSMIUM, bp - 1, min(rb, second)))
 
        if rs > 0 and not toxic_sells and not suppress_sell:
            q = min(rs, front)
            orders.append(Order(OSMIUM, ap, -q))
            rs -= q
            if rs > 0:
                orders.append(Order(OSMIUM, ap + 1, -min(rs, second)))
 
        return orders
 
    # ─────────────────────────────────────────────────────────────────────────
    def run(self, state: TradingState):
        self._load(state)
 
        result: Dict[Symbol, List[Order]] = {}
        for sym, od in state.order_depths.items():
            if sym == PEPPER:
                result[sym] = self._pepper(state, od)
            elif sym == OSMIUM:
                result[sym] = self._osmium(state, od)
 
        return result, 0, self._save()