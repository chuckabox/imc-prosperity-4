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
    ken_pepper_v4
    - Osmium: v6.6 baseline
    - Pepper: capital-preservation mode (earlier rails + emergency unwind)
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

        hist = self.history.get(product, [])
        if not isinstance(hist, list):
            hist = []
        hist.append(mid)
        if len(hist) > 3:
            hist = hist[-3:]
        self.history[product] = hist

        if len(hist) < 3:
            return mid

        prediction = self.sf_intercept
        for i in range(3):
            prediction += self.sf_weights[i] * hist[-(i + 1)]

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
                prediction += direction * 0.85

        return prediction

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # OSMIUM: v6.6 baseline
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

        # PEPPER: original core + strong safety rails
        product = "INTARIAN_PEPPER_ROOT"
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            buy_cap = limit - position
            sell_cap = limit + position
            fair = self.get_pepper_fair(state)
            orders: List["Order"] = []

            # Original accumulation, but taper adds as inventory grows.
            if position >= 60:
                buy_clip_cap = 4
            elif position >= 50:
                buy_clip_cap = 10
            else:
                buy_clip_cap = 80

            for ask in sorted(depth.sell_orders.keys()):
                if buy_cap <= 0:
                    break
                qty = min(abs(depth.sell_orders[ask]), buy_cap, buy_clip_cap)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    buy_cap -= qty
                    position += qty

            # Resting bid scaled down near long limits.
            if buy_cap > 0 and depth.buy_orders:
                best_bid = max(depth.buy_orders.keys())
                if position >= 60:
                    rest_bid_qty = min(buy_cap, 3)
                elif position >= 50:
                    rest_bid_qty = min(buy_cap, 8)
                else:
                    rest_bid_qty = buy_cap
                if rest_bid_qty > 0:
                    orders.append(Order(product, best_bid + 1, rest_bid_qty))

            # Emergency unwind mode near limits.
            near_long = position >= 55
            near_short = position <= -55

            if near_long:
                # Sell on smaller upside edge to escape large long.
                spike_edge = 1.2
            elif near_short:
                # Mirror if short-heavy.
                spike_edge = 1.2
            else:
                spike_edge = 3.0

            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid > fair + spike_edge and sell_cap > 0:
                    qty = min(abs(depth.buy_orders[bid]), sell_cap)
                    # In emergency mode, force larger unwind clips.
                    if near_long:
                        qty = min(qty, 28)
                    orders.append(Order(product, bid, -qty))
                    sell_cap -= qty
                    position -= qty
                else:
                    break

            # If very short, allow cheaper buyback (symmetry safeguard).
            if near_short:
                for ask in sorted(depth.sell_orders.keys()):
                    if buy_cap <= 0:
                        break
                    if ask < fair - 1.2:
                        qty = min(abs(depth.sell_orders[ask]), buy_cap, 28)
                        orders.append(Order(product, ask, qty))
                        buy_cap -= qty
                        position += qty
                    else:
                        break

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
