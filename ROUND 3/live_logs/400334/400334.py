"""
GOAT Round 3 v3 - Simplified Market-Making

Key insight: avoid complex fair-value models. Instead:
  - HP & VEV spot: tight MM with strong inventory skew
  - Liquid options: join the book at best bid/ask, let spreads do the work
  - Deep OTM: post passive ask at 1 (free short)
  - Deep ITM: only take extreme mispricing vs S-K parity

This removes the bias from IV calibration errors and the over-passivity of v2.
Result: steady, spread-capture focused PnL.
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import json


class Trader:

    def _best_bid(self, od: OrderDepth):
        return max(od.buy_orders.keys()) if od.buy_orders else None

    def _best_ask(self, od: OrderDepth):
        return min(od.sell_orders.keys()) if od.sell_orders else None

    def _mid(self, od: OrderDepth):
        b, a = self._best_bid(od), self._best_ask(od)
        if b is not None and a is not None:
            return (b + a) / 2.0
        return None

    def _join_book(self, product: str, od: OrderDepth, position: int,
                   qty_per_side: int, orders: list):
        """Post at best bid and ask (join the book) to capture spread."""
        limit = {"HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200}.get(product, 300)
        cap_buy = limit - position
        cap_sell = limit + position

        bid = self._best_bid(od)
        ask = self._best_ask(od)

        if bid is not None and cap_buy > 0:
            orders.append(Order(product, int(bid), min(qty_per_side, cap_buy)))
        if ask is not None and cap_sell > 0:
            orders.append(Order(product, int(ask), -min(qty_per_side, cap_sell)))

    def _inside_spread(self, product: str, od: OrderDepth, position: int,
                       bid_offset: int, ask_offset: int, qty: int, orders: list):
        """Post inside the spread with inventory skew."""
        limit = {"HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200}.get(product, 300)
        cap_buy = limit - position
        cap_sell = limit + position

        bid = self._best_bid(od)
        ask = self._best_ask(od)
        if bid is None or ask is None:
            return

        skew = position / limit
        our_bid = int(bid + bid_offset + skew * bid_offset * 2.0)
        our_ask = int(ask - ask_offset - skew * ask_offset * 2.0)

        if our_bid < bid:
            our_bid = bid
        if our_ask > ask:
            our_ask = ask
        if our_bid >= our_ask:
            our_bid, our_ask = int((bid + ask) / 2) - 1, int((bid + ask) / 2) + 1

        if cap_buy > 0 and our_bid >= bid:
            orders.append(Order(product, our_bid, min(qty, cap_buy)))
        if cap_sell > 0 and our_ask <= ask:
            orders.append(Order(product, our_ask, -min(qty, cap_sell)))

    def _unwind_if_needed(self, product: str, od: OrderDepth, position: int,
                          orders: list):
        """Cross the spread to flatten if near position limit."""
        limit = {"HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200}.get(product, 300)
        if abs(position) < int(0.75 * limit):
            return

        bid = self._best_bid(od)
        ask = self._best_ask(od)
        if bid is None or ask is None:
            return

        if position > 0:
            vol = min(position - int(0.5 * limit), 30)
            if vol > 0:
                orders.append(Order(product, bid, -vol))
        elif position < 0:
            vol = min(-position - int(0.5 * limit), 30)
            if vol > 0:
                orders.append(Order(product, ask, vol))

    def _trade_hp(self, state: TradingState) -> List[Order]:
        product = "HYDROGEL_PACK"
        orders = []
        if product not in state.order_depths:
            return orders
        od = state.order_depths[product]
        pos = state.position.get(product, 0)

        self._unwind_if_needed(product, od, pos, orders)
        approx_pos = pos + sum(o.quantity for o in orders)

        self._inside_spread(product, od, approx_pos,
                            bid_offset=5, ask_offset=5, qty=20, orders=orders)
        return orders

    def _trade_vev_spot(self, state: TradingState) -> List[Order]:
        product = "VELVETFRUIT_EXTRACT"
        orders = []
        if product not in state.order_depths:
            return orders
        od = state.order_depths[product]
        pos = state.position.get(product, 0)

        self._unwind_if_needed(product, od, pos, orders)
        approx_pos = pos + sum(o.quantity for o in orders)

        self._inside_spread(product, od, approx_pos,
                            bid_offset=2, ask_offset=2, qty=25, orders=orders)
        return orders

    def _trade_liquid_option(self, prod: str, state: TradingState) -> List[Order]:
        """Liquid options (5000-5500): join the book tightly."""
        orders = []
        if prod not in state.order_depths:
            return orders
        od = state.order_depths[prod]
        pos = state.position.get(prod, 0)

        bid = self._best_bid(od)
        ask = self._best_ask(od)
        if bid is None or ask is None:
            return orders

        spread = ask - bid
        cap_buy = 300 - pos
        cap_sell = 300 + pos

        if spread <= 1:
            # Ultra-tight: join at both sides
            if cap_buy > 0:
                orders.append(Order(prod, int(bid), min(20, cap_buy)))
            if cap_sell > 0:
                orders.append(Order(prod, int(ask), -min(20, cap_sell)))
        else:
            # Tighter spread: quote inside
            our_bid = int(bid + 0.5 * (spread / 2.0))
            our_ask = int(ask - 0.5 * (spread / 2.0))
            if our_bid >= our_ask:
                our_bid = int(bid)
                our_ask = int(ask)
            if cap_buy > 0 and our_bid > bid - 1:
                orders.append(Order(prod, our_bid, min(20, cap_buy)))
            if cap_sell > 0 and our_ask < ask + 1:
                orders.append(Order(prod, our_ask, -min(20, cap_sell)))

        return orders

    def _trade_deep_otm(self, prod: str, state: TradingState) -> List[Order]:
        """Deep OTM (6000, 6500): always sell at 1."""
        orders = []
        if prod not in state.order_depths:
            return orders
        od = state.order_depths[prod]
        pos = state.position.get(prod, 0)
        cap_sell = 300 + pos

        bid = self._best_bid(od)
        if bid is not None and bid >= 1 and cap_sell > 0:
            vol = min(od.buy_orders[bid], cap_sell, 50)
            orders.append(Order(prod, bid, -vol))
            cap_sell -= vol

        if cap_sell > 0:
            orders.append(Order(prod, 1, -min(cap_sell, 50)))

        return orders

    def _trade_deep_itm(self, prod: str, K: int, spot: float,
                        state: TradingState) -> List[Order]:
        """Deep ITM (4000, 4500): only take if >10 ticks from parity."""
        orders = []
        if prod not in state.order_depths:
            return orders
        od = state.order_depths[prod]
        pos = state.position.get(prod, 0)

        fair = max(spot - K, 0.0)
        bid = self._best_bid(od)
        ask = self._best_ask(od)

        cap_buy = 300 - pos
        cap_sell = 300 + pos

        if ask is not None and ask <= fair - 10 and cap_buy > 0:
            vol = min(-od.sell_orders[ask], cap_buy, 5)
            orders.append(Order(prod, ask, vol))

        if bid is not None and bid >= fair + 10 and cap_sell > 0:
            vol = min(od.buy_orders[bid], cap_sell, 5)
            orders.append(Order(prod, bid, -vol))

        return orders

    def run(self, state: TradingState):
        try:
            sd: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            sd = {}

        all_orders: Dict[str, List[Order]] = {}

        all_orders["HYDROGEL_PACK"] = self._trade_hp(state)
        all_orders["VELVETFRUIT_EXTRACT"] = self._trade_vev_spot(state)

        spot = None
        vev_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if vev_od:
            spot = self._mid(vev_od)
        if spot is None:
            spot = sd.get("last_spot", 5250.0)
        sd["last_spot"] = spot

        for prod in ("VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"):
            all_orders[prod] = self._trade_liquid_option(prod, state)

        for prod in ("VEV_6000", "VEV_6500"):
            all_orders[prod] = self._trade_deep_otm(prod, state)

        for prod, K in [("VEV_4000", 4000), ("VEV_4500", 4500)]:
            all_orders[prod] = self._trade_deep_itm(prod, K, spot, state)

        return all_orders, 0, json.dumps(sd)