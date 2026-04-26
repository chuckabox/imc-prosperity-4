"""
GOAT V9 - Expanded Wide Options (5000, 5100, 5200)

V8 worked: VEV_5200 made ~$25-30/day (matched V5's edge on this product).
But we capped total profit by trading only ONE product.

V5 backtest showed wide options 5000/5100/5200 all worked with the same
EMA mean-reversion strategy:
  - VEV_5000: +$111
  - VEV_5100: +$101
  - VEV_5200: +$662

V9 trades all three wide options with the V8/V5 proven strategy.
Expected: ~$75-120/day total (3x V8's profit).

Why only the wide options:
- They have 6-7 tick spreads (room for inside-spread MM)
- Live confirmed VEV_5200 fills at +PnL
- Tight options (5300-5500) and HP/VFE didn't fill in V5/V7 live tests
- Deep ITM/OTM (4000/4500/6000/6500) never trade
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import json


PRODUCTS = ("VEV_5000", "VEV_5100", "VEV_5200")
LIMIT = 300


class Trader:

    def _best_bid(self, od):
        return max(od.buy_orders.keys()) if od.buy_orders else None

    def _best_ask(self, od):
        return min(od.sell_orders.keys()) if od.sell_orders else None

    def _ema(self, sd, key, value, alpha):
        sd[key] = value if key not in sd else alpha * value + (1 - alpha) * sd[key]
        return sd[key]

    def _take(self, prod, od, fair, position, edge, orders, max_take):
        cap_buy = LIMIT - position
        cap_sell = LIMIT + position
        for ask in sorted(od.sell_orders.keys()):
            if ask <= fair - edge and cap_buy > 0 and max_take > 0:
                vol = min(-od.sell_orders[ask], cap_buy, max_take)
                if vol > 0:
                    orders.append(Order(prod, ask, vol))
                    cap_buy -= vol
                    max_take -= vol
            else:
                break
        for bid in sorted(od.buy_orders.keys(), reverse=True):
            if bid >= fair + edge and cap_sell > 0 and max_take > 0:
                vol = min(od.buy_orders[bid], cap_sell, max_take)
                if vol > 0:
                    orders.append(Order(prod, bid, -vol))
                    cap_sell -= vol
                    max_take -= vol
            else:
                break

    def _force_unwind(self, prod, od, position, orders, threshold=0.65, target_frac=0.30):
        if abs(position) < int(threshold * LIMIT):
            return
        target = int(target_frac * LIMIT)
        if position > 0:
            for bid in sorted(od.buy_orders.keys(), reverse=True):
                vol = min(od.buy_orders[bid], position - target, 50)
                if vol > 0:
                    orders.append(Order(prod, bid, -vol))
                    position -= vol
                if position <= target:
                    break
        else:
            for ask in sorted(od.sell_orders.keys()):
                vol = min(-od.sell_orders[ask], -position - target, 50)
                if vol > 0:
                    orders.append(Order(prod, ask, vol))
                    position += vol
                if position >= -target:
                    break

    def _trade(self, prod, state, sd):
        orders = []
        if prod not in state.order_depths:
            return orders
        od = state.order_depths[prod]
        pos = state.position.get(prod, 0)
        bid = self._best_bid(od)
        ask = self._best_ask(od)
        if bid is None or ask is None:
            return orders
        mid = (bid + ask) / 2.0
        spread = ask - bid

        # EMA-anchored fair value (V5/V8 proven approach)
        fast = self._ema(sd, f"{prod}_fast", mid, 0.4)
        slow = self._ema(sd, f"{prod}_slow", mid, 0.05)
        fair = fast

        # 1. Mean-reversion taking
        take_edge = max(1.5, spread * 0.45)
        self._take(prod, od, fair, pos, edge=take_edge, orders=orders, max_take=40)
        approx_pos = pos + sum(o.quantity for o in orders)

        # 2. Force unwind near limit
        self._force_unwind(prod, od, approx_pos, orders, threshold=0.65, target_frac=0.30)
        approx_pos = pos + sum(o.quantity for o in orders)

        # 3. Inside-spread MM with inventory skew
        skew = approx_pos / LIMIT
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

        cap_buy = LIMIT - approx_pos
        cap_sell = LIMIT + approx_pos
        if cap_buy > 0:
            orders.append(Order(prod, our_bid, min(40, cap_buy)))
        if cap_sell > 0:
            orders.append(Order(prod, our_ask, -min(40, cap_sell)))

        return orders

    def run(self, state: TradingState):
        try:
            sd: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            sd = {}

        all_orders: Dict[str, List[Order]] = {}
        for prod in PRODUCTS:
            all_orders[prod] = self._trade(prod, state, sd)

        return all_orders, 0, json.dumps(sd)
