"""
trader_robust_ken_v6_agg.py
===========================
V6 AGG — pattern-aware, IMC-max.

Same thesis as v6_safe (see ROUND 1/docs/round1_pattern_analysis.md):
  PEPPER_ROOT drifts deterministically up by ~$1k/day,
  OSMIUM is anchored at 10,000 with a ~16-tick spread.

The aggressive variant goes all-in on both:
  - Pepper: go to +80 long ASAP, NEVER sell. Ride the drift.
  - Osmium: tighter take-edge (1 tick vs anchor), bigger quote sizes,
    earlier inventory skew.

Designed to maximize mean PnL on the 3 IMC days. Accepts scenario-category
blow-ups as the cost of the pattern bet.
"""

import json
import math
from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState, Symbol


class Trader:
    LIMIT = 80

    PEPPER_MAX_LONG = 80

    OSMIUM_ANCHOR = 10_000
    OSMIUM_TAKE_EDGE = 1
    OSMIUM_QUOTE_SIZE = 30
    OSMIUM_SECOND_SIZE = 20
    OSMIUM_SKEW_START = 20
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
    # PEPPER_ROOT — ride the drift, max long, never sell
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

        rem_cap = self.PEPPER_MAX_LONG - pos
        if rem_cap <= 0:
            return []

        orders: List[Order] = []

        for ask in sorted(depth.sell_orders.keys()):
            if rem_cap <= 0:
                break
            avail = -depth.sell_orders[ask]
            if avail <= 0:
                continue
            qty = min(rem_cap, avail)
            orders.append(Order(product, ask, qty))
            rem_cap -= qty

        if rem_cap > 0:
            orders.append(Order(product, bb + 1, rem_cap))

        return orders

    # ------------------------------------------------------------------
    # OSMIUM — aggressive Resin-style market making around 10,000
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
