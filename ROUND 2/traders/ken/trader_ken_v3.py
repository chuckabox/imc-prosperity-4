"""
trader_ken_v3.py
================
Round 2 — suvin_test_v1 alpha, wrapped in ken's risk framework.

What this borrows (IDEAS, not code) from suvin_test_v1:
  * Pepper regime-cap classifier (base-anchor drift -> 80/60/30/0 cap tiers)
  * Two-speed warmup (fast-track at 500 ticks, full warmup at 1200)
  * Asymmetric cap updates: upgrade freely, downgrade only when warmed
  * Slope-based stop/resume with breach-count hysteresis
  * Soft spread-widening gate (scale down passive, don't halt)
  * Osmium VWAP-blended fair = 0.65 * vwap + 0.35 * anchor (5-tick smoothed)
  * Toxicity filter from market_trades imbalance (threshold 35)
  * Edge scaling with position: take_edge + |pos|//25
  * Early skew onset at pos >= 15 (hard at 35)
  * Hard flatten circuit-breaker at |pos| > 58 -> target 50
  * Dual-level quotes (front 28 / second 20) with size-scaling off anchor

What this keeps from ken_v2 (ken's safety + MAF):
  * Titan Shield: global PnL stop + per-product HWM trailing + hysteresis resume
  * Scale-free z-slope crash detector (no magic -12/-20) as secondary override
  * bid() for MAF auction
  * Gap-safe mid handling, max(0, qty) guards everywhere
  * State serialization (traderData round-trip)

Stack of shields (outer -> inner):
  1. gl_pnl stop / per-product kill (Titan) -> full liquidate.
  2. z-slope crash override -> full dump + 200t lockout.
  3. suvin's slope-based stop/resume -> orderly 20/tick exit.
  4. suvin's regime-cap drift classifier -> position cap.
"""

import json
import math
from typing import Dict, List, Any

from datamodel import Order, OrderDepth, TradingState, Symbol


PEPPER = "INTARIAN_PEPPER_ROOT"
OSMIUM = "ASH_COATED_OSMIUM"


def _median(vals: list) -> float:
    n = len(vals)
    if n == 0:
        return 0.0
    s = sorted(vals)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def _std(vals: list) -> float:
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    var = sum((x - m) * (x - m) for x in vals) / n
    return math.sqrt(var)


class Trader:
    LIMIT = 80

    # ---------------- Titan Shield ----------------
    GLOBAL_PNL_STOP = -5000.0
    PRODUCT_TRAIL = 3000.0             # looser than safe (3k vs 2.5k) to give
                                       # suvin's own stop/resume room to work
    HWM_RECOVER_MARGIN = 500.0

    # ---------------- Scale-free crash override ----------------
    # Secondary shield: fires only on REALLY sharp drops that suvin's own
    # slope stop might miss (novel regimes with different volatility profile).
    CRASH_WINDOW = 20
    CRASH_Z_STOP = -3.0                # stricter than safe (-2.5) / agg (-2.0)
    CRASH_Z_RESUME = 1.0
    CRASH_MIN_HIST = 30
    CRASH_LOCKOUT_TICKS = 150

    # ---------------- Pepper: suvin's regime-cap classifier ----------------
    PEPPER_WARMUP_TICKS = 1200
    PEPPER_FAST_TRACK_TICKS = 500

    # Drift thresholds (mid-ticks per 100 elapsed ticks, normalised)
    PEPPER_SLOPE_STRONG   =  0.08
    PEPPER_SLOPE_MODERATE =  0.04
    PEPPER_SLOPE_WEAK     = -0.01

    PEPPER_CAP_STRONG    = 80
    PEPPER_CAP_MODERATE  = 60
    PEPPER_CAP_WEAK      = 30
    PEPPER_CAP_NEGATIVE  = 0
    PEPPER_CAP_TENTATIVE = 20          # before warmup finalizes

    PEPPER_TAKE_STRONG = 20
    PEPPER_TAKE_NORMAL = 12
    PEPPER_PASSIVE_MAX = 40

    # Slope-based stop (20-tick local slope)
    PEPPER_STOP_BREACH_COUNT   = 2
    PEPPER_STOP_STRONG         = -14
    PEPPER_STOP_MODERATE       = -10
    PEPPER_STOP_WEAK           = -7
    PEPPER_RESUME_STRONG       = 6
    PEPPER_RESUME_MODERATE     = 5
    PEPPER_RESUME_WEAK         = 4

    PEPPER_SPREAD_PASSIVE_SCALE = 0.4  # when spread widens, scale passive size

    # ---------------- Osmium: suvin's alpha ----------------
    OSMIUM_ANCHOR = 10_000

    OSMIUM_TOXICITY_THRESHOLD = 35     # imbalance in market_trades
    OSMIUM_TAKE_EDGE = 1               # base take edge
    OSMIUM_EDGE_POS_STEP = 25          # widen edge per 25-lot inventory

    OSMIUM_SKEW_SOFT    = 15
    OSMIUM_SKEW_HARD    = 35
    OSMIUM_FLATTEN_HARD = 58
    OSMIUM_FLATTEN_TGT  = 50

    OSMIUM_QUOTE_FRONT  = 28
    OSMIUM_QUOTE_SECOND = 20

    OSMIUM_VWAP_WEIGHT = 0.65          # 0.65*vwap + 0.35*anchor

    def __init__(self):
        self.history: Dict[str, Any] = {}

    # IMC Market Access Fee.  Tunable via bid_sweep.
    def bid(self) -> int:
        return 15

    # ------------------------------------------------------------------
    # State plumbing
    # ------------------------------------------------------------------
    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        else:
            self.history = self.history or {}

        for p in (PEPPER, OSMIUM):
            self.history.setdefault(f"{p}_mid_hist", [])
            self.history.setdefault(f"{p}_cpnl", 0.0)
            self.history.setdefault(f"{p}_hwm", 0.0)
            self.history.setdefault(f"{p}_killed", False)
            self.history.setdefault(f"{p}_last_mid", None)
            self.history.setdefault(f"{p}_last_pos", 0)
            self.history.setdefault(f"{p}_crash_locked_until", -1)
        # Pepper-specific state
        self.history.setdefault("pp_base", [])           # first 15 mids as anchor
        self.history.setdefault("pp_t0", None)
        self.history.setdefault("pp_prev_spread", None)
        self.history.setdefault("pp_cap", None)
        self.history.setdefault("pp_breach", 0)
        self.history.setdefault("pp_stopped", False)
        # Osmium state
        self.history.setdefault("op_fair_hist", [])
        # Global
        self.history.setdefault("gl_pnl", 0.0)
        self.history.setdefault("gl_killed", False)

    def _save_state(self) -> str:
        return json.dumps(self.history)

    # ------------------------------------------------------------------
    # Book helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _best_bid_ask(depth: OrderDepth):
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    # ------------------------------------------------------------------
    # PnL tracking + Titan shield (shared with ken_v2)
    # ------------------------------------------------------------------
    def _update_pnl_tracking(self, product: str, pos: int, mid: float) -> None:
        last_mid = self.history.get(f"{product}_last_mid")
        last_pos = self.history.get(f"{product}_last_pos", 0)
        if last_mid is not None:
            delta = (mid - last_mid) * last_pos
            self.history[f"{product}_cpnl"] = self.history.get(f"{product}_cpnl", 0.0) + delta
            self.history["gl_pnl"] = self.history.get("gl_pnl", 0.0) + delta
        cpnl = self.history[f"{product}_cpnl"]
        hwm = max(self.history.get(f"{product}_hwm", 0.0), cpnl)
        self.history[f"{product}_hwm"] = hwm
        self.history[f"{product}_last_mid"] = mid
        self.history[f"{product}_last_pos"] = pos

    def _titan_fire(self, product: str) -> bool:
        if self.history.get("gl_killed", False):
            return True
        if self.history.get("gl_pnl", 0.0) < self.GLOBAL_PNL_STOP:
            self.history["gl_killed"] = True
            return True
        cpnl = self.history.get(f"{product}_cpnl", 0.0)
        hwm = self.history.get(f"{product}_hwm", 0.0)
        if hwm - cpnl > self.PRODUCT_TRAIL:
            self.history[f"{product}_killed"] = True
        if self.history.get(f"{product}_killed", False):
            if hwm - cpnl < self.HWM_RECOVER_MARGIN:
                self.history[f"{product}_killed"] = False
                return False
            return True
        return False

    @staticmethod
    def _liquidate(product: str, pos: int, bb, ba) -> List[Order]:
        if pos > 0 and bb is not None:
            return [Order(product, bb, -pos)]
        if pos < 0 and ba is not None:
            return [Order(product, ba, -pos)]
        return []

    # ------------------------------------------------------------------
    # Generalized scale-free crash override (secondary shield)
    # ------------------------------------------------------------------
    def _z_slope(self, hist: list) -> float:
        w = self.CRASH_WINDOW
        if len(hist) < w + 1:
            return 0.0
        recent = hist[-(w + 1):]
        returns = [recent[i + 1] - recent[i] for i in range(w)]
        s = _std(returns)
        if s <= 1e-9:
            return 0.0
        raw_slope = recent[-1] - recent[0]
        return raw_slope / (s * math.sqrt(w))

    def _crash_override(self, product: str, hist: list, ts: int) -> bool:
        if len(hist) < self.CRASH_MIN_HIST:
            return False
        z = self._z_slope(hist)
        locked_until = self.history.get(f"{product}_crash_locked_until", -1)
        currently_locked = ts < locked_until
        if z < self.CRASH_Z_STOP:
            self.history[f"{product}_crash_locked_until"] = ts + self.CRASH_LOCKOUT_TICKS
            return True
        if currently_locked:
            if z > self.CRASH_Z_RESUME:
                self.history[f"{product}_crash_locked_until"] = -1
                return False
            return True
        return False

    # ------------------------------------------------------------------
    # PEPPER_ROOT — suvin_test_v1's regime classifier + ken's shields
    # ------------------------------------------------------------------
    def _pepper_logic(self, state: TradingState) -> List[Order]:
        if PEPPER not in state.order_depths:
            return []
        depth = state.order_depths[PEPPER]
        pos = state.position.get(PEPPER, 0)
        bb, ba = self._best_bid_ask(depth)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0
        spread = ba - bb
        ts = state.timestamp

        hist = self.history[f"{PEPPER}_mid_hist"]
        hist.append(mid)
        if len(hist) > 120:
            hist = hist[-120:]
        self.history[f"{PEPPER}_mid_hist"] = hist

        base_samples = self.history["pp_base"]
        if len(base_samples) < 15:
            base_samples.append(mid)
            self.history["pp_base"] = base_samples

        if self.history.get("pp_t0") is None:
            self.history["pp_t0"] = ts
        start_ts = self.history["pp_t0"]

        self._update_pnl_tracking(PEPPER, pos, mid)

        # --- Outer shield 1: Titan ---
        if self._titan_fire(PEPPER):
            return self._liquidate(PEPPER, pos, bb, ba)

        # --- Outer shield 2: z-slope crash override ---
        if self._crash_override(PEPPER, hist, ts):
            if pos > 0:
                return [Order(PEPPER, bb, -pos)]
            return []

        # --- Spread-widening soft gate ---
        prev_spread = self.history.get("pp_prev_spread")
        spread_widening = prev_spread is not None and spread > prev_spread
        self.history["pp_prev_spread"] = spread

        # --- Regime classification (suvin's drift-per-100-ticks) ---
        elapsed = ts - start_ts
        warmed_up = elapsed >= self.PEPPER_WARMUP_TICKS
        fast_track = elapsed >= self.PEPPER_FAST_TRACK_TICKS

        cap = self.history.get("pp_cap")

        if len(base_samples) >= 15 and len(hist) >= 15:
            base_mean = _median(base_samples)
            current_mean = _median(hist[-15:])
            dt = max(1, elapsed)
            drift = (current_mean - base_mean) / dt * 100.0

            if fast_track and drift >= self.PEPPER_SLOPE_STRONG:
                new_cap = self.PEPPER_CAP_STRONG
            elif warmed_up:
                if drift > self.PEPPER_SLOPE_MODERATE:
                    new_cap = self.PEPPER_CAP_STRONG
                elif drift > self.PEPPER_SLOPE_WEAK:
                    new_cap = self.PEPPER_CAP_MODERATE
                elif drift > -0.02:
                    new_cap = self.PEPPER_CAP_WEAK
                else:
                    new_cap = self.PEPPER_CAP_NEGATIVE
            else:
                new_cap = cap

            # Upgrade freely, downgrade only at full warmup.
            if cap is None:
                cap = new_cap if new_cap is not None else self.PEPPER_CAP_TENTATIVE
            elif new_cap is not None and new_cap > cap:
                cap = new_cap
            elif warmed_up and new_cap is not None and new_cap < cap:
                cap = new_cap
            self.history["pp_cap"] = cap

        effective_cap = cap if cap is not None else self.PEPPER_CAP_TENTATIVE

        # --- Slope-based stop (inner, matched to cap tier) ---
        if effective_cap == self.PEPPER_CAP_STRONG:
            stop_th, resume_th = self.PEPPER_STOP_STRONG, self.PEPPER_RESUME_STRONG
        elif effective_cap == self.PEPPER_CAP_WEAK:
            stop_th, resume_th = self.PEPPER_STOP_WEAK, self.PEPPER_RESUME_WEAK
        else:
            stop_th, resume_th = self.PEPPER_STOP_MODERATE, self.PEPPER_RESUME_MODERATE

        breach = int(self.history.get("pp_breach", 0))
        stopped = bool(self.history.get("pp_stopped", False))
        if len(hist) >= 20:
            local_slope = hist[-1] - hist[-20]
            if local_slope < stop_th:
                breach += 1
            else:
                breach = 0
            if breach >= self.PEPPER_STOP_BREACH_COUNT:
                stopped = True
            elif stopped and local_slope > resume_th:
                stopped = False
        self.history["pp_breach"] = breach
        self.history["pp_stopped"] = stopped

        orders: List[Order] = []

        # --- Stopped regime: orderly exit (20/tick via best bid) ---
        if stopped or effective_cap == 0:
            if pos > 0:
                avail = depth.buy_orders.get(bb, 0)
                qty = max(0, min(pos, 20, avail))
                if qty > 0:
                    orders.append(Order(PEPPER, bb, -qty))
            return orders

        # --- Normal regime: accumulate toward cap ---
        rem_cap = max(0, effective_cap - pos)
        take_limit = (self.PEPPER_TAKE_STRONG if effective_cap == self.PEPPER_CAP_STRONG
                      else self.PEPPER_TAKE_NORMAL)

        if rem_cap > 0:
            budget = min(rem_cap, take_limit)
            for ask in sorted(depth.sell_orders.keys()):
                if budget <= 0:
                    break
                if ask <= mid + 1.5:
                    avail = -depth.sell_orders[ask]
                    qty = max(0, min(budget, avail))
                    if qty > 0:
                        orders.append(Order(PEPPER, ask, qty))
                        budget -= qty
                        rem_cap -= qty

            if rem_cap > 0:
                passive = max(0, min(rem_cap, self.PEPPER_PASSIVE_MAX))
                if spread_widening:
                    passive = int(passive * self.PEPPER_SPREAD_PASSIVE_SCALE)
                if passive > 0:
                    orders.append(Order(PEPPER, bb + 1, passive))

        # --- Light de-risk when overloaded and spread widens ---
        if spread_widening and pos > effective_cap * 0.5:
            sell_qty = max(0, min(pos, 10))
            if sell_qty > 0:
                orders.append(Order(PEPPER, ba - 1, -sell_qty))

        return orders

    # ------------------------------------------------------------------
    # OSMIUM — suvin_test_v1's VWAP-blend + toxicity filter
    # ------------------------------------------------------------------
    def _osmium_logic(self, state: TradingState) -> List[Order]:
        if OSMIUM not in state.order_depths:
            return []
        depth = state.order_depths[OSMIUM]
        pos = state.position.get(OSMIUM, 0)
        bb, ba = self._best_bid_ask(depth)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0

        self._update_pnl_tracking(OSMIUM, pos, mid)

        if self._titan_fire(OSMIUM):
            return self._liquidate(OSMIUM, pos, bb, ba)

        # --- VWAP-blended fair value (anchored) ---
        bv1 = depth.buy_orders[bb]
        av1 = -depth.sell_orders[ba]
        total = bv1 + av1
        vwap_mid = ((bb * av1 + ba * bv1) / total) if total > 0 else mid
        fair = self.OSMIUM_VWAP_WEIGHT * vwap_mid + (1 - self.OSMIUM_VWAP_WEIGHT) * self.OSMIUM_ANCHOR

        op_hist = self.history["op_fair_hist"]
        op_hist.append(fair)
        if len(op_hist) > 30:
            op_hist = op_hist[-30:]
        self.history["op_fair_hist"] = op_hist
        if len(op_hist) >= 5:
            fair = 0.6 * fair + 0.4 * (sum(op_hist[-5:]) / 5.0)

        # --- Toxicity filter from market_trades imbalance ---
        buy_vol = sell_vol = 0
        mt = state.market_trades.get(OSMIUM, []) if state.market_trades else []
        for t in mt:
            if t.price >= mid:
                buy_vol += abs(t.quantity)
            else:
                sell_vol += abs(t.quantity)
        imbalance = buy_vol - sell_vol
        toxic_buys  = imbalance >=  self.OSMIUM_TOXICITY_THRESHOLD
        toxic_sells = imbalance <= -self.OSMIUM_TOXICITY_THRESHOLD

        orders: List[Order] = []
        rb = max(0, self.LIMIT - pos)
        rs = max(0, self.LIMIT + pos)

        # --- Hard flatten circuit-breaker: |pos| > 58 -> target 50 at fair ---
        if pos > self.OSMIUM_FLATTEN_HARD and rs > 0:
            flatten = max(0, min(pos - self.OSMIUM_FLATTEN_TGT + 5, rs))
            if flatten > 0:
                orders.append(Order(OSMIUM, int(fair), -flatten))
                rs -= flatten
                pos -= flatten
        elif pos < -self.OSMIUM_FLATTEN_HARD and rb > 0:
            flatten = max(0, min(-pos - self.OSMIUM_FLATTEN_TGT + 5, rb))
            if flatten > 0:
                orders.append(Order(OSMIUM, int(fair), flatten))
                rb -= flatten
                pos += flatten

        # --- Take: edge scales with inventory (widen when overloaded) ---
        buy_edge  = self.OSMIUM_TAKE_EDGE + max(0, pos  // self.OSMIUM_EDGE_POS_STEP)
        sell_edge = self.OSMIUM_TAKE_EDGE + max(0, (-pos) // self.OSMIUM_EDGE_POS_STEP)

        if not toxic_buys:
            for ask in sorted(depth.sell_orders.keys()):
                if rb <= 0:
                    break
                if ask <= fair - buy_edge:
                    avail = -depth.sell_orders[ask]
                    q = max(0, min(rb, avail))
                    if q > 0:
                        orders.append(Order(OSMIUM, ask, q))
                        rb -= q
                        pos += q

        if not toxic_sells:
            for bid_p in sorted(depth.buy_orders.keys(), reverse=True):
                if rs <= 0:
                    break
                if bid_p >= fair + sell_edge:
                    avail = depth.buy_orders[bid_p]
                    q = max(0, min(rs, avail))
                    if q > 0:
                        orders.append(Order(OSMIUM, bid_p, -q))
                        rs -= q
                        pos -= q

        # --- MM quotes (early skew + size scaling off anchor) ---
        skew = int(pos / self.OSMIUM_SKEW_SOFT)

        bp = int(min(bb + 1, fair - 1)) - skew
        ap = int(max(ba - 1, fair + 1)) - skew

        bp = max(bp, int(fair) - 4)
        ap = min(ap, int(fair) + 4)

        if pos > self.OSMIUM_SKEW_HARD:
            bp -= 1
        if pos < -self.OSMIUM_SKEW_HARD:
            ap += 1

        if bp >= ap:
            bp = int(fair) - 1
            ap = int(fair) + 1

        anchor_drift = abs(fair - self.OSMIUM_ANCHOR)
        size_scale = max(0.5, 1.0 - anchor_drift / 20.0) if anchor_drift > 5 else 1.0
        front  = max(6, int(self.OSMIUM_QUOTE_FRONT  * size_scale))
        second = max(4, int(self.OSMIUM_QUOTE_SECOND * size_scale))

        if rb > 0:
            q = max(0, min(rb, front))
            if q > 0:
                orders.append(Order(OSMIUM, bp, q))
                rb -= q
            if rb > 0:
                q2 = max(0, min(rb, second))
                if q2 > 0:
                    orders.append(Order(OSMIUM, bp - 1, q2))

        if rs > 0:
            q = max(0, min(rs, front))
            if q > 0:
                orders.append(Order(OSMIUM, ap, -q))
                rs -= q
            if rs > 0:
                q2 = max(0, min(rs, second))
                if q2 > 0:
                    orders.append(Order(OSMIUM, ap + 1, -q2))

        return orders

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        pep = self._pepper_logic(state)
        if pep:
            result[PEPPER] = pep

        osm = self._osmium_logic(state)
        if osm:
            result[OSMIUM] = osm

        return result, 0, self._save_state()
