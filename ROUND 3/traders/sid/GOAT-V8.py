"""
GOAT V8 - SINGLE PRODUCT: VEV_5200 ONLY

V7 lost catastrophically (-$2,200 on VEV_5200, -$1,300 on VEV_5300) by
aggressively shorting based on a wrong "overpriced" thesis. The short got
squeezed because these options have real time value (spot ~5270 is close
to strikes).

V5's strategy on VEV_5200 worked: EMA mean-reversion + inside-spread MM with
inventory skew. Made +$662 in backtest, ~+$30 live.

V8 = strip everything except VEV_5200. Use V5's proven approach. No directional
bias, no shorting thesis, just clean spread capture around an EMA fair value.
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import json


PRODUCT = "VEV_5200"
LIMIT = 300


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

    def _ema(self, sd, key, value, alpha):
        sd[key] = value if key not in sd else alpha * value + (1 - alpha) * sd[key]
        return sd[key]

    def _take(self, od, fair, position, edge, orders, max_take):
        cap_buy = LIMIT - position
        cap_sell = LIMIT + position
        for ask in sorted(od.sell_orders.keys()):
            if ask <= fair - edge and cap_buy > 0 and max_take > 0:
                vol = min(-od.sell_orders[ask], cap_buy, max_take)
                if vol > 0:
                    orders.append(Order(PRODUCT, ask, vol))
                    cap_buy -= vol
                    max_take -= vol
            else:
                break
        for bid in sorted(od.buy_orders.keys(), reverse=True):
            if bid >= fair + edge and cap_sell > 0 and max_take > 0:
                vol = min(od.buy_orders[bid], cap_sell, max_take)
                if vol > 0:
                    orders.append(Order(PRODUCT, bid, -vol))
                    cap_sell -= vol
                    max_take -= vol
            else:
                break

    def _force_unwind(self, od, position, orders, threshold=0.65, target_frac=0.30):
        if abs(position) < int(threshold * LIMIT):
            return
        target = int(target_frac * LIMIT)
        if position > 0:
            for bid in sorted(od.buy_orders.keys(), reverse=True):
                vol = min(od.buy_orders[bid], position - target, 50)
                if vol > 0:
                    orders.append(Order(PRODUCT, bid, -vol))
                    position -= vol
                if position <= target:
                    break
        else:
            for ask in sorted(od.sell_orders.keys()):
                vol = min(-od.sell_orders[ask], -position - target, 50)
                if vol > 0:
                    orders.append(Order(PRODUCT, ask, vol))
                    position += vol
                if position >= -target:
                    break

    def _trade(self, state, sd):
        orders = []
        if PRODUCT not in state.order_depths:
            return orders
        od = state.order_depths[PRODUCT]
        pos = state.position.get(PRODUCT, 0)
        bid = self._best_bid(od)
        ask = self._best_ask(od)
        if bid is None or ask is None:
            return orders
        mid = (bid + ask) / 2.0
        spread = ask - bid

        # EMA-anchored fair value (V5's proven approach)
        fast = self._ema(sd, "fast", mid, 0.4)
        slow = self._ema(sd, "slow", mid, 0.05)
        fair = fast

        # 1. Mean-reversion taking - cross spread when ask cheap or bid rich
        take_edge = max(1.5, spread * 0.45)
        self._take(od, fair, pos, edge=take_edge, orders=orders, max_take=40)
        approx_pos = pos + sum(o.quantity for o in orders)

        # 2. Force unwind near limit
        self._force_unwind(od, approx_pos, orders, threshold=0.65, target_frac=0.30)
        approx_pos = pos + sum(o.quantity for o in orders)

        # 3. Inside-spread MM with inventory skew
        skew = approx_pos / LIMIT
        bid_off = max(1, int(spread * 0.3))
        ask_off = max(1, int(spread * 0.3))
        our_bid = int(round(fair - bid_off - skew * bid_off * 2.0))
        our_ask = int(round(fair + ask_off - skew * ask_off * 2.0))

        # Stay inside the spread
        if our_bid >= ask:
            our_bid = ask - 1
        if our_ask <= bid:
            our_ask = bid + 1
        if our_bid >= our_ask:
            our_bid = bid
            our_ask = ask

        cap_buy = LIMIT - approx_pos
        cap_sell = LIMIT + approx_pos
        if cap_buy > 0:
            orders.append(Order(PRODUCT, our_bid, min(40, cap_buy)))
        if cap_sell > 0:
            orders.append(Order(PRODUCT, our_ask, -min(40, cap_sell)))

        return orders

    def run(self, state: TradingState):
        try:
            sd: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            sd = {}

        all_orders: Dict[str, List[Order]] = {PRODUCT: self._trade(state, sd)}
        return all_orders, 0, json.dumps(sd)
