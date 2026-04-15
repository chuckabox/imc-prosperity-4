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
    trader_ken v5 (new algo family)
    - Osmium: v2-style anchored market making
    - Pepper: bidirectional alpha with regime-aware target inventory
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
                tape_volume += trade.quantity if trade.price >= 10000 else -trade.quantity
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
                momentum += trade.quantity if trade.price >= mid else -trade.quantity

        if momentum != 0:
            direction = 1 if momentum > 0 else -1
            pred_direction = 1 if prediction > mid else -1
            if direction == pred_direction:
                prediction += direction * 0.9

        return prediction

    def pepper_regime(self) -> str:
        hist = self.history.get("pepper_long_hist", [])
        if len(hist) < 6:
            return "neutral"
        slope = (hist[-1] - hist[-6]) / 5.0
        if slope > 0.45:
            return "up"
        if slope < -0.45:
            return "down"
        return "neutral"

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ---- OSMIUM (trusted baseline behavior) ----
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

            skew = 0.05
            bid_px = min(best_bid + 1, math.floor(fair - 0.5 - (position * skew)))
            ask_px = max(best_ask - 1, math.ceil(fair + 0.5 - (position * skew)))
            bid_px = min(bid_px, math.floor(fair - 0.5))
            ask_px = max(ask_px, math.ceil(fair + 0.5))

            if rem_buy > 0:
                orders.append(Order(product, int(bid_px), rem_buy))
            if rem_sell > 0:
                orders.append(Order(product, int(ask_px), -rem_sell))

            result[product] = orders

        # ---- PEPPER (new bidirectional family) ----
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
                target = 35
            elif regime == "down":
                target = -35

            # Taker entries/exits around fair with target-aware bias.
            buy_edge = 1.0
            sell_edge = 1.0
            if regime == "up":
                buy_edge = 0.6
                sell_edge = 1.8
            elif regime == "down":
                buy_edge = 1.8
                sell_edge = 0.6

            for ask, vol in sorted(depth.sell_orders.items()):
                if buy_cap <= 0:
                    break
                if ask <= fair - buy_edge and position < target + 25:
                    qty = min(abs(vol), buy_cap, 25)
                    orders.append(Order(product, ask, qty))
                    buy_cap -= qty
                    position += qty
                else:
                    break

            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if sell_cap <= 0:
                    break
                if bid >= fair + sell_edge and position > target - 25:
                    qty = min(abs(vol), sell_cap, 25)
                    orders.append(Order(product, bid, -qty))
                    sell_cap -= qty
                    position -= qty
                else:
                    break

            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(fair - 1)
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(fair + 1)

            gap = target - position
            bias = max(-2.0, min(2.0, gap / 20.0))
            passive_bid = min(best_bid + 1, int(math.floor(fair - 1.0 + bias)))
            passive_ask = max(best_ask - 1, int(math.ceil(fair + 1.0 + bias)))

            if buy_cap > 0:
                buy_qty = min(buy_cap, 30 if gap > 0 else 15)
                if buy_qty > 0:
                    orders.append(Order(product, passive_bid, buy_qty))

            if sell_cap > 0:
                sell_qty = min(sell_cap, 30 if gap < 0 else 15)
                if sell_qty > 0:
                    orders.append(Order(product, passive_ask, -sell_qty))

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
