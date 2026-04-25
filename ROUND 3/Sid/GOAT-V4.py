"""
GOAT Round 3 v4 - Hybrid

V3 was too passive (only quoted inside spreads, no taking).
V1 took aggressively on HP/VEV but used a broken IV model on vouchers.
V4 combines: V1's mean-reversion taking on HP/VEV-spot (where EMA fair makes sense)
+ V3's passive book-joining on options (no model bias from IV).

HP: EMA-anchored fair, aggressive take at edge=4, market-make ±4 with strong skew.
VEV spot: trend-aware EMA fair, aggressive take at edge=2.5, dynamic edges.
Liquid options: join the book / quote tightly inside spread (no BS pricing).
Deep OTM: always post ask at 1. Deep ITM: take only at >10 from parity.
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import json


LIMITS = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300, "VEV_4500": 300,
    "VEV_5000": 300, "VEV_5100": 300, "VEV_5200": 300,
    "VEV_5300": 300, "VEV_5400": 300, "VEV_5500": 300,
    "VEV_6000": 300, "VEV_6500": 300,
}


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

    def _ema(self, sd: dict, key: str, value: float, alpha: float):
        sd[key] = value if key not in sd else alpha * value + (1 - alpha) * sd[key]
        return sd[key]

    def _take(self, product: str, od: OrderDepth, fair: float, position: int,
              edge: float, orders: list, max_take: int = 999):
        limit = LIMITS[product]
        cap_buy = limit - position
        cap_sell = limit + position
        for ask in sorted(od.sell_orders.keys()):
            if ask <= fair - edge and cap_buy > 0 and max_take > 0:
                vol = min(-od.sell_orders[ask], cap_buy, max_take)
                if vol > 0:
                    orders.append(Order(product, ask, vol))
                    cap_buy -= vol
                    max_take -= vol
            else:
                break
        for bid in sorted(od.buy_orders.keys(), reverse=True):
            if bid >= fair + edge and cap_sell > 0 and max_take > 0:
                vol = min(od.buy_orders[bid], cap_sell, max_take)
                if vol > 0:
                    orders.append(Order(product, bid, -vol))
                    cap_sell -= vol
                    max_take -= vol
            else:
                break

    def _make(self, product: str, od: OrderDepth, fair: float, position: int,
              bid_edge: float, ask_edge: float, qty: int, orders: list,
              skew_factor: float = 1.0):
        limit = LIMITS[product]
        cap_buy = limit - position
        cap_sell = limit + position
        skew = position / limit
        bid_px = round(fair - bid_edge - skew * bid_edge * skew_factor)
        ask_px = round(fair + ask_edge - skew * ask_edge * skew_factor)
        if bid_px >= ask_px:
            bid_px = ask_px - 1
        best_bid = self._best_bid(od)
        best_ask = self._best_ask(od)
        if best_ask is not None and bid_px >= best_ask:
            bid_px = best_ask - 1
        if best_bid is not None and ask_px <= best_bid:
            ask_px = best_bid + 1
        if cap_buy > 0:
            orders.append(Order(product, int(bid_px), min(qty, cap_buy)))
        if cap_sell > 0:
            orders.append(Order(product, int(ask_px), -min(qty, cap_sell)))

    def _force_unwind(self, product: str, od: OrderDepth, position: int, orders: list):
        limit = LIMITS[product]
        if abs(position) < int(0.85 * limit):
            return
        if position > 0:
            for bid in sorted(od.buy_orders.keys(), reverse=True):
                vol = min(od.buy_orders[bid], position - int(0.6 * limit), 30)
                if vol > 0:
                    orders.append(Order(product, bid, -vol))
                    position -= vol
                if position <= int(0.6 * limit):
                    break
        else:
            for ask in sorted(od.sell_orders.keys()):
                vol = min(-od.sell_orders[ask], -position - int(0.6 * limit), 30)
                if vol > 0:
                    orders.append(Order(product, ask, vol))
                    position += vol
                if position >= -int(0.6 * limit):
                    break

    def _trade_hp(self, state: TradingState, sd: dict) -> List[Order]:
        product = "HYDROGEL_PACK"
        orders = []
        if product not in state.order_depths:
            return orders
        od = state.order_depths[product]
        pos = state.position.get(product, 0)
        mid = self._mid(od)
        if mid is None:
            return orders

        fast = self._ema(sd, "hp_fast", mid, 0.3)
        slow = self._ema(sd, "hp_slow", mid, 0.02)
        fair = 0.7 * fast + 0.3 * slow

        self._take(product, od, fair, pos, edge=4.0, orders=orders)
        approx_pos = pos + sum(o.quantity for o in orders)
        self._force_unwind(product, od, approx_pos, orders)
        approx_pos = pos + sum(o.quantity for o in orders)
        self._make(product, od, fair, approx_pos,
                   bid_edge=4.0, ask_edge=4.0, qty=18, orders=orders, skew_factor=1.5)
        return orders

    def _trade_vev_spot(self, state: TradingState, sd: dict) -> List[Order]:
        product = "VELVETFRUIT_EXTRACT"
        orders = []
        if product not in state.order_depths:
            return orders
        od = state.order_depths[product]
        pos = state.position.get(product, 0)
        mid = self._mid(od)
        if mid is None:
            return orders

        fast = self._ema(sd, "vev_fast", mid, 0.4)
        slow = self._ema(sd, "vev_slow", mid, 0.05)
        trend = fast - slow
        fair = fast - 0.3 * trend

        self._take(product, od, fair, pos, edge=2.5, orders=orders)
        approx_pos = pos + sum(o.quantity for o in orders)
        self._force_unwind(product, od, approx_pos, orders)
        approx_pos = pos + sum(o.quantity for o in orders)

        bid_edge = 2.0 + min(2.0, abs(trend) * 0.5)
        ask_edge = 2.0 + min(2.0, abs(trend) * 0.5)
        self._make(product, od, fair, approx_pos,
                   bid_edge=bid_edge, ask_edge=ask_edge,
                   qty=20, orders=orders, skew_factor=1.5)
        return orders

    def _trade_liquid_option(self, prod: str, state: TradingState) -> List[Order]:
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

        self._force_unwind(prod, od, pos, orders)
        approx_pos = pos + sum(o.quantity for o in orders)
        cap_buy = 300 - approx_pos
        cap_sell = 300 + approx_pos
        skew = approx_pos / 300

        if spread <= 1:
            if cap_buy > 0 and skew < 0.5:
                orders.append(Order(prod, int(bid), min(15, cap_buy)))
            if cap_sell > 0 and skew > -0.5:
                orders.append(Order(prod, int(ask), -min(15, cap_sell)))
        elif spread == 2:
            if cap_buy > 0 and skew < 0.5:
                orders.append(Order(prod, int(bid), min(15, cap_buy)))
            if cap_sell > 0 and skew > -0.5:
                orders.append(Order(prod, int(ask), -min(15, cap_sell)))
        else:
            our_bid = int(bid + 1 - skew * 2)
            our_ask = int(ask - 1 - skew * 2)
            if our_bid >= our_ask:
                our_bid = int(bid)
                our_ask = int(ask)
            if our_bid > ask - 1:
                our_bid = ask - 1
            if our_ask < bid + 1:
                our_ask = bid + 1
            if cap_buy > 0:
                orders.append(Order(prod, our_bid, min(20, cap_buy)))
            if cap_sell > 0:
                orders.append(Order(prod, our_ask, -min(20, cap_sell)))
        return orders

    def _trade_deep_otm(self, prod: str, state: TradingState) -> List[Order]:
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

        all_orders["HYDROGEL_PACK"] = self._trade_hp(state, sd)
        all_orders["VELVETFRUIT_EXTRACT"] = self._trade_vev_spot(state, sd)

        spot = None
        vev_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if vev_od:
            spot = self._mid(vev_od)
        if spot is None:
            spot = sd.get("last_spot", 5270.0)
        sd["last_spot"] = spot

        for prod in ("VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"):
            all_orders[prod] = self._trade_liquid_option(prod, state)

        for prod in ("VEV_6000", "VEV_6500"):
            all_orders[prod] = self._trade_deep_otm(prod, state)

        for prod, K in [("VEV_4000", 4000), ("VEV_4500", 4500)]:
            all_orders[prod] = self._trade_deep_itm(prod, K, spot, state)

        return all_orders, 0, json.dumps(sd)
