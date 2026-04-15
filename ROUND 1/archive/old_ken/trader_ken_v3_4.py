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
    trader_ken v3.4 (live-oriented)
    - More taker-selective execution
    - Reduced dependence on deep passive layers
    - Pepper includes tactical shorting on rich quotes
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

        tape_adj = math.copysign(min(abs(tape_volume) * 0.16, 2.8), tape_volume)
        mid_pull = max(-0.7, min(0.7, (mid - 10000.0) * 0.10))
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

        flow = 0
        if product in state.market_trades and state.market_trades[product]:
            for trade in state.market_trades[product]:
                flow += trade.quantity if trade.price >= mid else -trade.quantity

        if flow != 0:
            d1 = 1 if prediction > mid else -1
            d2 = 1 if flow > 0 else -1
            if d1 == d2:
                prediction += d1 * 0.8

        return prediction

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ---- Osmium ----
        product = "ASH_COATED_OSMIUM"
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            fair = self.get_osmium_fair(state)
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
            spread = max(1, best_ask - best_bid)
            orders: List["Order"] = []

            rem_buy = limit - position
            rem_sell = limit + position

            # Favor high-quality taker fills.
            take_margin = 2.6 if spread <= 2 else 3.0
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

            # Keep only one passive level (live-friendly).
            skew = 0.06 if abs(position) >= 40 else 0.04
            bid_px = min(best_bid + 1, math.floor(fair - 0.6 - position * skew))
            ask_px = max(best_ask - 1, math.ceil(fair + 0.6 - position * skew))
            bid_px = min(bid_px, math.floor(fair - 0.5))
            ask_px = max(ask_px, math.ceil(fair + 0.5))

            if rem_buy > 0:
                orders.append(Order(product, int(bid_px), rem_buy))
            if rem_sell > 0:
                orders.append(Order(product, int(ask_px), -rem_sell))
            result[product] = orders

        # ---- Pepper ----
        product = "INTARIAN_PEPPER_ROOT"
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            buy_cap = limit - position
            sell_cap = limit + position
            fair = self.get_pepper_fair(state)
            orders: List["Order"] = []

            # Buy only with edge, not all asks.
            entry_buffer = 0.9 if position < 50 else 1.3
            for ask in sorted(depth.sell_orders.keys()):
                if buy_cap <= 0:
                    break
                if ask <= fair - entry_buffer:
                    qty = min(abs(depth.sell_orders[ask]), buy_cap, 35)
                    orders.append(Order(product, ask, qty))
                    buy_cap -= qty
                else:
                    break

            # Tactical shorting for overextended rich bids.
            short_buffer = 2.8 if position > -20 else 2.2
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if sell_cap <= 0:
                    break
                if bid >= fair + short_buffer:
                    qty = min(abs(depth.buy_orders[bid]), sell_cap, 30)
                    orders.append(Order(product, bid, -qty))
                    sell_cap -= qty
                else:
                    break

            # Single passive quote each side.
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(fair - 1)
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(fair + 1)

            passive_bid = min(best_bid + 1, int(math.floor(fair - 1.0)))
            passive_ask = max(best_ask - 1, int(math.ceil(fair + 1.0)))

            if buy_cap > 0 and position < 65:
                orders.append(Order(product, passive_bid, min(buy_cap, 30)))
            if sell_cap > 0:
                orders.append(Order(product, passive_ask, -min(sell_cap, 30)))

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
