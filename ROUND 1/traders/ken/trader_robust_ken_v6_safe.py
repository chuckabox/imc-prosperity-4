"""
trader_robust_ken_v6_safe.py
============================
V6 SAFE — pattern-aware, robust-max.

Grounded in the Round 1 pattern analysis
(see ROUND 1/docs/round1_pattern_analysis.md):

- INTARIAN_PEPPER_ROOT has a deterministic upward drift of ~+$1,000/day on
  the 3 IMC days (100% up in 200-tick windows). Market-making both sides of
  this is structurally losing; the right play is to accumulate long and
  hold. We cap at +40 and install a cheap slope-guard so that a reversed-
  drift scenario cannot blow us up.

- ASH_COATED_OSMIUM behaves like Prosperity 3's Rainforest Resin: std ~4,
  median spread 16, hard anchor at 10,000. Best play is Timo-Diehm-style
  market making anchored on 10,000 — take inside the anchor, post passive
  quotes just inside the book (never crossing 10,000), flatten at the
  anchor when inventory is large.
"""

import json
import math
from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState, Symbol


class Trader:
    LIMIT = 80

    PEPPER_MAX_LONG = 40
    PEPPER_SLOPE_WINDOW = 20
    PEPPER_SLOPE_STOP_TICKS = 5

    OSMIUM_ANCHOR = 10_000
    OSMIUM_TAKE_EDGE = 2
    OSMIUM_QUOTE_SIZE = 20
    OSMIUM_SECOND_SIZE = 15
    OSMIUM_SKEW_START = 40
    OSMIUM_FLATTEN = 60

    def __init__(self):
        self.history: Dict[str, list] = {}

    def _load_state(self, state: TradingState):
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}

    # ------------------------------------------------------------------
    # PEPPER_ROOT — capped long accumulator with slope guard
    # ------------------------------------------------------------------
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

        hist = self.history.get("pp", [])
        hist.append(mid)
        if len(hist) > 60:
            hist = hist[-60:]
        self.history["pp"] = hist

        neg_slope_streak = self.history.get("pp_neg_streak", 0)
        drift_stopped = bool(self.history.get("pp_stopped", False))

        if len(hist) >= self.PEPPER_SLOPE_WINDOW:
            window = hist[-self.PEPPER_SLOPE_WINDOW :]
            slope = window[-1] - window[0]
            if slope < 0:
                neg_slope_streak += 1
            else:
                neg_slope_streak = 0

        if neg_slope_streak >= self.PEPPER_SLOPE_STOP_TICKS:
            drift_stopped = True

        self.history["pp_neg_streak"] = neg_slope_streak
        self.history["pp_stopped"] = drift_stopped

        orders: List[Order] = []

        if drift_stopped:
            if pos > 0:
                qty = min(pos, depth.buy_orders.get(bb, 0))
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        rem_cap = self.PEPPER_MAX_LONG - pos
        if rem_cap <= 0:
            return orders

        for ask in sorted(depth.sell_orders.keys()):
            if rem_cap <= 0:
                break
            avail = -depth.sell_orders[ask]
            if avail <= 0:
                continue
            if ask <= mid + 1:
                qty = min(rem_cap, avail)
                orders.append(Order(product, ask, qty))
                rem_cap -= qty

        if rem_cap > 0:
            orders.append(Order(product, bb + 1, rem_cap))

        return orders

    # ------------------------------------------------------------------
    # OSMIUM — Resin-style market making around 10,000
    # ------------------------------------------------------------------
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
