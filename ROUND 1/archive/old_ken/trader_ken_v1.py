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
        orders: Dict[Symbol, List[Order]],
        conversions: int,
        trader_data: str,
    ) -> None:
        # Keep empty for low portal output overhead
        pass


logger = Logger()


class Trader:
    """
    trader_ken v1
    - ASH_COATED_OSMIUM: anchored MM + tape-adjusted fair
    - INTARIAN_PEPPER_ROOT: 3-lag autoregressive fair + momentum confluence
    - Added inventory guardrails to reduce max-position trap risk
    """

    def __init__(self):
        self.limits = {
            "ASH_COATED_OSMIUM": 80,
            "INTARIAN_PEPPER_ROOT": 80,
        }
        self.pepper_weights = [0.34296, 0.32058, 0.33645]
        self.pepper_intercept = 0.2535
        self.history: Dict[str, Any] = {}

    def update_history(self, trader_data: str) -> None:
        if not trader_data:
            return
        try:
            parsed = json.loads(trader_data)
            if isinstance(parsed, dict):
                self.history = parsed
        except Exception:
            self.history = {}

    def _best_bid_ask(self, state: TradingState, product: str):
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return best_bid, best_ask

    def get_osmium_fair(self, state: TradingState) -> float:
        product = "ASH_COATED_OSMIUM"
        best_bid, best_ask = self._best_bid_ask(state, product)
        _ = (best_bid, best_ask)

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
        best_bid, best_ask = self._best_bid_ask(state, product)

        if best_bid is None and best_ask is None:
            return float(self.history.get("_pepper_last", 12000.0))

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

        prediction = self.pepper_intercept
        for i in range(3):
            prediction += self.pepper_weights[i] * hist[-(i + 1)]

        momentum = 0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= mid:
                    momentum += trade.quantity
                else:
                    momentum -= trade.quantity

        if momentum != 0:
            flow_dir = 1 if momentum > 0 else -1
            pred_dir = 1 if prediction > mid else -1
            if flow_dir == pred_dir:
                prediction += flow_dir * 0.8

        return prediction

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result: Dict[str, List[Order]] = {}

        # ---------------- OSMIUM ----------------
        osmium = "ASH_COATED_OSMIUM"
        if osmium in state.order_depths:
            depth = state.order_depths[osmium]
            pos = state.position.get(osmium, 0)
            limit = self.limits[osmium]
            fair = self.get_osmium_fair(state)
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
            orders: List[Order] = []

            rem_buy = limit - pos
            rem_sell = limit + pos

            # Snipe mispricings first
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - 2.2 and rem_buy > 0:
                    qty = min(rem_buy, -vol)
                    orders.append(Order(osmium, int(ask), qty))
                    rem_buy -= qty
                    pos += qty

            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + 2.2 and rem_sell > 0:
                    qty = min(rem_sell, vol)
                    orders.append(Order(osmium, int(bid), -qty))
                    rem_sell -= qty
                    pos -= qty

            # Passive queue-jump with soft inventory skew
            skew = 0.05
            bid_price = math.floor(fair - 0.5 - (pos * skew))
            ask_price = math.ceil(fair + 0.5 - (pos * skew))

            final_bid = min(best_bid + 1, bid_price)
            final_ask = max(best_ask - 1, ask_price)
            final_bid = min(final_bid, math.floor(fair - 0.5))
            final_ask = max(final_ask, math.ceil(fair + 0.5))

            # Guardrail: once near limit, bias passive quotes toward unwind
            if pos >= 60:
                final_bid -= 1
                final_ask -= 1
            elif pos <= -60:
                final_bid += 1
                final_ask += 1

            if rem_buy > 0:
                orders.append(Order(osmium, int(final_bid), rem_buy))
            if rem_sell > 0:
                orders.append(Order(osmium, int(final_ask), -rem_sell))

            result[osmium] = orders

        # ---------------- PEPPER ----------------
        pepper = "INTARIAN_PEPPER_ROOT"
        if pepper in state.order_depths:
            depth = state.order_depths[pepper]
            pos = state.position.get(pepper, 0)
            limit = self.limits[pepper]
            fair = self.get_pepper_fair(state)
            orders: List[Order] = []

            buy_cap = limit - pos
            sell_cap = limit + pos

            # Entry: buy only if ask is below fair with buffer
            for ask, vol in sorted(depth.sell_orders.items()):
                if buy_cap <= 0:
                    break
                if ask <= fair - 0.6:
                    qty = min(buy_cap, -vol)
                    orders.append(Order(pepper, int(ask), qty))
                    buy_cap -= qty
                else:
                    break

            # Exit: take strong bids above fair
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if sell_cap <= 0:
                    break
                if bid >= fair + 2.4:
                    qty = min(sell_cap, vol)
                    orders.append(Order(pepper, int(bid), -qty))
                    sell_cap -= qty
                else:
                    break

            # Passive participation with unwind pressure near extremes
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(fair - 1)
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(fair + 1)

            passive_bid = min(best_bid + 1, int(math.floor(fair - 0.8)))
            passive_ask = max(best_ask - 1, int(math.ceil(fair + 1.2)))

            if pos >= 60:
                # near max long -> stop chasing buys, lean into exits
                buy_cap = min(buy_cap, 5)
                passive_ask -= 1
            elif pos <= -60:
                # near max short -> stop chasing sells, lean into covers
                sell_cap = min(sell_cap, 5)
                passive_bid += 1

            if buy_cap > 0:
                orders.append(Order(pepper, passive_bid, buy_cap))
            if sell_cap > 0:
                orders.append(Order(pepper, passive_ask, -sell_cap))

            result[pepper] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
