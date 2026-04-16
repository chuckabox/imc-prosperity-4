import json
import math
from typing import Any, Dict, List

from datamodel import Order, Symbol, TradingState


class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(
        self,
        state: TradingState,
        orders: Dict[Symbol, List["Order"]],
        conversions: int,
        trader_data: str,
    ) -> None:
        pass


logger = Logger()


class Trader:
    """
    trader_ken v6.5
    - Osmium: keep v6.1 profile
    - Pepper: tighter edge filters + stronger inventory pull
    """

    def __init__(self):
        self.limits = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
        self.sf_weights = [0.34296, 0.32058, 0.33645]
        self.sf_intercept = 0.2535
        self.history = {}

    def update_history(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except Exception:
                self.history = {}

    def get_osmium_fair(self, state: TradingState) -> float:
        product = "ASH_COATED_OSMIUM"
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
        mid = (best_bid + best_ask) / 2.0

        tape_volume = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= 10000:
                    tape_volume += trade.quantity
                else:
                    tape_volume -= trade.quantity

        tape_adj = math.copysign(min(abs(tape_volume) * 0.185, 3.0), tape_volume)
        mid_pull = max(-1.0, min(1.0, (mid - 10000.0) * 0.15))
        return 10000.0 + tape_adj + mid_pull

    def get_pepper_fair(self, state: TradingState) -> float:
        product = "INTARIAN_PEPPER_ROOT"
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None

        if best_bid is None and best_ask is None:
            return self.history.get("_pepper_last", 0.0)

        mid = ((best_bid or best_ask) + (best_ask or best_bid)) / 2.0
        self.history["_pepper_last"] = mid

        short_hist = self.history.get("pepper_short_hist", [])
        if not isinstance(short_hist, list):
            short_hist = []
        short_hist.append(mid)
        if len(short_hist) > 3:
            short_hist = short_hist[-3:]
        self.history["pepper_short_hist"] = short_hist

        long_hist = self.history.get("pepper_long_hist", [])
        if not isinstance(long_hist, list):
            long_hist = []
        long_hist.append(mid)
        if len(long_hist) > 8:
            long_hist = long_hist[-8:]
        self.history["pepper_long_hist"] = long_hist

        if len(short_hist) < 3:
            return mid

        prediction = self.sf_intercept
        for i in range(3):
            prediction += self.sf_weights[i] * short_hist[-(i + 1)]

        momentum = 0
        if product in state.market_trades and state.market_trades[product]:
            for trade in state.market_trades[product]:
                if trade.price >= mid:
                    momentum += trade.quantity
                else:
                    momentum -= trade.quantity

        if momentum != 0:
            direction = 1 if momentum > 0 else -1
            pred_direction = 1 if prediction > mid else -1
            if direction == pred_direction:
                prediction += direction * 0.75

        return prediction

    def pepper_regime(self) -> str:
        hist = self.history.get("pepper_long_hist", [])
        if len(hist) < 6:
            return "neutral"
        slope = (hist[-1] - hist[-6]) / 5.0
        if slope > 0.5:
            return "up"
        if slope < -0.5:
            return "down"
        return "neutral"

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        product = "ASH_COATED_OSMIUM"
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
            spread = max(1, best_ask - best_bid)
            fair = self.get_osmium_fair(state)
            orders: List["Order"] = []

            rem_buy = limit - position
            rem_sell = limit + position
            take_margin = 2.25 if spread <= 2 else 2.65
            if abs(position) >= 50:
                take_margin += 0.15

            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - take_margin and rem_buy > 0:
                    qty = min(rem_buy, -vol)
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty
                    position += qty

            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + take_margin and rem_sell > 0:
                    qty = min(rem_sell, vol)
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty
                    position -= qty

            skew_factor = 0.05 if abs(position) < 45 else 0.085
            bid_price = math.floor(fair - 0.5 - (position * skew_factor))
            ask_price = math.ceil(fair + 0.5 - (position * skew_factor))
            final_bid = min(best_bid + 1, bid_price)
            final_ask = max(best_ask - 1, ask_price)
            final_bid = min(final_bid, math.floor(fair - 0.5))
            final_ask = max(final_ask, math.ceil(fair + 0.5))

            if rem_buy > 0:
                top_buy = min(rem_buy, math.ceil(rem_buy * 0.62))
                deep_buy = rem_buy - top_buy
                orders.append(Order(product, int(final_bid), top_buy))
                if deep_buy > 0:
                    orders.append(Order(product, int(final_bid - 1), deep_buy))

            if rem_sell > 0:
                top_sell = min(rem_sell, math.ceil(rem_sell * 0.62))
                deep_sell = rem_sell - top_sell
                orders.append(Order(product, int(final_ask), -top_sell))
                if deep_sell > 0:
                    orders.append(Order(product, int(final_ask + 1), -deep_sell))

            result[product] = orders

        product = "INTARIAN_PEPPER_ROOT"
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            buy_cap = limit - position
            sell_cap = limit + position
            fair = self.get_pepper_fair(state)
            regime = self.pepper_regime()
            orders: List["Order"] = []

            target = 0
            if regime == "up":
                target = 25
            elif regime == "down":
                target = -25

            buy_edge = 1.1
            sell_edge = 1.1
            if regime == "up":
                buy_edge = 0.6
                sell_edge = 2.0
            elif regime == "down":
                buy_edge = 2.0
                sell_edge = 0.6

            for ask, vol in sorted(depth.sell_orders.items()):
                if buy_cap <= 0:
                    break
                if ask <= fair - buy_edge and position < target + 20:
                    qty = min(abs(vol), buy_cap, 20)
                    orders.append(Order(product, ask, qty))
                    buy_cap -= qty
                    position += qty
                else:
                    break

            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if sell_cap <= 0:
                    break
                if bid >= fair + sell_edge and position > target - 20:
                    qty = min(abs(vol), sell_cap, 20)
                    orders.append(Order(product, bid, -qty))
                    sell_cap -= qty
                    position -= qty
                else:
                    break

            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(fair - 1)
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(fair + 1)

            gap = target - position
            bias = max(-2.0, min(2.0, gap / 16.0))
            passive_bid = min(best_bid + 1, int(math.floor(fair - 1.2 + bias)))
            passive_ask = max(best_ask - 1, int(math.ceil(fair + 1.2 + bias)))

            if buy_cap > 0:
                buy_qty = min(buy_cap, 32 if gap > 0 else 12)
                if buy_qty > 0:
                    orders.append(Order(product, passive_bid, buy_qty))

            if sell_cap > 0:
                sell_qty = min(sell_cap, 32 if gap < 0 else 12)
                if sell_qty > 0:
                    orders.append(Order(product, passive_ask, -sell_qty))

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
