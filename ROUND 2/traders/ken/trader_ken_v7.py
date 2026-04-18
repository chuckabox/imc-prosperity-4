"""
trader_ken_v7.py — Round 2: Holy_grailllll core + minimal hardening
===================================================================

Core (unchanged from ``Holy_grailllll.py``):
  * Pepper drift regime, raw 20-tick stop slope, caps / takes / passive as Holy.
  * Osmium VWAP fair, 5-tick smooth, ±0.6 OBI fair nudge when |OBI| ≥ 0.3.
  * ``bid()`` = 4_000 (same MAF posture as Holy).

Hardening (surgical, from ken v5/v6 lineage):
  * Per-tick mark-to-market tracking + combined ``gl_pnl`` / per-product ``cpnl``.
  * Titan: global floor + per-product trailing drawdown → liquidate until recovery margin.
  * Pepper z-slope crash override (short lockout) on violent mid path.
  * Pepper base-median sustained drop → orderly sell + long lockout (scenario guard).
  * Mid backfill when one-sided book (keeps ``pp`` / ``op`` buffers alive).
  * Session ``gl_hwm`` bump each ``run()`` for future gated logic (no cap scaling here).

No ken_v6-style boot / EOD / fragile cap multipliers — those stay off to preserve Holy IMC edge.

Implementation note: never ``setdefault("pp_t0", None)`` — ``setdefault("pp_t0", ts)`` would then
return ``None`` (key present), ``elapsed`` becomes invalid, the engine swallows errors, and
almost all ticks are skipped.
"""

import json
import math
from typing import Any, Dict, List

from datamodel import Order, OrderDepth, TradingState


PEPPER = "INTARIAN_PEPPER_ROOT"
OSMIUM = "ASH_COATED_OSMIUM"


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


class Trader:
    LIMIT = 80

    # ---------------- Titan (same rails as ken_v5 / v6) ----------------
    GLOBAL_PNL_STOP = -5000.0
    PRODUCT_TRAIL_PEPPER = 2500.0
    PRODUCT_TRAIL_OSMIUM = 3000.0
    HWM_RECOVER_MARGIN = 500.0

    # Toggle hardening pieces independently when diagnosing / tuning.
    ENABLE_TITAN = True
    ENABLE_Z_CRASH = True
    ENABLE_PEPPER_CRASH_GATE = True

    # ---------------- z-slope crash (Pepper only) ----------------
    CRASH_WINDOW = 20
    CRASH_Z_STOP = -3.0
    CRASH_Z_RESUME = 1.0
    CRASH_MIN_HIST = 30
    CRASH_LOCKOUT_TICKS = 180

    # ---------------- Pepper crash gate ----------------
    PEPPER_CRASH_BASE_DROP = 8
    PEPPER_CRASH_BREACH = 5
    PEPPER_CRASH_LOCKOUT = 400

    # ── PEPPER (Holy_grailllll) ───────────────────────────────────────────
    PEPPER_WARMUP_TICKS = 1200
    PEPPER_FAST_TRACK_TICKS = 200

    PEPPER_SLOPE_STRONG_FAST = 0.05
    PEPPER_SLOPE_STRONG = 0.04
    PEPPER_SLOPE_MODERATE = 0.01
    PEPPER_SLOPE_WEAK = -0.01

    PEPPER_CAP_STRONG = 80
    PEPPER_CAP_MODERATE = 60
    PEPPER_CAP_WEAK = 30
    PEPPER_CAP_NEGATIVE = 0
    PEPPER_CAP_TENTATIVE = 25

    PEPPER_TAKE_STRONG = 32
    PEPPER_TAKE_NORMAL = 18
    PEPPER_PASSIVE_MAX = 65

    PEPPER_STOP_BREACH_COUNT = 3
    PEPPER_STOP_STRONG = -20
    PEPPER_STOP_MODERATE = -10
    PEPPER_STOP_WEAK = -7
    PEPPER_RESUME_STRONG = 5
    PEPPER_RESUME_MODERATE = 5
    PEPPER_RESUME_WEAK = 4

    PEPPER_SPREAD_PASSIVE_SCALE = 0.75
    PEPPER_TAKE_CROSS_EDGE = 2.0

    # ── OSMIUM (Holy_grailllll) ─────────────────────────────────────────────
    OSMIUM_ANCHOR = 10_000

    OSMIUM_TOXICITY_THRESHOLD = 35
    OSMIUM_TAKE_EDGE = 0
    OSMIUM_EDGE_POS_STEP = 30
    OSMIUM_TAKE_EDGE_MAX = 3

    OSMIUM_SKEW_SOFT = 15
    OSMIUM_SKEW_HARD = 35
    OSMIUM_FLATTEN_HARD = 58
    OSMIUM_FLATTEN_TARGET = 50

    OSMIUM_QUOTE_FRONT = 38
    OSMIUM_QUOTE_SECOND = 28

    OSMIUM_SPREAD_CLAMP = 5
    OSMIUM_VWAP_WEIGHT = 0.65
    OSMIUM_DRIFT_SCALE_AT = 8

    def __init__(self):
        self.history: Dict[str, Any] = {}

    def bid(self) -> int:
        return 4_000

    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}

        self.history.setdefault("pp", [])
        self.history.setdefault("pp_base", [])
        self.history.setdefault("op", [])
        self.history.setdefault("pp_breach", 0)
        self.history.setdefault("pp_stopped", False)
        self.history.setdefault("pp_crash_breach", 0)
        self.history.setdefault("pp_crash_lock_until", -1)

        for p in (PEPPER, OSMIUM):
            self.history.setdefault(f"{p}_cpnl", 0.0)
            # hwm: do not default to 0.0 — that makes max(0, cpnl) treat any loss as
            # drawdown from a false peak and trips Titan immediately (see ken_v7 notes).
            self.history.setdefault(f"{p}_killed", False)
            self.history.setdefault(f"{p}_last_mid", None)
            self.history.setdefault(f"{p}_last_pos", 0)
            self.history.setdefault(f"{p}_crash_locked_until", -1)

        self.history.setdefault("gl_pnl", 0.0)
        self.history.setdefault("gl_hwm", 0.0)
        self.history.setdefault("gl_killed", False)

    def _save_state(self) -> str:
        return json.dumps(self.history)

    def _update_pnl_tracking(self, product: str, pos: int, mid: float) -> None:
        last_mid = self.history.get(f"{product}_last_mid")
        last_pos = self.history.get(f"{product}_last_pos", 0)
        if last_mid is not None:
            delta = (mid - last_mid) * last_pos
            self.history[f"{product}_cpnl"] = self.history.get(f"{product}_cpnl", 0.0) + delta
            self.history["gl_pnl"] = self.history.get("gl_pnl", 0.0) + delta
        cpnl = self.history[f"{product}_cpnl"]
        prev_hwm = self.history.get(f"{product}_hwm")
        if prev_hwm is None:
            self.history[f"{product}_hwm"] = cpnl
        else:
            self.history[f"{product}_hwm"] = max(prev_hwm, cpnl)
        self.history[f"{product}_last_mid"] = mid
        self.history[f"{product}_last_pos"] = pos

    def _titan_fire(self, product: str) -> bool:
        if not self.ENABLE_TITAN:
            return False
        if self.history.get("gl_killed", False):
            return True
        if self.history.get("gl_pnl", 0.0) < self.GLOBAL_PNL_STOP:
            self.history["gl_killed"] = True
            return True
        trail = (
            self.PRODUCT_TRAIL_PEPPER if product == PEPPER else self.PRODUCT_TRAIL_OSMIUM
        )
        cpnl = self.history.get(f"{product}_cpnl", 0.0)
        hwm = self.history.get(f"{product}_hwm")
        if hwm is None:
            hwm = cpnl
        if hwm - cpnl > trail:
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

    def _z_slope(self, hist: list) -> float:
        w = self.CRASH_WINDOW
        if len(hist) < w + 1:
            return 0.0
        recent = hist[-(w + 1) :]
        returns = [recent[i + 1] - recent[i] for i in range(w)]
        s = _std(returns)
        if s <= 1e-9:
            return 0.0
        raw_slope = recent[-1] - recent[0]
        return raw_slope / (s * math.sqrt(w))

    def _crash_override(self, product: str, hist: list, ts: int) -> bool:
        if not self.ENABLE_Z_CRASH:
            return False
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

    def _pepper_logic(self, state: TradingState) -> List[Order]:
        if PEPPER not in state.order_depths:
            return []

        depth = state.order_depths[PEPPER]
        pos = state.position.get(PEPPER, 0)

        if not depth.buy_orders or not depth.sell_orders:
            hist = self.history["pp"]
            if hist:
                hist.append(hist[-1])
                if len(hist) > 120:
                    hist = hist[-120:]
                self.history["pp"] = hist
            return []

        bb = max(depth.buy_orders.keys())
        ba = min(depth.sell_orders.keys())
        mid = (bb + ba) / 2.0
        spread = ba - bb
        ts = state.timestamp

        hist = self.history["pp"]
        hist.append(mid)
        if len(hist) > 120:
            hist = hist[-120:]
        self.history["pp"] = hist

        base_samples = self.history["pp_base"]
        if len(base_samples) < 15:
            base_samples.append(mid)
            self.history["pp_base"] = base_samples

        if self.history.get("pp_t0") is None:
            self.history["pp_t0"] = ts
        start_ts = self.history["pp_t0"]

        prev_spread = self.history.get("pp_prev_spread", spread)
        spread_widening = spread > prev_spread
        self.history["pp_prev_spread"] = spread

        elapsed = ts - start_ts
        warmed_up = elapsed >= self.PEPPER_WARMUP_TICKS
        fast_track = elapsed >= self.PEPPER_FAST_TRACK_TICKS

        self._update_pnl_tracking(PEPPER, pos, mid)

        if self._titan_fire(PEPPER):
            return self._liquidate(PEPPER, pos, bb, ba)

        if self._crash_override(PEPPER, hist, ts):
            if pos > 0:
                return [Order(PEPPER, bb, -pos)]
            return []

        if self.ENABLE_PEPPER_CRASH_GATE:
            base_median = _median(base_samples) if len(base_samples) >= 15 else mid
            if warmed_up and (base_median - mid) >= self.PEPPER_CRASH_BASE_DROP:
                self.history["pp_crash_breach"] = int(self.history.get("pp_crash_breach", 0)) + 1
            else:
                self.history["pp_crash_breach"] = 0
            if self.history["pp_crash_breach"] >= self.PEPPER_CRASH_BREACH:
                self.history["pp_crash_lock_until"] = ts + self.PEPPER_CRASH_LOCKOUT
            lock_until = self.history.get("pp_crash_lock_until", -1)
        else:
            lock_until = -1

        if ts < lock_until:
            orders: List[Order] = []
            if pos > 0:
                avail = depth.buy_orders.get(bb, 0)
                qty = max(0, min(pos, 30, avail))
                if qty > 0:
                    orders.append(Order(PEPPER, bb, -qty))
            return orders

        cap = self.history.get("pp_cap", None)

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

            if cap is None:
                cap = new_cap if new_cap is not None else self.PEPPER_CAP_TENTATIVE
            elif new_cap is not None and new_cap > cap:
                cap = new_cap
            elif warmed_up and new_cap is not None and new_cap < cap:
                cap = new_cap

            self.history["pp_cap"] = cap

        effective_cap = cap if cap is not None else self.PEPPER_CAP_TENTATIVE

        if effective_cap == self.PEPPER_CAP_STRONG:
            stop_th, resume_th = self.PEPPER_STOP_STRONG, self.PEPPER_RESUME_STRONG
        elif effective_cap == self.PEPPER_CAP_WEAK:
            stop_th, resume_th = self.PEPPER_STOP_WEAK, self.PEPPER_RESUME_WEAK
        else:
            stop_th, resume_th = self.PEPPER_STOP_MODERATE, self.PEPPER_RESUME_MODERATE

        breach_count = int(self.history.get("pp_breach", 0))
        drift_stopped = bool(self.history.get("pp_stopped", False))

        if len(hist) >= 20:
            local_slope = hist[-1] - hist[-20]
            if local_slope < stop_th:
                breach_count += 1
            else:
                breach_count = 0
            if breach_count >= self.PEPPER_STOP_BREACH_COUNT:
                drift_stopped = True
            elif drift_stopped and local_slope > resume_th:
                drift_stopped = False

        self.history["pp_breach"] = breach_count
        self.history["pp_stopped"] = drift_stopped

        orders: List[Order] = []

        if drift_stopped or effective_cap == 0:
            if pos > 0:
                dump_qty = min(pos, 20)
                avail = depth.buy_orders.get(bb, 0)
                qty = min(dump_qty, avail)
                if qty > 0:
                    orders.append(Order(PEPPER, bb, -qty))
            return orders

        rem_cap = effective_cap - pos
        take_limit = (
            self.PEPPER_TAKE_STRONG
            if effective_cap == self.PEPPER_CAP_STRONG
            else self.PEPPER_TAKE_NORMAL
        )

        if rem_cap > 0:
            budget = min(rem_cap, take_limit)
            for ask in sorted(depth.sell_orders.keys()):
                if budget <= 0:
                    break
                if ask <= mid + self.PEPPER_TAKE_CROSS_EDGE:
                    qty = min(budget, -depth.sell_orders[ask])
                    orders.append(Order(PEPPER, ask, qty))
                    budget -= qty
                    rem_cap -= qty

            if rem_cap > 0:
                passive_qty = min(rem_cap, self.PEPPER_PASSIVE_MAX)
                if spread_widening:
                    passive_qty = int(passive_qty * self.PEPPER_SPREAD_PASSIVE_SCALE)
                if passive_qty > 0:
                    orders.append(Order(PEPPER, bb + 1, passive_qty))

        if spread_widening and pos > effective_cap * 0.6:
            sell_qty = min(pos, 8)
            orders.append(Order(PEPPER, ba - 1, -sell_qty))

        return orders

    def _osmium_logic(self, state: TradingState) -> List[Order]:
        if OSMIUM not in state.order_depths:
            return []

        depth = state.order_depths[OSMIUM]
        pos = state.position.get(OSMIUM, 0)

        if not depth.buy_orders or not depth.sell_orders:
            op = self.history["op"]
            if op:
                op.append(op[-1])
                if len(op) > 30:
                    op = op[-30:]
                self.history["op"] = op
            return []

        bb = max(depth.buy_orders.keys())
        ba = min(depth.sell_orders.keys())
        mid = (bb + ba) / 2.0

        self._update_pnl_tracking(OSMIUM, pos, mid)

        if self._titan_fire(OSMIUM):
            return self._liquidate(OSMIUM, pos, bb, ba)

        bv1 = depth.buy_orders[bb]
        av1 = -depth.sell_orders[ba]
        total_vol = bv1 + av1
        vwap_mid = (bb * av1 + ba * bv1) / total_vol if total_vol > 0 else mid

        fair = self.OSMIUM_VWAP_WEIGHT * vwap_mid + (1 - self.OSMIUM_VWAP_WEIGHT) * self.OSMIUM_ANCHOR

        op = self.history["op"]
        op.append(fair)
        if len(op) > 30:
            op = op[-30:]
        self.history["op"] = op

        if len(op) >= 5:
            fair = 0.6 * fair + 0.4 * (sum(op[-5:]) / 5.0)

        if total_vol > 0:
            obi = (bv1 - av1) / total_vol
            if obi >= 0.3 or obi <= -0.3:
                fair += 0.6 * (1.0 if obi > 0 else -1.0)

        buy_vol = sell_vol = 0
        if OSMIUM in state.market_trades:
            for t in state.market_trades[OSMIUM]:
                if t.price >= mid:
                    buy_vol += abs(t.quantity)
                else:
                    sell_vol += abs(t.quantity)

        imbalance = buy_vol - sell_vol
        toxic_buys = imbalance >= self.OSMIUM_TOXICITY_THRESHOLD
        toxic_sells = imbalance <= -self.OSMIUM_TOXICITY_THRESHOLD

        orders: List[Order] = []
        rb = self.LIMIT - pos
        rs = self.LIMIT + pos

        if pos > self.OSMIUM_FLATTEN_HARD and rs > 0:
            flatten_qty = min(pos - self.OSMIUM_FLATTEN_TARGET + 5, rs)
            orders.append(Order(OSMIUM, int(fair), -flatten_qty))
            rs -= flatten_qty
            pos -= flatten_qty
        elif pos < -self.OSMIUM_FLATTEN_HARD and rb > 0:
            flatten_qty = min(-pos - self.OSMIUM_FLATTEN_TARGET + 5, rb)
            orders.append(Order(OSMIUM, int(fair), flatten_qty))
            rb += flatten_qty
            pos += flatten_qty

        pos_adj_buy = min(
            self.OSMIUM_TAKE_EDGE_MAX,
            self.OSMIUM_TAKE_EDGE + max(0, pos // self.OSMIUM_EDGE_POS_STEP),
        )
        pos_adj_sell = min(
            self.OSMIUM_TAKE_EDGE_MAX,
            self.OSMIUM_TAKE_EDGE + max(0, (-pos) // self.OSMIUM_EDGE_POS_STEP),
        )

        for ask in sorted(depth.sell_orders.keys()):
            if ask <= fair - pos_adj_buy and rb > 0:
                q = min(rb, -depth.sell_orders[ask])
                orders.append(Order(OSMIUM, ask, q))
                rb -= q
                pos += q

        for bid in sorted(depth.buy_orders.keys(), reverse=True):
            if bid >= fair + pos_adj_sell and rs > 0:
                q = min(rs, depth.buy_orders[bid])
                orders.append(Order(OSMIUM, bid, -q))
                rs -= q
                pos -= q

        skew = int(pos / self.OSMIUM_SKEW_SOFT)

        bp = int(min(bb + 1, fair - 1)) - skew
        ap = int(max(ba - 1, fair + 1)) - skew

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

        anchor_drift = abs(fair - self.OSMIUM_ANCHOR)
        size_scale = (
            max(0.5, 1.0 - (anchor_drift - self.OSMIUM_DRIFT_SCALE_AT) / 20.0)
            if anchor_drift > self.OSMIUM_DRIFT_SCALE_AT
            else 1.0
        )

        front = max(6, int(self.OSMIUM_QUOTE_FRONT * size_scale))
        second = max(4, int(self.OSMIUM_QUOTE_SECOND * size_scale))

        if rb > 0 and not toxic_buys:
            q = min(rb, front)
            orders.append(Order(OSMIUM, bp, q))
            rb -= q
            if rb > 0:
                orders.append(Order(OSMIUM, bp - 1, min(rb, second)))

        if rs > 0 and not toxic_sells:
            q = min(rs, front)
            orders.append(Order(OSMIUM, ap, -q))
            rs -= q
            if rs > 0:
                orders.append(Order(OSMIUM, ap + 1, -min(rs, second)))

        return orders

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        pep = self._pepper_logic(state)
        if pep:
            result[PEPPER] = pep

        osm = self._osmium_logic(state)
        if osm:
            result[OSMIUM] = osm

        gl = self.history.get("gl_pnl", 0.0)
        self.history["gl_hwm"] = max(self.history.get("gl_hwm", gl), gl)

        return result, 0, self._save_state()
