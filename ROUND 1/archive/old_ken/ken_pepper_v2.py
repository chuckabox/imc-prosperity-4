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
    ken_pepper_v2
    - Osmium: unchanged v6.6 baseline
    - Pepper: less passive than v1, still inventory-safe
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

        tape_volume = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= 10000:
                    tape_volume += trade.quantity
                else:
                    tape_volume -= trade.quantity

        tape_adj = math.copysign(min(abs(tape_volume) * 0.17, 2.8), tape_volume)
        top_bid_vol = depth.buy_orders.get(best_bid, 0)
        top_ask_vol = -depth.sell_orders.get(best_ask, 0)
        denom = top_bid_vol + top_ask_vol
        imbalance = (top_bid_vol - top_ask_vol) / denom if denom > 0 else 0.0
        imbalance_adj = max(-0.7, min(0.7, imbalance * 0.9))
        return 10000.0 + tape_adj + imbalance_adj

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
                prediction += direction * 0.72

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

        # OSMIUM baseline
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
            base_take = 2.2 if spread <= 2 else 2.65
            inventory_penalty = 0.2 if abs(position) >= 55 else 0.0
            take_margin = base_take + inventory_penalty

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

            spread_bias = 0.06 if spread <= 2 else 0.08
            skew_factor = spread_bias if abs(position) < 45 else spread_bias + 0.03
            width = 0.45 if spread <= 2 else 0.6
            bid_price = math.floor(fair - width - (position * skew_factor))
            ask_price = math.ceil(fair + width - (position * skew_factor))
            final_bid = min(best_bid + 1, bid_price)
            final_ask = max(best_ask - 1, ask_price)
            final_bid = min(final_bid, math.floor(fair - 0.5))
            final_ask = max(final_ask, math.ceil(fair + 0.5))

            if rem_buy > 0:
                top_buy = min(rem_buy, math.ceil(rem_buy * 0.68))
                deep_buy = rem_buy - top_buy
                orders.append(Order(product, int(final_bid), top_buy))
                if deep_buy > 0:
                    orders.append(Order(product, int(final_bid - 1), deep_buy))

            if rem_sell > 0:
                top_sell = min(rem_sell, math.ceil(rem_sell * 0.68))
                deep_sell = rem_sell - top_sell
                orders.append(Order(product, int(final_ask), -top_sell))
                if deep_sell > 0:
                    orders.append(Order(product, int(final_ask + 1), -deep_sell))

            result[product] = orders

        # PEPPER v2 (balanced aggressive)
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
                target = 26
            elif regime == "down":
                target = -26

            buy_edge = 1.05
            sell_edge = 1.05
            if regime == "up":
                buy_edge = 0.6
                sell_edge = 1.8
            elif regime == "down":
                buy_edge = 1.8
                sell_edge = 0.6

            # Soft rails
            if position >= 68:
                buy_cap = 0
            if position <= -68:
                sell_cap = 0

            # Emergency de-risk: when inventory is stretched, allow easier exits.
            if position > 50:
                sell_edge = min(sell_edge, 0.45)
            if position < -50:
                buy_edge = min(buy_edge, 0.45)

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
            bias = max(-1.9, min(1.9, gap / 15.0))

            passive_bid = min(best_bid + 1, int(math.floor(fair - 1.2 + bias)))
            passive_ask = max(best_ask - 1, int(math.ceil(fair + 1.2 + bias)))

            if buy_cap > 0:
                buy_qty = min(buy_cap, 28 if gap > 0 else 12)
                if position >= 56:
                    buy_qty = min(buy_qty, 6)
                if buy_qty > 0:
                    orders.append(Order(product, passive_bid, buy_qty))

            if sell_cap > 0:
                sell_qty = min(sell_cap, 28 if gap < 0 else 12)
                if position <= -56:
                    sell_qty = min(sell_qty, 6)
                if sell_qty > 0:
                    orders.append(Order(product, passive_ask, -sell_qty))

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
