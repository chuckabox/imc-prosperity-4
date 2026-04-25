"""
GOAT Round 3 v5 - MAXIMUM AGGRESSION

V4 fixed VFE bleeding and added VEV_5200, but HP/VFE/5300/5400/5500 still 0.
V5 cranks aggression to the max:

- HP/VFE: tiny edges (take=1.5, make=2). Ladder-quote 2 levels deep on each side.
- Wide-spread options (5000, 5100, 5200): mean-reversion takes against EMA
  + aggressive inside-spread quoting.
- Tight-spread options (5300, 5400, 5500): microprice-based directional posting
  (only post on the heavy side of the book, where flow points). Take aggressively
  against EMA deviation.
- Force cross-spread when inventory > 70% of limit (vs 85% in V4).
- Multi-level ladders for HP/VFE so we have presence at 2-3 price points.
- Short EMA for vouchers (alpha=0.4) to mean-revert against transient mid moves.
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import json


LIMITS = {
    "HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300, "VEV_4500": 300,
    "VEV_5000": 300, "VEV_5100": 300, "VEV_5200": 300,
    "VEV_5300": 300, "VEV_5400": 300, "VEV_5500": 300,
    "VEV_6000": 300, "VEV_6500": 300,
}


class Trader:

    def _best_bid(self, od):
        return max(od.buy_orders.keys()) if od.buy_orders else None

    def _best_ask(self, od):
        return min(od.sell_orders.keys()) if od.sell_orders else None

    def _mid(self, od):
        b, a = self._best_bid(od), self._best_ask(od)
        if b is not None and a is not None:
            return (b + a) / 2.0
        return None

    def _microprice(self, od):
        b, a = self._best_bid(od), self._best_ask(od)
        if b is None or a is None:
            return self._mid(od)
        bv = od.buy_orders[b]
        av = -od.sell_orders[a]
        denom = bv + av
        if denom <= 0:
            return (b + a) / 2.0
        return (b * av + a * bv) / denom

    def _book_pressure(self, od):
        """Return value in [-1, 1]: +1 means heavy buy pressure (mid will rise)."""
        b, a = self._best_bid(od), self._best_ask(od)
        if b is None or a is None:
            return 0.0
        bv = od.buy_orders[b]
        av = -od.sell_orders[a]
        if bv + av <= 0:
            return 0.0
        return (bv - av) / (bv + av)

    def _ema(self, sd, key, value, alpha):
        sd[key] = value if key not in sd else alpha * value + (1 - alpha) * sd[key]
        return sd[key]

    def _take(self, product, od, fair, position, edge, orders, max_take=999):
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

    def _ladder_make(self, product, od, fair, position, edges, qtys, orders, skew_factor=2.0):
        """Post at multiple price levels. edges[i] is i-th level offset from fair."""
        limit = LIMITS[product]
        cap_buy = limit - position
        cap_sell = limit + position
        skew = position / limit
        best_bid = self._best_bid(od)
        best_ask = self._best_ask(od)

        for i, (edge, qty) in enumerate(zip(edges, qtys)):
            bid_px = round(fair - edge - skew * edge * skew_factor)
            ask_px = round(fair + edge - skew * edge * skew_factor)
            if best_ask is not None and bid_px >= best_ask:
                bid_px = best_ask - 1
            if best_bid is not None and ask_px <= best_bid:
                ask_px = best_bid + 1
            if bid_px >= ask_px:
                continue
            if cap_buy > 0:
                q = min(qty, cap_buy)
                orders.append(Order(product, int(bid_px), q))
                cap_buy -= q
            if cap_sell > 0:
                q = min(qty, cap_sell)
                orders.append(Order(product, int(ask_px), -q))
                cap_sell -= q

    def _force_unwind(self, product, od, position, orders, threshold=0.70):
        limit = LIMITS[product]
        if abs(position) < int(threshold * limit):
            return
        target = int(0.4 * limit)
        if position > 0:
            for bid in sorted(od.buy_orders.keys(), reverse=True):
                vol = min(od.buy_orders[bid], position - target, 40)
                if vol > 0:
                    orders.append(Order(product, bid, -vol))
                    position -= vol
                if position <= target:
                    break
        else:
            for ask in sorted(od.sell_orders.keys()):
                vol = min(-od.sell_orders[ask], -position - target, 40)
                if vol > 0:
                    orders.append(Order(product, ask, vol))
                    position += vol
                if position >= -target:
                    break

    def _trade_hp(self, state, sd):
        product = "HYDROGEL_PACK"
        orders = []
        if product not in state.order_depths:
            return orders
        od = state.order_depths[product]
        pos = state.position.get(product, 0)
        mid = self._microprice(od)
        if mid is None:
            return orders

        fast = self._ema(sd, "hp_fast", mid, 0.35)
        slow = self._ema(sd, "hp_slow", mid, 0.02)
        fair = 0.65 * fast + 0.35 * slow

        self._take(product, od, fair, pos, edge=1.5, orders=orders, max_take=40)
        approx_pos = pos + sum(o.quantity for o in orders)
        self._force_unwind(product, od, approx_pos, orders, threshold=0.70)
        approx_pos = pos + sum(o.quantity for o in orders)

        self._ladder_make(product, od, fair, approx_pos,
                          edges=[2, 4, 7], qtys=[15, 12, 10],
                          orders=orders, skew_factor=2.0)
        return orders

    def _trade_vev_spot(self, state, sd):
        product = "VELVETFRUIT_EXTRACT"
        orders = []
        if product not in state.order_depths:
            return orders
        od = state.order_depths[product]
        pos = state.position.get(product, 0)
        mid = self._microprice(od)
        if mid is None:
            return orders

        fast = self._ema(sd, "vev_fast", mid, 0.4)
        slow = self._ema(sd, "vev_slow", mid, 0.04)
        trend = fast - slow
        fair = fast - 0.4 * trend

        self._take(product, od, fair, pos, edge=1.5, orders=orders, max_take=40)
        approx_pos = pos + sum(o.quantity for o in orders)
        self._force_unwind(product, od, approx_pos, orders, threshold=0.70)
        approx_pos = pos + sum(o.quantity for o in orders)

        trend_pad = min(1.5, abs(trend) * 0.4)
        self._ladder_make(product, od, fair, approx_pos,
                          edges=[1 + trend_pad, 3 + trend_pad],
                          qtys=[20, 15],
                          orders=orders, skew_factor=2.0)
        return orders

    def _trade_wide_option(self, prod, state, sd):
        """For VEV_5000, 5100, 5200 (spread 3-6): EMA-mean-reversion taking + inside MM."""
        orders = []
        if prod not in state.order_depths:
            return orders
        od = state.order_depths[prod]
        pos = state.position.get(prod, 0)
        mid = self._mid(od)
        if mid is None:
            return orders
        bid = self._best_bid(od)
        ask = self._best_ask(od)
        if bid is None or ask is None:
            return orders
        spread = ask - bid

        fast = self._ema(sd, f"{prod}_fast", mid, 0.4)
        slow = self._ema(sd, f"{prod}_slow", mid, 0.05)
        fair = fast

        take_edge = max(1.5, spread * 0.5)
        self._take(prod, od, fair, pos, edge=take_edge, orders=orders, max_take=30)
        approx_pos = pos + sum(o.quantity for o in orders)
        self._force_unwind(prod, od, approx_pos, orders, threshold=0.70)
        approx_pos = pos + sum(o.quantity for o in orders)

        skew = approx_pos / 300
        bid_off = max(1, int(spread * 0.3))
        ask_off = max(1, int(spread * 0.3))
        our_bid = int(round(fair - bid_off - skew * bid_off * 2.0))
        our_ask = int(round(fair + ask_off - skew * ask_off * 2.0))
        if our_bid >= ask:
            our_bid = ask - 1
        if our_ask <= bid:
            our_ask = bid + 1
        if our_bid >= our_ask:
            our_bid = bid
            our_ask = ask

        cap_buy = 300 - approx_pos
        cap_sell = 300 + approx_pos
        if cap_buy > 0:
            orders.append(Order(prod, our_bid, min(25, cap_buy)))
        if cap_sell > 0:
            orders.append(Order(prod, our_ask, -min(25, cap_sell)))
        return orders

    def _trade_tight_option(self, prod, state, sd):
        """For VEV_5300, 5400, 5500 (spread 1-2): microprice-directional + aggressive taking."""
        orders = []
        if prod not in state.order_depths:
            return orders
        od = state.order_depths[prod]
        pos = state.position.get(prod, 0)
        mid = self._mid(od)
        if mid is None:
            return orders
        bid = self._best_bid(od)
        ask = self._best_ask(od)
        if bid is None or ask is None:
            return orders

        fast = self._ema(sd, f"{prod}_fast", mid, 0.4)
        fair = fast
        pressure = self._book_pressure(od)

        # Aggressive take if mid deviates from EMA by ≥1 tick
        self._take(prod, od, fair, pos, edge=1.0, orders=orders, max_take=20)
        approx_pos = pos + sum(o.quantity for o in orders)
        self._force_unwind(prod, od, approx_pos, orders, threshold=0.70)
        approx_pos = pos + sum(o.quantity for o in orders)

        cap_buy = 300 - approx_pos
        cap_sell = 300 + approx_pos
        skew = approx_pos / 300

        # Directional posting: quote on the heavy side
        # If pressure > 0.3 (bid-heavy → mid drifting up), post ASK at best ask
        # If pressure < -0.3 (ask-heavy → mid drifting down), post BID at best bid
        # Otherwise, post both at the touch
        post_bid = (pressure < 0.3 or skew < -0.3) and skew < 0.5
        post_ask = (pressure > -0.3 or skew > 0.3) and skew > -0.5

        if post_bid and cap_buy > 0:
            orders.append(Order(prod, int(bid), min(15, cap_buy)))
        if post_ask and cap_sell > 0:
            orders.append(Order(prod, int(ask), -min(15, cap_sell)))
        return orders

    def _trade_deep_otm(self, prod, state):
        orders = []
        if prod not in state.order_depths:
            return orders
        od = state.order_depths[prod]
        pos = state.position.get(prod, 0)
        cap_sell = 300 + pos
        bid = self._best_bid(od)
        if bid is not None and bid >= 1 and cap_sell > 0:
            vol = min(od.buy_orders[bid], cap_sell, 60)
            orders.append(Order(prod, bid, -vol))
            cap_sell -= vol
        if cap_sell > 0:
            orders.append(Order(prod, 1, -min(cap_sell, 100)))
        if cap_sell > 30:
            orders.append(Order(prod, 2, -min(cap_sell - 30, 50)))
        return orders

    def _trade_deep_itm(self, prod, K, spot, state):
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

        if ask is not None and ask <= fair - 6 and cap_buy > 0:
            vol = min(-od.sell_orders[ask], cap_buy, 10)
            orders.append(Order(prod, ask, vol))
        if bid is not None and bid >= fair + 6 and cap_sell > 0:
            vol = min(od.buy_orders[bid], cap_sell, 10)
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
            spot = self._microprice(vev_od)
        if spot is None:
            spot = sd.get("last_spot", 5270.0)
        sd["last_spot"] = spot

        for prod in ("VEV_5000", "VEV_5100", "VEV_5200"):
            all_orders[prod] = self._trade_wide_option(prod, state, sd)
        for prod in ("VEV_5300", "VEV_5400", "VEV_5500"):
            all_orders[prod] = self._trade_tight_option(prod, state, sd)
        for prod in ("VEV_6000", "VEV_6500"):
            all_orders[prod] = self._trade_deep_otm(prod, state)
        for prod, K in [("VEV_4000", 4000), ("VEV_4500", 4500)]:
            all_orders[prod] = self._trade_deep_itm(prod, K, spot, state)

        return all_orders, 0, json.dumps(sd)
