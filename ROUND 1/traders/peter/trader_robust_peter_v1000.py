"""
trader_robust_peter_v1000.py
============================
Robustness-first. Smooth equity over peak returns.

One-sentence logic:
  Buy pepper on drift (magnitude slope guard, recovery allowed);
  market-make osmium at anchor 10k with early graduated skew and tight inventory.

Changes from v6_safe:
  PEPPER: magnitude-based stop (not streak), recovery, tighter take, capped passive
  OSMIUM: take_edge 2->3, quote sizes smaller, skew starts at 25 (not 40),
          graduated 2-tick skew at pos>50, full-spread shift, flatten at 55
"""

import json
from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState, Symbol


class Trader:
    LIMIT = 80

    # --- PEPPER ---
    PEPPER_MAX_LONG = 35             # was 40; less max exposure
    PEPPER_SLOPE_WINDOW = 20
    PEPPER_STOP_THRESHOLD = -8       # slope < -8 over window = stop (was: 5 neg-tick streak)
    PEPPER_RESUME_THRESHOLD = 5      # slope > +5 = drift resumed; allow recovery
    PEPPER_PASSIVE_CAP = 10          # max single passive order; was uncapped

    # --- OSMIUM ---
    OSMIUM_ANCHOR = 10_000
    OSMIUM_TAKE_EDGE = 3             # was 2; more selective taking
    OSMIUM_QUOTE_SIZE = 15           # was 20; slower inventory buildup
    OSMIUM_SECOND_SIZE = 10          # was 15
    OSMIUM_SKEW_START = 25           # was 40; start skewing at 31% of limit
    OSMIUM_SKEW_HARD = 50            # new; 2-tick skew above this
    OSMIUM_FLATTEN = 55              # was 60; flatten earlier

    def __init__(self):
        self.history: Dict[str, list] = {}

    def _load_state(self, state: TradingState):
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}

    # ------------------------------------------------------------------
    # PEPPER_ROOT — capped long accumulator, magnitude slope guard
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

        drift_stopped = bool(self.history.get("pp_stopped", False))

        if len(hist) >= self.PEPPER_SLOPE_WINDOW:
            window = hist[-self.PEPPER_SLOPE_WINDOW:]
            slope = window[-1] - window[0]
            if slope < self.PEPPER_STOP_THRESHOLD:
                # Magnitude drop over window confirms real reversal — stop
                drift_stopped = True
            elif drift_stopped and slope > self.PEPPER_RESUME_THRESHOLD:
                # Drift clearly resumed — allow recovery
                drift_stopped = False

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

        # Take only at ask <= mid (no +1 buffer to reduce adverse entry cost)
        for ask in sorted(depth.sell_orders.keys()):
            if rem_cap <= 0:
                break
            avail = -depth.sell_orders[ask]
            if avail <= 0:
                continue
            if ask <= mid:
                qty = min(rem_cap, avail)
                orders.append(Order(product, ask, qty))
                rem_cap -= qty

        # Passive: cap to PEPPER_PASSIVE_CAP to avoid large adverse fills
        if rem_cap > 0:
            passive_qty = min(rem_cap, self.PEPPER_PASSIVE_CAP)
            orders.append(Order(product, bb + 1, passive_qty))

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

        # Take edge = 3: only trade clearly mispriced levels
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

        # Flatten early at OSMIUM_FLATTEN (55, not 60)
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

        # Graduated skew: shift full spread toward reducing inventory
        # Long: shift spread down (sell cheaper, buy less aggressively)
        # Short: shift spread up (buy dearer, sell less aggressively)
        abs_pos = abs(pos)
        if abs_pos > self.OSMIUM_SKEW_HARD:
            skew = 2
        elif abs_pos > self.OSMIUM_SKEW_START:
            skew = 1
        else:
            skew = 0

        skew_dir = 1 if pos > 0 else -1  # positive = long, shift down

        bid_price = min(bb + 1, fair - 1) - skew * skew_dir
        ask_price = max(ba - 1, fair + 1) - skew * skew_dir

        # Safety clamp: never quote more than 4 ticks from anchor
        bid_price = max(int(bid_price), fair - 4)
        ask_price = min(int(ask_price), fair + 4)

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
