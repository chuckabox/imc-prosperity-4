import json
import math
from typing import Dict, List, Any
from datamodel import Order, OrderDepth, TradingState, Symbol

class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: Dict[Symbol, List[Order]], conversions: int, trader_data: str) -> None:
        pass

logger = Logger()

class Trader:
    """
    Antigravity Round 1 High-Frequency Optimized Strategy (trader_peter2_2)
    ----------------------------------------------------------------------
    - Goal: Break the 9k barrier with a 20-unit limit.
    - Strategy: Aggressive Pennying + Tape-Aware Sniping.
    - Limits: Hard 20-unit constraint.
    - Execution: 0.5-tick buffers for maximum fill probability.
    """

    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 20,
            'INTARIAN_PEPPER_ROOT': 20
        }

        # Proven Starfruit Signal (3-Lag Regression)
        self.sf_weights = [0.34296, 0.32058, 0.33645]
        self.sf_intercept = 0.2535

        self.history = {}
        self.traderData = ""

    def update_history(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except:
                self.history = {}

    def get_fair_price(self, product: str, state: TradingState) -> float:
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
        mid_price = (best_bid + best_ask) / 2.0

        # Tape Reading Influence (Aggressive)
        tape_volume = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= mid_price: tape_volume += trade.quantity
                else: tape_volume -= trade.quantity
        # Scale to 2.5 ticks max. Volume confirm price hunger
        tape_adj = math.copysign(min(abs(tape_volume) * 0.15, 2.5), tape_volume)

        if product == 'ASH_COATED_OSMIUM':
            return 10000.0 + tape_adj

        if product == 'INTARIAN_PEPPER_ROOT':
            hist = self.history.get(product, [])
            if not isinstance(hist, list): hist = []

            hist.append(mid_price)
            if len(hist) > 3: hist = hist[-3:]
            self.history[product] = hist

            if len(hist) < 3: return mid_price + tape_adj

            # Regression prediction BASELINE
            prediction = self.sf_intercept
            for i in range(3):
                prediction += self.sf_weights[i] * hist[-(i+1)]

            # VOLUME MOMENTUM ADJUSTMENT: Only trust if volume confirm
            momentum = 0
            if product in state.market_trades and state.market_trades[product]:
                for trade in state.market_trades[product]:
                    if trade.price >= mid_price: momentum += trade.quantity
                    else: momentum -= trade.quantity

            # If prediction say UP but volume say DOWN = stay neutral
            # If prediction say UP AND volume say UP = go aggressive
            if momentum != 0:
                direction = 1 if momentum > 0 else -1
                pred_direction = 1 if prediction > mid_price else -1
                if direction == pred_direction:  # CONFLUENCE
                    prediction += direction * 1.0  # Extra tick confidence

            return prediction + tape_adj

        return mid_price

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        for product in self.limits.keys():
            if product not in state.order_depths: continue

            depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            position = state.position.get(product, 0)
            limit = self.limits[product]

            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 0
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 0
            if not best_bid or not best_ask: continue

            fair_price = self.get_fair_price(product, state)

            # 1. Sniper Mode
            # Tighter thresholds for higher fill rate
            take_margin = 2.5 if product == 'ASH_COATED_OSMIUM' else 2.0

            rem_buy = limit - position
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair_price - take_margin and rem_buy > 0:
                    qty = min(rem_buy, -vol)
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty
                    position += qty

            rem_sell = limit + position
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair_price + take_margin and rem_sell > 0:
                    qty = min(rem_sell, vol)
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty
                    position -= qty

            # 2. Aggressive Maker (Pennying)
            # Softer skew factor for tighter spreads and more fills
            skew_factor = 0.2

            bid_price = math.floor(fair_price - 0.5 - (position * skew_factor))
            ask_price = math.ceil(fair_price + 0.5 - (position * skew_factor))

            # Absolute Pennying: Try to be #1 in the queue
            final_bid = min(best_bid + 1, bid_price)
            final_ask = max(best_ask - 1, ask_price)

            # Safety: don't quote past fair
            final_bid = min(final_bid, math.floor(fair_price - 0.5))
            final_ask = max(final_ask, math.ceil(fair_price + 0.5))

            rem_buy = limit - position
            if rem_buy > 0:
                orders.append(Order(product, int(final_bid), rem_buy))

            rem_sell = limit + position
            if rem_sell > 0:
                orders.append(Order(product, int(final_ask), -rem_sell))

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
