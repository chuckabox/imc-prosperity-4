"""
chimera_safe.py — Round 2: Best-of-Team Combination + Crash Protection
=======================================================================
Base: Holy Grail (v8) — proven top Pepper regime classifier + Osmium MM.
Added: Ken v4's Titan Shield, z-slope crash override, AR(3) Osmium fair.
Added: Peter v101's linreg-smoothed stop, multi-level VWAP, flow skew.
Added: End-of-day position flatten + drawdown-triggered cap reduction.
Fixed: Osmium flatten-short rb bug (Peter v101 discovery).

Philosophy: SAFE — conservative entry, tight exits, no-loss priority.

Shield stack (outer → inner):
  1. Titan Shield: global PnL stop + per-product HWM trailing → liquidate.
  2. Z-slope crash override → full dump + 200-tick lockout.
  3. Linreg-smoothed slope stop/resume → orderly 20/tick exit.
  4. Drawdown cap reduction → halve cap when cpnl draws down > 2000.
  5. EOD position flatten → progressive cap reduction from tick 8500.
  6. Regime-cap drift classifier → position cap (0/30/60/80).

MAF bid: 100 (moderate — likely top-50% without overpaying).

Pepper params: SAFE (TAKE_STRONG=25, PASSIVE=50, BREACH=2, STOP=-14).
Osmium params: AR(3) fair + multi-level VWAP + flow skew, moderate quotes.
"""

import json
import math
from typing import Dict, List, Any

from datamodel import Order, OrderDepth, TradingState, Symbol


PEPPER = "INTARIAN_PEPPER_ROOT"
OSMIUM = "ASH_COATED_OSMIUM"


# ═══════════════════════════════════════════════════════════════════════════
# Helper functions
# ═══════════════════════════════════════════════════════════════════════════

def _median(vals: list) -> float:
    n = len(vals)
    if n == 0:
        return 0.0
    s = sorted(vals)
    mid = n // 2
    return float(s[mid]) if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0


def _std(vals: list) -> float:
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    var = sum((x - m) * (x - m) for x in vals) / n
    return math.sqrt(var)


def _linreg_slope(vals: list) -> float:
    """OLS slope in price-per-sample over the given window."""
    n = len(vals)
    if n < 2:
        return 0.0
    xm = (n - 1) / 2.0
    ym = sum(vals) / n
    num = sum((i - xm) * (v - ym) for i, v in enumerate(vals))
    den = sum((i - xm) ** 2 for i in range(n))
    return num / den if den else 0.0


# ═══════════════════════════════════════════════════════════════════════════


class Trader:
    LIMIT = 80

    # ══════════════════════════════════════════════════════════════════════
    # TITAN SHIELD  (from Ken v2/v3/v4)
    # ══════════════════════════════════════════════════════════════════════
    GLOBAL_PNL_STOP    = -15000.0  # hard cut if combined PnL sinks below this
    PRODUCT_TRAIL      =  8000.0   # per-product HWM trailing drawdown (Pepper only)
    HWM_RECOVER_MARGIN =  1000.0   # must recover within this of HWM to resume

    # ══════════════════════════════════════════════════════════════════════
    # Z-SLOPE CRASH OVERRIDE  (from Ken v2 safe — strictest variant)
    # ══════════════════════════════════════════════════════════════════════
    CRASH_WINDOW        = 20
    CRASH_Z_STOP        = -2.5     # z-score trigger (scale-free, no magic numbers)
    CRASH_Z_RESUME      =  1.0     # positive z to resume
    CRASH_MIN_HIST      = 30       # minimum history before crash check is armed
    CRASH_LOCKOUT_TICKS = 200      # buy-lockout after firing

    # ══════════════════════════════════════════════════════════════════════
    # PEPPER CONSTANTS  (Safe: conservative entry, tight exits)
    # ══════════════════════════════════════════════════════════════════════
    PEPPER_WARMUP_TICKS      = 1200
    PEPPER_FAST_TRACK_TICKS  = 300   # HG was 200 — wait longer to confirm

    PEPPER_SLOPE_STRONG_FAST = 0.06  # HG was 0.05 — require clearer signal
    PEPPER_SLOPE_STRONG      = 0.04
    PEPPER_SLOPE_MODERATE    = 0.01
    PEPPER_SLOPE_WEAK        = -0.01

    PEPPER_CAP_STRONG    = 80
    PEPPER_CAP_MODERATE  = 60
    PEPPER_CAP_WEAK      = 30
    PEPPER_CAP_NEGATIVE  =  0
    PEPPER_CAP_TENTATIVE = 20       # HG was 25 — less blind risk before warmup

    PEPPER_TAKE_STRONG   = 25       # HG was 32 — more measured fills
    PEPPER_TAKE_NORMAL   = 14       # HG was 18
    PEPPER_PASSIVE_MAX   = 50       # HG was 65
    PEPPER_TAKE_CROSS_EDGE = 1.5    # HG was 2.0 — tighter cross filter

    PEPPER_STOP_BREACH_COUNT = 2    # HG was 3 — trigger stop sooner
    PEPPER_STOP_STRONG    = -14     # HG was -20 — exit sooner on pullbacks
    PEPPER_STOP_MODERATE  = -10
    PEPPER_STOP_WEAK      =  -7
    PEPPER_RESUME_STRONG  =   6     # HG was 5 — need stronger bounce to re-enter
    PEPPER_RESUME_MODERATE=   5
    PEPPER_RESUME_WEAK    =   4

    PEPPER_SPREAD_PASSIVE_SCALE = 0.5   # HG was 0.75 — cut passive more on wide spread
    PEPPER_DERISK_THRESHOLD     = 0.5   # HG was 0.6 — de-risk earlier
    PEPPER_DERISK_QTY           = 10    # HG was 8 — sell more when de-risking

    # End-of-day position flatten (tick-based progressive reduction)
    PEPPER_EOD_PHASES = [(8500, 0.75), (9000, 0.50), (9500, 0.25), (9800, 0.0)]

    # Drawdown-triggered cap reduction
    PEPPER_DD_THRESHOLD = 2000.0    # halve cap when cpnl drops this much from HWM

    # ══════════════════════════════════════════════════════════════════════
    # OSMIUM CONSTANTS
    # ══════════════════════════════════════════════════════════════════════
    OSMIUM_ANCHOR = 10_000

    OSMIUM_TOXICITY_THRESHOLD  = 35
    OSMIUM_FLOW_SKEW_THRESHOLD = 15    # Peter v101: sub-toxic flow lean
    OSMIUM_TAKE_EDGE      = 0          # Ken v4: take at fair (not Suvin's -1)
    OSMIUM_EDGE_POS_STEP  = 30
    OSMIUM_TAKE_EDGE_MAX  = 3

    OSMIUM_SKEW_SOFT      = 15
    OSMIUM_SKEW_HARD      = 35
    OSMIUM_FLATTEN_HARD   = 58
    OSMIUM_FLATTEN_TARGET = 50

    OSMIUM_QUOTE_FRONT    = 35         # moderate (between 28 and 40)
    OSMIUM_QUOTE_SECOND   = 25

    OSMIUM_SPREAD_CLAMP   = 5
    OSMIUM_VWAP_WEIGHT    = 0.65
    OSMIUM_DRIFT_SCALE_AT = 8
    OSMIUM_VWAP_LEVELS    = 3          # Peter v101: multi-level depth VWAP

    # AR(3) fair value predictor (Ken v4: novel alpha from R1 patterns.md)
    OSMIUM_AR3_WINDOW      = 300       # rolling window (reduced for state size safety)
    OSMIUM_AR3_REFIT_EVERY = 50        # refit every N ticks
    OSMIUM_AR3_MIN_FIT     = 60        # minimum samples before using AR(3)
    OSMIUM_AR3_BLEND       = 0.70      # 0.70*AR3 + 0.30*(VWAP-blend fallback)

    def __init__(self):
        self.history: Dict[str, Any] = {}

    # ══════════════════════════════════════════════════════════════════════
    # MARKET ACCESS FEE  (Round 2 only; ignored in other rounds)
    # ══════════════════════════════════════════════════════════════════════
    def bid(self) -> int:
        return 100

    # ══════════════════════════════════════════════════════════════════════
    # STATE PLUMBING
    # ══════════════════════════════════════════════════════════════════════
    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        else:
            self.history = self.history or {}

        # Per-product state
        for p in (PEPPER, OSMIUM):
            self.history.setdefault(f"{p}_mid_hist", [])
            self.history.setdefault(f"{p}_cpnl", 0.0)
            self.history.setdefault(f"{p}_hwm", 0.0)
            self.history.setdefault(f"{p}_killed", False)
            self.history.setdefault(f"{p}_last_mid", None)
            self.history.setdefault(f"{p}_last_pos", 0)
            self.history.setdefault(f"{p}_crash_locked_until", -1)

        # Pepper-specific
        self.history.setdefault("pp_base", [])
        self.history.setdefault("pp_t0", None)
        self.history.setdefault("pp_prev_spread", None)
        self.history.setdefault("pp_cap", None)
        self.history.setdefault("pp_breach", 0)
        self.history.setdefault("pp_stopped", False)

        # Osmium-specific
        self.history.setdefault("op_fair_hist", [])
        self.history.setdefault("op_mid_buf", [])
        self.history.setdefault("op_ar3_intercept", 0.0)
        self.history.setdefault("op_ar3_w", [0.0, 0.0, 0.0])
        self.history.setdefault("op_ar3_fitted", False)
        self.history.setdefault("op_ar3_last_fit", -9999)

        # Global
        self.history.setdefault("gl_pnl", 0.0)
        self.history.setdefault("gl_killed", False)
        self.history.setdefault("tick", 0)

    def _save_state(self) -> str:
        return json.dumps(self.history)

    # ══════════════════════════════════════════════════════════════════════
    # BOOK HELPERS
    # ══════════════════════════════════════════════════════════════════════
    @staticmethod
    def _best_bid_ask(depth: OrderDepth):
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    # ══════════════════════════════════════════════════════════════════════
    # PNL TRACKING + TITAN SHIELD  (from Ken v2/v3/v4)
    # ══════════════════════════════════════════════════════════════════════
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
        """Return True if Titan Shield wants this product liquidated."""
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

    # ══════════════════════════════════════════════════════════════════════
    # Z-SLOPE CRASH OVERRIDE  (from Ken v2 safe — scale-free detector)
    # ══════════════════════════════════════════════════════════════════════
    def _z_slope(self, hist: list) -> float:
        """Z-scored slope over CRASH_WINDOW ticks. Scale-free."""
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
        """True if crash shield is ACTIVE (block buys + liquidate longs)."""
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

    # ══════════════════════════════════════════════════════════════════════
    # OSMIUM AR(3) FAIR VALUE  (from Ken v4 — novel alpha)
    # ══════════════════════════════════════════════════════════════════════
    def _osmium_ar3_refit(self, buf: List[float]) -> None:
        """Refit 4-param OLS: y_t = c + w1*y_{t-1} + w2*y_{t-2} + w3*y_{t-3}.
        Uses 4x4 normal equations solved via Gauss elimination (no numpy)."""
        n = len(buf) - 3
        if n < self.OSMIUM_AR3_MIN_FIT:
            return
        # Build X^T X (4x4) and X^T y (4) from rolling rows [1, m1, m2, m3]
        sx = [[0.0] * 4 for _ in range(4)]
        sy = [0.0] * 4
        for i in range(3, len(buf)):
            row = (1.0, buf[i - 1], buf[i - 2], buf[i - 3])
            y = buf[i]
            for a in range(4):
                sy[a] += row[a] * y
                for b in range(4):
                    sx[a][b] += row[a] * row[b]
        # Solve 4x4 by Gaussian elimination (augmented matrix sx|sy)
        M = [sx[a] + [sy[a]] for a in range(4)]
        for k in range(4):
            piv = k
            for r in range(k + 1, 4):
                if abs(M[r][k]) > abs(M[piv][k]):
                    piv = r
            if abs(M[piv][k]) < 1e-9:
                return  # singular — keep previous coefficients
            if piv != k:
                M[k], M[piv] = M[piv], M[k]
            inv = 1.0 / M[k][k]
            for c in range(k, 5):
                M[k][c] *= inv
            for r in range(4):
                if r == k:
                    continue
                f = M[r][k]
                if f != 0.0:
                    for c in range(k, 5):
                        M[r][c] -= f * M[k][c]
        coef = [M[a][4] for a in range(4)]
        self.history["op_ar3_intercept"] = coef[0]
        self.history["op_ar3_w"] = [coef[1], coef[2], coef[3]]
        self.history["op_ar3_fitted"] = True

    def _osmium_ar3_predict(self, mid: float, fallback: float) -> float:
        """Append current mid to buffer, refit on schedule, predict next fair."""
        buf: List[float] = self.history["op_mid_buf"]
        buf.append(mid)
        if len(buf) > self.OSMIUM_AR3_WINDOW:
            buf = buf[-self.OSMIUM_AR3_WINDOW:]
        self.history["op_mid_buf"] = buf

        tick = len(buf)
        last_fit = self.history.get("op_ar3_last_fit", -9999)
        if tick - last_fit >= self.OSMIUM_AR3_REFIT_EVERY:
            self._osmium_ar3_refit(buf)
            self.history["op_ar3_last_fit"] = tick

        if not self.history.get("op_ar3_fitted", False) or len(buf) < 3:
            return fallback

        intc = self.history["op_ar3_intercept"]
        w = self.history["op_ar3_w"]
        pred = intc + w[0] * buf[-1] + w[1] * buf[-2] + w[2] * buf[-3]
        # Sanity clamp: never let AR(3) wander more than 50 ticks from anchor
        if abs(pred - self.OSMIUM_ANCHOR) > 50:
            return fallback
        return pred

    # ══════════════════════════════════════════════════════════════════════
    # PEPPER ROOT  (Holy Grail base + all shields + EOD flatten)
    # ══════════════════════════════════════════════════════════════════════
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
        tick = self.history["tick"]

        # ── History ──────────────────────────────────────────────────────
        hist = self.history[f"{PEPPER}_mid_hist"]
        hist.append(mid)
        if len(hist) > 120:
            hist = hist[-120:]
        self.history[f"{PEPPER}_mid_hist"] = hist

        base_samples = self.history["pp_base"]
        if len(base_samples) < 15:
            base_samples.append(mid)
            self.history["pp_base"] = base_samples

        if self.history["pp_t0"] is None:
            self.history["pp_t0"] = ts
        start_ts = self.history["pp_t0"]

        self._update_pnl_tracking(PEPPER, pos, mid)

        # ── SHIELD 1: Titan (Pepper only — directional bet) ──────────────
        if self._titan_fire(PEPPER):
            return self._liquidate(PEPPER, pos, bb, ba)

        # ── SHIELD 2: Z-slope crash override ─────────────────────────────
        if self._crash_override(PEPPER, hist, ts):
            if pos > 0:
                return [Order(PEPPER, bb, -pos)]
            return []

        # ── Spread widening detection ─────────────────────────────────────
        prev_spread = self.history.get("pp_prev_spread")
        spread_widening = prev_spread is not None and spread > prev_spread
        self.history["pp_prev_spread"] = spread

        # ── Regime classification (drift-per-100-ticks) ──────────────────
        elapsed = ts - start_ts
        warmed_up = elapsed >= self.PEPPER_WARMUP_TICKS
        fast_track = elapsed >= self.PEPPER_FAST_TRACK_TICKS

        cap = self.history.get("pp_cap")

        if len(base_samples) >= 15 and len(hist) >= 15:
            base_mean = _median(base_samples)
            current_mean = _median(hist[-15:])
            dt = max(1, elapsed)
            drift = (current_mean - base_mean) / dt * 100.0

            if fast_track and drift >= self.PEPPER_SLOPE_STRONG_FAST:
                new_cap = self.PEPPER_CAP_STRONG
            elif warmed_up:
                if drift > self.PEPPER_SLOPE_STRONG:
                    new_cap = self.PEPPER_CAP_STRONG
                elif drift > self.PEPPER_SLOPE_MODERATE:
                    new_cap = self.PEPPER_CAP_MODERATE
                elif drift > self.PEPPER_SLOPE_WEAK:
                    new_cap = self.PEPPER_CAP_WEAK
                else:
                    new_cap = self.PEPPER_CAP_NEGATIVE
            else:
                new_cap = cap

            # Upgrade freely, downgrade only after full warmup
            if cap is None:
                cap = new_cap if new_cap is not None else self.PEPPER_CAP_TENTATIVE
            elif new_cap is not None and new_cap > cap:
                cap = new_cap
            elif warmed_up and new_cap is not None and new_cap < cap:
                cap = new_cap

            self.history["pp_cap"] = cap

        effective_cap = cap if cap is not None else self.PEPPER_CAP_TENTATIVE

        # Save the REGIME cap for stop-threshold selection (reflects market,
        # not our risk budget). EOD/DD modifications below change our sizing
        # but the market regime determines how sensitive stops should be.
        regime_cap = effective_cap

        # ── SHIELD 5: EOD position reduction ─────────────────────────────
        eod_mult = 1.0
        for phase_tick, mult in self.PEPPER_EOD_PHASES:
            if tick >= phase_tick:
                eod_mult = mult
        effective_cap = int(effective_cap * eod_mult)

        # After 90% of day (eod_mult <= 0.50): no new buys, only hold/sell
        eod_no_new_buys = tick >= 9000

        # ── SHIELD 4: Drawdown cap reduction ─────────────────────────────
        pp_cpnl = self.history.get(f"{PEPPER}_cpnl", 0.0)
        pp_hwm = self.history.get(f"{PEPPER}_hwm", 0.0)
        if pp_hwm - pp_cpnl > self.PEPPER_DD_THRESHOLD:
            effective_cap = int(effective_cap * 0.5)

        # ── SHIELD 3: Linreg-smoothed slope stop ─────────────────────────
        # Stop thresholds use regime_cap (market-driven), not effective_cap
        if regime_cap >= self.PEPPER_CAP_STRONG:
            stop_th, resume_th = self.PEPPER_STOP_STRONG, self.PEPPER_RESUME_STRONG
        elif regime_cap <= self.PEPPER_CAP_WEAK and regime_cap > 0:
            stop_th, resume_th = self.PEPPER_STOP_WEAK, self.PEPPER_RESUME_WEAK
        else:
            stop_th, resume_th = self.PEPPER_STOP_MODERATE, self.PEPPER_RESUME_MODERATE

        breach = int(self.history.get("pp_breach", 0))
        stopped = bool(self.history.get("pp_stopped", False))

        if len(hist) >= 20:
            # Peter v100: linreg slope × 19 ≈ same units as hist[-1]-hist[-20]
            # but is smoother — avoids single-tick spikes triggering false stops
            local_slope = _linreg_slope(hist[-20:]) * 19
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

        # ── Case A: Stopped or cap=0 → orderly exit (20/tick) ────────────
        if stopped or effective_cap == 0:
            if pos > 0:
                dump = min(pos, 20)
                avail = depth.buy_orders.get(bb, 0)
                qty = max(0, min(dump, avail))
                if qty > 0:
                    orders.append(Order(PEPPER, bb, -qty))
            return orders

        # ── Case B: Position exceeds reduced cap → sell excess ────────────
        if pos > effective_cap:
            excess = pos - effective_cap
            sell_qty = max(0, min(excess, 20))
            if sell_qty > 0:
                avail = depth.buy_orders.get(bb, 0)
                qty = max(0, min(sell_qty, avail))
                if qty > 0:
                    orders.append(Order(PEPPER, bb, -qty))
            return orders

        # ── Case C: Normal — accumulate toward cap (if EOD allows) ────────
        rem_cap = max(0, effective_cap - pos)
        take_limit = (self.PEPPER_TAKE_STRONG if effective_cap >= self.PEPPER_CAP_STRONG
                      else self.PEPPER_TAKE_NORMAL)

        if rem_cap > 0 and not eod_no_new_buys:
            budget = min(rem_cap, take_limit)
            for ask in sorted(depth.sell_orders.keys()):
                if budget <= 0:
                    break
                if ask <= mid + self.PEPPER_TAKE_CROSS_EDGE:
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

        # ── De-risk when overloaded and spread widens ─────────────────────
        if spread_widening and pos > effective_cap * self.PEPPER_DERISK_THRESHOLD:
            sell_qty = max(0, min(pos, self.PEPPER_DERISK_QTY))
            if sell_qty > 0:
                orders.append(Order(PEPPER, ba - 1, -sell_qty))

        return orders

    # ══════════════════════════════════════════════════════════════════════
    # ASH-COATED OSMIUM  (AR(3) fair + Multi-VWAP + Flow Skew + Titan)
    # ══════════════════════════════════════════════════════════════════════
    def _osmium_logic(self, state: TradingState) -> List[Order]:
        if OSMIUM not in state.order_depths:
            return []
        depth = state.order_depths[OSMIUM]
        pos = state.position.get(OSMIUM, 0)
        bb, ba = self._best_bid_ask(depth)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0

        # Track mid history for crash detection (shared state key)
        hist = self.history[f"{OSMIUM}_mid_hist"]
        hist.append(mid)
        if len(hist) > 60:
            hist = hist[-60:]
        self.history[f"{OSMIUM}_mid_hist"] = hist

        # Note: NO Titan Shield for Osmium. Osmium is mean-reverting around
        # 10,000 — drawdowns are normal oscillation and recover naturally.
        # Titan Shield would prematurely kill the strategy.

        # ── Multi-level VWAP fair value (Peter v101) ──────────────────────
        bid_items = sorted(depth.buy_orders.items(), reverse=True)[:self.OSMIUM_VWAP_LEVELS]
        ask_items = sorted(depth.sell_orders.items())[:self.OSMIUM_VWAP_LEVELS]
        bid_vol = sum(v for _, v in bid_items)
        ask_vol = sum(-v for _, v in ask_items)
        if bid_vol > 0 and ask_vol > 0:
            vwap_bid = sum(p * v for p, v in bid_items) / bid_vol
            vwap_ask = sum(p * (-v) for p, v in ask_items) / ask_vol
            vwap_mid = (vwap_bid + vwap_ask) / 2.0
        else:
            vwap_mid = mid

        fair_fallback = self.OSMIUM_VWAP_WEIGHT * vwap_mid + (1 - self.OSMIUM_VWAP_WEIGHT) * self.OSMIUM_ANCHOR

        # ── AR(3) predictor (Ken v4) blended with VWAP fallback ───────────
        ar3_pred = self._osmium_ar3_predict(mid, fair_fallback)
        if self.history.get("op_ar3_fitted", False):
            fair = self.OSMIUM_AR3_BLEND * ar3_pred + (1 - self.OSMIUM_AR3_BLEND) * fair_fallback
        else:
            fair = fair_fallback

        # ── EMA smoothing (5-tick) ────────────────────────────────────────
        op_hist = self.history["op_fair_hist"]
        op_hist.append(fair)
        if len(op_hist) > 30:
            op_hist = op_hist[-30:]
        self.history["op_fair_hist"] = op_hist
        if len(op_hist) >= 5:
            fair = 0.6 * fair + 0.4 * (sum(op_hist[-5:]) / 5.0)

        # ── Toxicity + flow imbalance ─────────────────────────────────────
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

        # ── Flow skew: lean quotes into sub-toxic active flow (Peter v101) ──
        flow_skew = 0
        if imbalance >= self.OSMIUM_FLOW_SKEW_THRESHOLD and not toxic_buys:
            flow_skew = 1     # buyers active → sell more into demand
        elif imbalance <= -self.OSMIUM_FLOW_SKEW_THRESHOLD and not toxic_sells:
            flow_skew = -1    # sellers active → buy more from supply

        orders: List[Order] = []
        rb = max(0, self.LIMIT - pos)
        rs = max(0, self.LIMIT + pos)

        # ── Hard flatten circuit-breaker: |pos| > 58 → target 50 ─────────
        if pos > self.OSMIUM_FLATTEN_HARD and rs > 0:
            flatten = max(0, min(pos - self.OSMIUM_FLATTEN_TARGET + 5, rs))
            if flatten > 0:
                orders.append(Order(OSMIUM, int(fair), -flatten))
                rs -= flatten
                pos -= flatten
        elif pos < -self.OSMIUM_FLATTEN_HARD and rb > 0:
            flatten = max(0, min(-pos - self.OSMIUM_FLATTEN_TARGET + 5, rb))
            if flatten > 0:
                orders.append(Order(OSMIUM, int(fair), flatten))
                rb -= flatten    # BUG FIX: was rb += in Holy Grail (Peter v101 catch)
                pos += flatten

        # ── Liquidity taking: NO toxicity gate (Ken v4 insight) ───────────
        # Toxic flow usually means market moved in our favor → take it.
        buy_edge = min(self.OSMIUM_TAKE_EDGE_MAX,
                       self.OSMIUM_TAKE_EDGE + max(0, pos // self.OSMIUM_EDGE_POS_STEP))
        sell_edge = min(self.OSMIUM_TAKE_EDGE_MAX,
                        self.OSMIUM_TAKE_EDGE + max(0, (-pos) // self.OSMIUM_EDGE_POS_STEP))

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

        # ── Market making: position skew + flow skew + clamped quotes ─────
        total_skew = int(pos / self.OSMIUM_SKEW_SOFT) + flow_skew

        bp = int(min(bb + 1, fair - 1)) - total_skew
        ap = int(max(ba - 1, fair + 1)) - total_skew

        clamp = self.OSMIUM_SPREAD_CLAMP
        bp = max(bp, int(fair) - clamp)
        ap = min(ap, int(fair) + clamp)

        if pos > self.OSMIUM_SKEW_HARD:
            bp -= 1
        if pos < -self.OSMIUM_SKEW_HARD:
            ap += 1

        if bp >= ap:
            bp = int(fair) - 1
            ap = int(fair) + 1

        # Size scaling — shrink only when drift is far from anchor
        anchor_drift = abs(fair - self.OSMIUM_ANCHOR)
        size_scale = (max(0.5, 1.0 - (anchor_drift - self.OSMIUM_DRIFT_SCALE_AT) / 20.0)
                      if anchor_drift > self.OSMIUM_DRIFT_SCALE_AT else 1.0)
        front  = max(6, int(self.OSMIUM_QUOTE_FRONT  * size_scale))
        second = max(4, int(self.OSMIUM_QUOTE_SECOND * size_scale))

        # Passive MM — suppress only on genuinely toxic flow side
        if rb > 0 and not toxic_buys:
            q = max(0, min(rb, front))
            if q > 0:
                orders.append(Order(OSMIUM, bp, q))
                rb -= q
            if rb > 0:
                q2 = max(0, min(rb, second))
                if q2 > 0:
                    orders.append(Order(OSMIUM, bp - 1, q2))

        if rs > 0 and not toxic_sells:
            q = max(0, min(rs, front))
            if q > 0:
                orders.append(Order(OSMIUM, ap, -q))
                rs -= q
            if rs > 0:
                q2 = max(0, min(rs, second))
                if q2 > 0:
                    orders.append(Order(OSMIUM, ap + 1, -q2))

        return orders

    # ══════════════════════════════════════════════════════════════════════
    # ENTRY POINT
    # ══════════════════════════════════════════════════════════════════════
    def run(self, state: TradingState):
        self._load_state(state)
        self.history["tick"] = self.history.get("tick", 0) + 1

        result: Dict[str, List[Order]] = {}

        pep = self._pepper_logic(state)
        if pep:
            result[PEPPER] = pep

        osm = self._osmium_logic(state)
        if osm:
            result[OSMIUM] = osm

        return result, 0, self._save_state()
