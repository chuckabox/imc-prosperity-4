"""
trader_ken_v2_agg.py
====================
Round 2 — AGG variant. Target: mean PnL >= $110k/day on IMC data, blowup < 5%.

Shares architecture with trader_ken_v2_safe.py but:
  * PEPPER_CAP = 80 (full limit).
  * Takes up to mid+2, passive size 40 at bb+1.
  * Softer crash z threshold (-3.0 vs -2.5), partial liquidation on fire.
  * OSMIUM take edge 1 (one tick tighter), front-quote size 30.
  * OBI nudge on OSMIUM: shifts fair +/- 2 when bv/av imbalance > 1.5.
  * bid() = 20 to contest median plus buffer.
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
    GLOBAL_PNL_STOP = -8000.0      # looser than safe
    PRODUCT_TRAIL = 4000.0
    HWM_RECOVER_MARGIN = 1000.0

    # ---------------- Crash shield ----------------
    CRASH_WINDOW = 20
    CRASH_Z_STOP = -3.0            # softer trigger than safe (-2.5)
    CRASH_Z_RESUME = 0.5
    CRASH_MIN_HIST = 30
    CRASH_LOCKOUT_TICKS = 150
    CRASH_PARTIAL_FRACTION = 0.5   # dump 50% first, trail the rest

    # ---------------- Pepper (drift-gated, bidirectional) ----------------
    # Same target logic as safe but can go SHORT on confirmed negative drift.
    # If Pepper crashes, we're short and profit; if it drifts up, we're long.
    PEPPER_CAP = 80                # full limit
    PEPPER_HIST_SHORT = 10
    PEPPER_HIST_LONG = 45
    PEPPER_DRIFT_STRONG = 0.30
    PEPPER_DRIFT_MODERATE = 0.10
    PEPPER_DRIFT_WEAK = 0.03
    PEPPER_TAKE_EDGE = 2           # buy at ask <= mid + 2 (wider take)
    PEPPER_PASSIVE_SIZE = 40       # larger leapfrog
    PEPPER_TAKE_PER_TICK = 20      # faster accumulation per tick
    PEPPER_DESTOCK_PER_TICK = 20

    # ---------------- Osmium ----------------
    OSMIUM_ANCHOR = 10_000
    OSMIUM_TAKE_EDGE = 1           # take closer to anchor (tighter)
    OSMIUM_QUOTE_SIZE_L1 = 30      # larger front quote
    OSMIUM_QUOTE_SIZE_L2 = 20
    OSMIUM_SKEW_START = 20         # skew earlier
    OSMIUM_FLATTEN = 55
    OSMIUM_OBI_RATIO = 1.5         # imbalance ratio triggers nudge
    OSMIUM_OBI_NUDGE = 2           # ticks
    OSMIUM_OBI_MAX_NUDGE = 2       # cap fair deviation from anchor (agg: anchor +/- 2)

    def __init__(self):
        self.history: Dict[str, Any] = {}

    def bid(self) -> int:
        return 20

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
        self.history.setdefault("gl_pnl", 0.0)
        self.history.setdefault("gl_killed", False)
        self.history.setdefault("start_ts", None)

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
    # PnL tracking + Titan shield
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
    def _liquidate(product: str, pos: int, bb: int, ba: int) -> List[Order]:
        if pos > 0 and bb is not None:
            return [Order(product, bb, -pos)]
        if pos < 0 and ba is not None:
            return [Order(product, ba, -pos)]
        return []

    # ------------------------------------------------------------------
    # Crash detector
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

    def _crash_shield(self, product: str, hist: list, ts: int) -> bool:
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
    # Pepper drift + target helpers
    # ------------------------------------------------------------------
    def _pepper_drift(self, hist: list) -> float:
        if len(hist) < self.PEPPER_HIST_LONG:
            return 0.0
        recent = sum(hist[-self.PEPPER_HIST_SHORT:]) / self.PEPPER_HIST_SHORT
        baseline = sum(hist[-self.PEPPER_HIST_LONG:]) / self.PEPPER_HIST_LONG
        return recent - baseline

    # Agg variant: BIDIRECTIONAL. Short on confirmed negative drift.
    def _pepper_target(self, drift: float) -> int:
        if drift > self.PEPPER_DRIFT_STRONG:
            return self.PEPPER_CAP
        if drift > self.PEPPER_DRIFT_MODERATE:
            return self.PEPPER_CAP // 2
        if drift < -self.PEPPER_DRIFT_STRONG:
            return -self.PEPPER_CAP
        if drift < -self.PEPPER_DRIFT_MODERATE:
            return -(self.PEPPER_CAP // 2)
        if drift > self.PEPPER_DRIFT_WEAK:
            return self.PEPPER_CAP // 4
        if drift < -self.PEPPER_DRIFT_WEAK:
            return -(self.PEPPER_CAP // 4)
        return 0

    # ------------------------------------------------------------------
    # PEPPER_ROOT — bidirectional drift-gated accumulator
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
        ts = state.timestamp

        hist = self.history[f"{PEPPER}_mid_hist"]
        hist.append(mid)
        if len(hist) > 250:
            hist = hist[-250:]
        self.history[f"{PEPPER}_mid_hist"] = hist

        self._update_pnl_tracking(PEPPER, pos, mid)

        if self._titan_fire(PEPPER):
            return self._liquidate(PEPPER, pos, bb, ba)

        if self._crash_shield(PEPPER, hist, ts):
            # Scale-free emergency: dump a partial slice so remaining inventory
            # is trailed down over subsequent ticks (avoids selling the bottom).
            if pos > 0:
                dump_qty = max(1, int(pos * self.CRASH_PARTIAL_FRACTION))
                return [Order(PEPPER, bb, -dump_qty)]
            if pos < 0:
                # Don't add to short mid-crash (likely near-bottom)
                return []
            return []

        drift = self._pepper_drift(hist)
        target = self._pepper_target(drift)
        rem = target - pos
        orders: List[Order] = []

        if rem > 0:
            take_budget = min(rem, self.PEPPER_TAKE_PER_TICK)
            for ask in sorted(depth.sell_orders.keys()):
                if take_budget <= 0:
                    break
                avail = -depth.sell_orders[ask]
                if avail <= 0:
                    continue
                if ask <= mid + self.PEPPER_TAKE_EDGE:
                    qty = max(0, min(take_budget, avail))
                    if qty > 0:
                        orders.append(Order(PEPPER, ask, qty))
                        take_budget -= qty
                        rem -= qty
            if rem > 0:
                passive_qty = max(0, min(rem, self.PEPPER_PASSIVE_SIZE))
                if passive_qty > 0:
                    orders.append(Order(PEPPER, bb + 1, passive_qty))

        elif rem < 0:
            sell_budget = min(-rem, self.PEPPER_DESTOCK_PER_TICK)
            for bid_p in sorted(depth.buy_orders.keys(), reverse=True):
                if sell_budget <= 0:
                    break
                avail = depth.buy_orders[bid_p]
                if avail <= 0:
                    continue
                if bid_p >= mid - self.PEPPER_TAKE_EDGE:
                    qty = max(0, min(sell_budget, avail))
                    if qty > 0:
                        orders.append(Order(PEPPER, bid_p, -qty))
                        sell_budget -= qty
                        rem += qty
            if rem < 0:
                passive_qty = max(0, min(-rem, self.PEPPER_PASSIVE_SIZE))
                if passive_qty > 0:
                    orders.append(Order(PEPPER, ba - 1, -passive_qty))

        return orders

    # ------------------------------------------------------------------
    # OSMIUM — anchored MM with mild OBI nudge
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

        hist = self.history[f"{OSMIUM}_mid_hist"]
        hist.append(mid)
        if len(hist) > 100:
            hist = hist[-100:]
        self.history[f"{OSMIUM}_mid_hist"] = hist

        self._update_pnl_tracking(OSMIUM, pos, mid)

        if self._titan_fire(OSMIUM):
            return self._liquidate(OSMIUM, pos, bb, ba)

        # Mild OBI nudge, bounded to anchor +/- OBI_MAX_NUDGE
        bv = sum(depth.buy_orders.values())
        av = sum(-v for v in depth.sell_orders.values())
        nudge = 0
        if av > 0 and bv / max(av, 1) > self.OSMIUM_OBI_RATIO:
            nudge = +self.OSMIUM_OBI_NUDGE
        elif bv > 0 and av / max(bv, 1) > self.OSMIUM_OBI_RATIO:
            nudge = -self.OSMIUM_OBI_NUDGE
        nudge = max(-self.OSMIUM_OBI_MAX_NUDGE, min(self.OSMIUM_OBI_MAX_NUDGE, nudge))
        fair = self.OSMIUM_ANCHOR + nudge

        orders: List[Order] = []
        rem_buy = max(0, self.LIMIT - pos)
        rem_sell = max(0, self.LIMIT + pos)

        # --- Take (anchor-tight) ---
        for ask in sorted(depth.sell_orders.keys()):
            if rem_buy <= 0:
                break
            if ask <= fair - self.OSMIUM_TAKE_EDGE:
                avail = -depth.sell_orders[ask]
                qty = max(0, min(rem_buy, avail))
                if qty > 0:
                    orders.append(Order(OSMIUM, ask, qty))
                    rem_buy -= qty
                    pos += qty

        for bid_p in sorted(depth.buy_orders.keys(), reverse=True):
            if rem_sell <= 0:
                break
            if bid_p >= fair + self.OSMIUM_TAKE_EDGE:
                avail = depth.buy_orders[bid_p]
                qty = max(0, min(rem_sell, avail))
                if qty > 0:
                    orders.append(Order(OSMIUM, bid_p, -qty))
                    rem_sell -= qty
                    pos -= qty

        # --- Flatten large inventory at anchor ---
        if pos > self.OSMIUM_FLATTEN and rem_sell > 0:
            qty = max(0, min(pos - self.OSMIUM_FLATTEN + 5, rem_sell))
            if qty > 0:
                orders.append(Order(OSMIUM, self.OSMIUM_ANCHOR, -qty))
                rem_sell -= qty
                pos -= qty
        elif pos < -self.OSMIUM_FLATTEN and rem_buy > 0:
            qty = max(0, min(-pos - self.OSMIUM_FLATTEN + 5, rem_buy))
            if qty > 0:
                orders.append(Order(OSMIUM, self.OSMIUM_ANCHOR, qty))
                rem_buy -= qty
                pos += qty

        # --- Passive (dual-level) penny inside the anchor ---
        skew = 0
        if abs(pos) > self.OSMIUM_SKEW_START:
            skew = 1 if pos > 0 else -1

        bid_l1 = fair - 1 - (1 if skew > 0 else 0)
        ask_l1 = fair + 1 + (1 if skew < 0 else 0)
        if ba is not None and bid_l1 >= ba:
            bid_l1 = ba - 1
        if bb is not None and ask_l1 <= bb:
            ask_l1 = bb + 1
        if bid_l1 >= ask_l1:
            bid_l1 = fair - 1
            ask_l1 = fair + 1

        if rem_buy > 0:
            front = max(0, min(rem_buy, self.OSMIUM_QUOTE_SIZE_L1))
            if front > 0:
                orders.append(Order(OSMIUM, int(bid_l1), front))
                rem_buy -= front
            if rem_buy > 0 and bid_l1 - 1 < ask_l1:
                second = max(0, min(rem_buy, self.OSMIUM_QUOTE_SIZE_L2))
                if second > 0:
                    orders.append(Order(OSMIUM, int(bid_l1 - 1), second))

        if rem_sell > 0:
            front = max(0, min(rem_sell, self.OSMIUM_QUOTE_SIZE_L1))
            if front > 0:
                orders.append(Order(OSMIUM, int(ask_l1), -front))
                rem_sell -= front
            if rem_sell > 0 and ask_l1 + 1 > bid_l1:
                second = max(0, min(rem_sell, self.OSMIUM_QUOTE_SIZE_L2))
                if second > 0:
                    orders.append(Order(OSMIUM, int(ask_l1 + 1), -second))

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
