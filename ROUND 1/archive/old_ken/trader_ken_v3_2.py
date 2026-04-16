import json
import math
from typing import Dict, List, Any
from datamodel import Order, TradingState, Symbol


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
    trader_ken v3.2
    - Osmium: baseline anchored sniper + pennying
    - Pepper: hybrid of trend-follow + mean-reversion flips
    """

    def __init__(self):
        self.limits = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
        self.sf_weights = [0.34296, 0.32058, 0.33645]
        self.sf_intercept = 0.2535
        self.history: Dict[str, Any] = {}

    def update_history(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except Exception:
                self.history = {}

    def get_osmium_fair(self, state: TradingState) -> float:
        product = "ASH_COATED_OSMIUM"
        tape_volume = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= 10000:
                    tape_volume += trade.quantity
                else:
                    tape_volume -= trade.quantity
        tape_adj = math.copysign(min(abs(tape_volume) * 0.15, 2.5), tape_volume)
        return 10000.0 + tape_adj

    def get_pepper_fair(self, state: TradingState) -> float:
        product = "INTARIAN_PEPPER_ROOT"
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None

        if best_bid is None and best_ask is None:
            return self.history.get("_pepper_last", 0.0)

        mid = ((best_bid or best_ask) + (best_ask or best_bid)) / 2.0
        self.history["_pepper_last"] = mid

        hist = self.history.get(product, [])
        if not isinstance(hist, list):
            hist = []
        hist.append(mid)
        if len(hist) > 3:
            hist = hist[-3:]
        self.history[product] = hist

        long_hist = self.history.get("pepper_long_hist", [])
        if not isinstance(long_hist, list):
            long_hist = []
        long_hist.append(mid)
        if len(long_hist) > 8:
            long_hist = long_hist[-8:]
        self.history["pepper_long_hist"] = long_hist

        if len(hist) < 3:
            return mid

        prediction = self.sf_intercept
        for i in range(3):
            prediction += self.sf_weights[i] * hist[-(i + 1)]

        # tape confirmation
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
                prediction += direction * 0.8

        return prediction

    def _pepper_regime(self) -> str:
        hist = self.history.get("pepper_long_hist", [])
        if len(hist) < 6:
            return "neutral"
        slope = (hist[-1] - hist[-6]) / 5.0
        if slope > 0.6:
            return "up"
        if slope < -0.6:
            return "down"
        return "neutral"

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ---- OSMIUM unchanged baseline ----
        product = "ASH_COATED_OSMIUM"
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
            fair = self.get_osmium_fair(state)
            orders: List["Order"] = []

            rem_buy = limit - position
            rem_sell = limit + position
            take_margin = 2.5

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

            skew_factor = 0.05
            bid_price = math.floor(fair - 0.5 - (position * skew_factor))
            ask_price = math.ceil(fair + 0.5 - (position * skew_factor))
            final_bid = min(best_bid + 1, bid_price)
            final_ask = max(best_ask - 1, ask_price)
            final_bid = min(final_bid, math.floor(fair - 0.5))
            final_ask = max(final_ask, math.ceil(fair + 0.5))

            if rem_buy > 0:
                orders.append(Order(product, int(final_bid), rem_buy))
            if rem_sell > 0:
                orders.append(Order(product, int(final_ask), -rem_sell))
            result[product] = orders

        # ---- PEPPER hybrid alpha ----
        product = "INTARIAN_PEPPER_ROOT"
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            buy_cap = limit - position
            sell_cap = limit + position
            fair = self.get_pepper_fair(state)
            regime = self._pepper_regime()
            orders: List["Order"] = []

            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(fair - 1)
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(fair + 1)
            mid = (best_bid + best_ask) / 2.0 if best_bid and best_ask else fair

            # Baseline trend-follow buys, but less blind at extremes.
            max_take_qty = buy_cap if position < 55 else min(buy_cap, 20)
            taken = 0
            for ask in sorted(depth.sell_orders.keys()):
                if taken >= max_take_qty:
                    break
                # If market is stretched above fair, switch to mean-reversion behavior.
                if ask > fair + 1.2 and regime != "up":
                    break
                qty = min(abs(depth.sell_orders[ask]), max_take_qty - taken)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    buy_cap -= qty
                    taken += qty

            # Resting bid only when not already too long or too extended.
            if buy_cap > 0 and position < 60 and mid <= fair + 0.8:
                rest_qty = buy_cap if position < 45 else min(buy_cap, 12)
                orders.append(Order(product, best_bid + 1, rest_qty))

            # Mean-reversion flip: if book is far above fair, allow tactical shorts.
            if regime == "neutral" and position > 20:
                for bid in sorted(depth.buy_orders.keys(), reverse=True):
                    if sell_cap <= 0:
                        break
                    if bid >= fair + 2.6:
                        qty = min(abs(depth.buy_orders[bid]), sell_cap, 15)
                        orders.append(Order(product, bid, -qty))
                        sell_cap -= qty
                    else:
                        break

            # Core profit-taking with adaptive threshold.
            take_profit = 3.0
            if position >= 45:
                take_profit = 2.2
            if position >= 65:
                take_profit = 1.5
            if regime == "down":
                take_profit = min(take_profit, 1.8)

            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if sell_cap <= 0:
                    break
                if bid >= fair + take_profit:
                    qty = min(abs(depth.buy_orders[bid]), sell_cap)
                    orders.append(Order(product, bid, -qty))
                    sell_cap -= qty
                else:
                    break

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
