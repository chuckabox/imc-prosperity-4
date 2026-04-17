"""
trader_robust_ken_v6b.py
========================
V6b — balanced: "safe's brain, agg's ambition"

Design targets (vs v6_safe / v6_agg, live portal estimates):
- Eliminate the initial entry-cost dip v6_agg had (~-$560 spent crossing
  the spread on 80 Pepper units in tick 1).
- Keep the slope-guard so reversed-drift days don't blow the round.
- Size Osmium between safe and agg to squeeze more from the 16-tick spread.
- Expected live PnL/day: ~$7-9k (vs safe ~$6k, agg ~$10k with tail risk).

Pepper logic — "drift confirmation" style:
- Cap 60 (between safe 40 and agg 80).
- Gradual accumulation: add at most PEPPER_ADD_PER_TICK = 5 units per call,
  so fully loading from 0 → 60 takes ~12 ticks instead of 1. This spreads
  entry cost from $560 to ~$50.
- Prefer passive re-bid at best_bid+1 over crossing the spread (cheaper
  fills, matches the 98%-up-over-50-ticks drift).
- Only cross the ask when it sits at or below current_mid (same as safe).
- Slope guard identical to safe (5 consecutive negative 20-tick slopes →
  flatten and stop).

Osmium logic — "moderate Resin MM":
- Same hard 10,000 anchor as safe/agg.
- Take-edge 1 tick (agg-style — the anchor is rock-solid).
- Quote sizes: 25 front / 18 second (between safe 20/15 and agg 30/20).
- Inventory skew starts at |pos| > 30 (between safe 40 and agg 20).
"""

import json
import math
from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState, Symbol


class Trader:
    LIMIT = 80

    PEPPER_MAX_LONG = 60
    PEPPER_ADD_PER_TICK = 10
    PEPPER_SLOPE_WINDOW = 20
    PEPPER_SLOPE_STOP_TICKS = 5

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

        neg_streak = self.history.get("pp_neg_streak", 0)
        stopped = bool(self.history.get("pp_stopped", False))

        if len(hist) >= self.PEPPER_SLOPE_WINDOW:
            window = hist[-self.PEPPER_SLOPE_WINDOW :]
            slope = window[-1] - window[0]
            if slope < 0:
                neg_streak += 1
            else:
                neg_streak = 0

        if neg_streak >= self.PEPPER_SLOPE_STOP_TICKS:
            stopped = True

        self.history["pp_neg_streak"] = neg_streak
        self.history["pp_stopped"] = stopped

        orders: List[Order] = []

        if stopped:
            if pos > 0:
                qty = min(pos, depth.buy_orders.get(bb, 0))
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        rem_cap = self.PEPPER_MAX_LONG - pos
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
