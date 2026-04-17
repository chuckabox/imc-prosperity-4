"""
trader_robust_ken_v6c.py
========================
V6c — drift-adaptive ("smart safe")

Difference vs v6_safe / v6b / v6_agg:
  All three prior variants hardcode the Pepper cap (40 / 60 / 80).
  v6c *measures* the realized drift during a 2,000-tick warmup, then
  picks the cap that matches the regime it actually sees.

  - Strong up-drift  (slope > 0.5 ticks/step)  -> cap 80 (agg-equivalent)
  - Moderate drift   (0.2 - 0.5)               -> cap 60 (v6b)
  - Weak / noise     (-0.2 - 0.2)              -> cap 30 (mostly Osmium)
  - Negative drift   (< -0.2)                  -> cap  0 (flatten, trade Osmium only)

  The slope guard (5 consecutive negative 20-tick slopes) still runs AFTER
  warmup in case a trending day turns mid-session.

Osmium logic identical to v6b: hard 10,000 anchor, 1-tick take edge, 25/18
quote sizes, inventory skew starts at |pos|>30, flatten at |pos|>60.

Why this beats v6b:
  - On days like the 3 IMC samples (drift ~1.08 ticks/step) v6c will auto-
    upgrade to cap 80 -> captures full agg upside.
  - On a drift-nerfed live day v6c auto-downgrades -> no forced directional
    loss, keeps Osmium income.
  - On a reversed-drift live day v6c goes to cap 0 at tick 2000 AND still
    has the slope-guard as a late-stage tripwire.
"""

import json
import math
from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState, Symbol


class Trader:
    LIMIT = 80

    PEPPER_WARMUP_TICKS = 2000
    PEPPER_ADD_PER_TICK = 10
    PEPPER_SLOPE_WINDOW = 20
    PEPPER_SLOPE_STOP_TICKS = 5

    # thresholds on measured slope (price delta per 100 timestamp units).
    # IMC days have drift ~1000 ticks per ~1e6 timestamps -> slope ~0.1.
    # Calibration: STRONG captures >= ~$600/day expected drift.
    PEPPER_SLOPE_STRONG = 0.06
    PEPPER_SLOPE_MODERATE = 0.02
    PEPPER_SLOPE_WEAK = -0.02

    PEPPER_CAP_STRONG = 80
    PEPPER_CAP_MODERATE = 60
    PEPPER_CAP_WEAK = 30
    PEPPER_CAP_NEGATIVE = 0

    OSMIUM_ANCHOR = 10_000
    OSMIUM_TAKE_EDGE = 1
    OSMIUM_QUOTE_SIZE = 25
    OSMIUM_SECOND_SIZE = 18
    OSMIUM_SKEW_START = 30
    OSMIUM_FLATTEN = 60

    def __init__(self):
        self.history: Dict[str, list] = {}

    def _load_state(self, state: TradingState):
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}

    def _pick_pepper_cap(self, slope: float) -> int:
        if slope > self.PEPPER_SLOPE_STRONG:
            return self.PEPPER_CAP_STRONG
        if slope > self.PEPPER_SLOPE_MODERATE:
            return self.PEPPER_CAP_MODERATE
        if slope > self.PEPPER_SLOPE_WEAK:
            return self.PEPPER_CAP_WEAK
        return self.PEPPER_CAP_NEGATIVE

    def _pepper_logic(self, state: TradingState) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)

        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        ts = state.timestamp

        hist = self.history.get("pp", [])
        hist.append(mid)
        if len(hist) > 60:
            hist = hist[-60:]
        self.history["pp"] = hist

        if "pp_start_mid" not in self.history:
            self.history["pp_start_mid"] = mid
            self.history["pp_start_ts"] = ts

        cap = self.history.get("pp_cap", None)
        start_mid = self.history.get("pp_start_mid", mid)
        start_ts = self.history.get("pp_start_ts", ts)

        if cap is None and (ts - start_ts) >= self.PEPPER_WARMUP_TICKS:
            elapsed = max(1, ts - start_ts)
            slope = (mid - start_mid) / elapsed * 100.0
            cap = self._pick_pepper_cap(slope)
            self.history["pp_cap"] = cap
            self.history["pp_measured_slope"] = slope

        effective_cap = cap if cap is not None else min(self.PEPPER_CAP_MODERATE, 20)

        neg_streak = self.history.get("pp_neg_streak", 0)
        stopped = bool(self.history.get("pp_stopped", False))

        if len(hist) >= self.PEPPER_SLOPE_WINDOW:
            window = hist[-self.PEPPER_SLOPE_WINDOW :]
            slope_w = window[-1] - window[0]
            if slope_w < 0:
                neg_streak += 1
            else:
                neg_streak = 0
        if neg_streak >= self.PEPPER_SLOPE_STOP_TICKS:
            stopped = True
        self.history["pp_neg_streak"] = neg_streak
        self.history["pp_stopped"] = stopped

        orders: List[Order] = []

        if stopped or effective_cap == 0:
            if pos > 0:
                qty = min(pos, depth.buy_orders.get(bb, 0))
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        rem_cap = effective_cap - pos
        if rem_cap <= 0:
            return orders

        tick_budget = min(rem_cap, self.PEPPER_ADD_PER_TICK)

        for ask in sorted(depth.sell_orders.keys()):
            if tick_budget <= 0:
                break
            avail = -depth.sell_orders[ask]
            if avail <= 0:
                continue
            if ask <= mid + 1:
                qty = min(tick_budget, avail)
                orders.append(Order(product, ask, qty))
                tick_budget -= qty

        if tick_budget > 0:
            orders.append(Order(product, bb + 1, tick_budget))

        return orders

    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)

        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None:
            return []

        fair = self.OSMIUM_ANCHOR

        orders: List[Order] = []
        rem_buy = self.LIMIT - pos
        rem_sell = self.LIMIT + pos

        for ask in sorted(depth.sell_orders.keys()):
            if ask <= fair - self.OSMIUM_TAKE_EDGE and rem_buy > 0:
                avail = -depth.sell_orders[ask]
                qty = min(rem_buy, avail)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty
                    pos += qty

        for bid in sorted(depth.buy_orders.keys(), reverse=True):
            if bid >= fair + self.OSMIUM_TAKE_EDGE and rem_sell > 0:
                avail = depth.buy_orders[bid]
                qty = min(rem_sell, avail)
                if qty > 0:
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty
                    pos -= qty

        if pos > self.OSMIUM_FLATTEN and rem_sell > 0:
            qty = min(pos - self.OSMIUM_FLATTEN + 5, rem_sell)
            if qty > 0:
                orders.append(Order(product, fair, -qty))
                rem_sell -= qty
        elif pos < -self.OSMIUM_FLATTEN and rem_buy > 0:
            qty = min(-pos - self.OSMIUM_FLATTEN + 5, rem_buy)
            if qty > 0:
                orders.append(Order(product, fair, qty))
                rem_buy -= qty

        skew = 0
        if abs(pos) > self.OSMIUM_SKEW_START:
            skew = 1 if pos > 0 else -1

        bid_price = min(bb + 1, fair - 1) - (1 if skew > 0 else 0)
        ask_price = max(ba - 1, fair + 1) + (1 if skew < 0 else 0)

        if bid_price >= ask_price:
            bid_price = fair - 1
            ask_price = fair + 1

        if rem_buy > 0:
            front = min(rem_buy, self.OSMIUM_QUOTE_SIZE)
            orders.append(Order(product, int(bid_price), front))
            rem_buy -= front
            if rem_buy > 0:
                orders.append(
                    Order(product, int(bid_price - 1), min(rem_buy, self.OSMIUM_SECOND_SIZE))
                )

        if rem_sell > 0:
            front = min(rem_sell, self.OSMIUM_QUOTE_SIZE)
            orders.append(Order(product, int(ask_price), -front))
            rem_sell -= front
            if rem_sell > 0:
                orders.append(
                    Order(product, int(ask_price + 1), -min(rem_sell, self.OSMIUM_SECOND_SIZE))
                )

        return orders

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        pep = self._pepper_logic(state)
        if pep:
            result["INTARIAN_PEPPER_ROOT"] = pep

        osm = self._osmium_logic(state)
        if osm:
            result["ASH_COATED_OSMIUM"] = osm

        return result, 0, json.dumps(self.history)
