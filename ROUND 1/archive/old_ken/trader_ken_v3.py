import json
import math
from typing import Any, Dict, List

from datamodel import Order, TradingState, Symbol


class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        conversions: int,
        trader_data: str,
    ) -> None:
        pass


logger = Logger()


class Trader:
    """
    trader_ken v3
    - Osmium: proven anchored sniper + pennying core
    - Pepper: regime-aware position targeting (trend vs neutral)
    - Goal: avoid getting stuck at max inventory while staying profitable
    """

    def __init__(self):
        self.limits = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
        self.pepper_weights = [0.34296, 0.32058, 0.33645]
        self.pepper_intercept = 0.2535
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

    def _pepper_mid_and_history(self, state: TradingState) -> float:
        product = "INTARIAN_PEPPER_ROOT"
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None

        if best_bid is None and best_ask is None:
            return float(self.history.get("_pepper_last", 12000.0))

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

        return mid

    def get_pepper_fair(self, state: TradingState) -> float:
        mid = self._pepper_mid_and_history(state)
        short_hist = self.history.get("pepper_short_hist", [])
        if len(short_hist) < 3:
            return mid

        prediction = self.pepper_intercept
        for i in range(3):
            prediction += self.pepper_weights[i] * short_hist[-(i + 1)]

        momentum = 0
        product = "INTARIAN_PEPPER_ROOT"
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
                prediction += direction * 0.9

        return prediction

    def _pepper_regime(self) -> str:
        long_hist = self.history.get("pepper_long_hist", [])
        if len(long_hist) < 6:
            return "neutral"

        recent = long_hist[-1]
        past = long_hist[-6]
        slope = (recent - past) / 5.0

        if slope > 0.45:
            return "uptrend"
        if slope < -0.45:
            return "downtrend"
        return "neutral"

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ---------------- OSMIUM (unchanged core) ----------------
        product = "ASH_COATED_OSMIUM"
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
            fair = self.get_osmium_fair(state)
            orders: List[Order] = []

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

        # ---------------- PEPPER (v3 regime-aware) ----------------
        product = "INTARIAN_PEPPER_ROOT"
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            buy_cap = limit - position
            sell_cap = limit + position
            fair = self.get_pepper_fair(state)
            regime = self._pepper_regime()
            orders: List[Order] = []

            # Set position targets by regime (do not always chase +80).
            target_pos = 0
            if regime == "uptrend":
                target_pos = 45
            elif regime == "downtrend":
                target_pos = -45

            # Aggressive takes with regime-aware thresholds.
            buy_take_threshold = fair - (0.4 if regime == "uptrend" else 0.8)
            sell_take_threshold = fair + (1.8 if regime == "uptrend" else 1.2)
            if regime == "downtrend":
                buy_take_threshold = fair - 1.2
                sell_take_threshold = fair + 0.4

            for ask, vol in sorted(depth.sell_orders.items()):
                if buy_cap <= 0:
                    break
                # Only scale into longs above target in strong uptrend.
                if position >= target_pos and regime != "uptrend":
                    break
                if ask <= buy_take_threshold:
                    qty = min(abs(vol), buy_cap, 25)
                    if qty > 0:
                        orders.append(Order(product, ask, qty))
                        buy_cap -= qty
                        position += qty
                else:
                    break

            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if sell_cap <= 0:
                    break
                if position <= target_pos and regime != "downtrend":
                    break
                if bid >= sell_take_threshold:
                    qty = min(abs(vol), sell_cap, 25)
                    if qty > 0:
                        orders.append(Order(product, bid, -qty))
                        sell_cap -= qty
                        position -= qty
                else:
                    break

            # Passive quotes around fair that nudge position toward target.
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(fair - 1)
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(fair + 1)

            pos_gap = target_pos - position
            # Positive gap => we want more long inventory; negative => more short.
            bias = max(-2.0, min(2.0, pos_gap / 20.0))

            passive_bid = min(best_bid + 1, int(math.floor(fair - 0.8 + bias)))
            passive_ask = max(best_ask - 1, int(math.ceil(fair + 0.9 + bias)))

            if buy_cap > 0:
                buy_qty = min(buy_cap, 35 if pos_gap > 0 else 20)
                if buy_qty > 0:
                    orders.append(Order(product, passive_bid, buy_qty))
            if sell_cap > 0:
                sell_qty = min(sell_cap, 35 if pos_gap < 0 else 20)
                if sell_qty > 0:
                    orders.append(Order(product, passive_ask, -sell_qty))

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
