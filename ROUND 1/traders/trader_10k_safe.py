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
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 80,
            'INTARIAN_PEPPER_ROOT': 80
        }

        # 3-lag regression weights for Pepper Root
        self.sf_weights = [0.34296, 0.32058, 0.33645]
        self.sf_intercept = 0.2535

        self.history = {}

    def update_history(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except:
                self.history = {}

    def get_osmium_fair(self, state: TradingState) -> float:
        product = 'ASH_COATED_OSMIUM'
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

        tape_adj = math.copysign(min(abs(tape_volume) * 0.15, 2.5), tape_volume)
        return 10000.0 + tape_adj

    def get_pepper_fair(self, state: TradingState) -> float:
        product = 'INTARIAN_PEPPER_ROOT'
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None

        if best_bid is None and best_ask is None:
            return self.history.get('_pepper_last', 0.0)

        mid = ((best_bid or best_ask) + (best_ask or best_bid)) / 2.0
        self.history['_pepper_last'] = mid

        hist = self.history.get(product, [])
        if not isinstance(hist, list):
            hist = []

        hist.append(mid)
        if len(hist) > 10:  # Increased history for trend detection
            hist = hist[-10:]
        self.history[product] = hist

        if len(hist) < 3:
            return mid

        prediction = self.sf_intercept
        # Use last 3 for regression as before
        regression_hist = hist[-3:]
        for i in range(3):
            prediction += self.sf_weights[i] * regression_hist[-(i + 1)]

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
                prediction += direction * 1.0

        return prediction

    def get_pepper_trend_safe(self, state: TradingState, mid: float) -> float:
        product = 'INTARIAN_PEPPER_ROOT'
        hist = self.history.get(product, [])
        if len(hist) < 10:
            return 1.0  # Full aggression during warm-up
        
        # Simple Moving Average for trend detection
        sma = sum(hist) / len(hist)
        
        # If price starts dipping below SMA, reduce aggression
        # 0.5 = neutral, 1.0 = aggressive, 0.0 = emergency exit
        if mid < sma - 2.0:
            return 0.0  # Emergency: exit long position
        elif mid < sma:
            return 0.4  # Defensive: reduce buying
        return 1.0      # Bullish: full buy

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ── ASH_COATED_OSMIUM ──────────────────
        product = 'ASH_COATED_OSMIUM'
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

        # ── INTARIAN_PEPPER_ROOT: Safe Mode ────────────────
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            
            fair = self.get_pepper_fair(state)
            mid = self.history.get('_pepper_last', fair)
            aggression = self.get_pepper_trend_safe(state, mid)
            
            orders = []
            
            # SAFE BUYING: Scale cap by trend aggression
            target_buy_limit = int(limit * aggression)
            buy_cap = max(0, target_buy_limit - position)
            sell_cap = limit + position

            # Only buy if aggression > 0
            if aggression > 0:
                for ask in sorted(depth.sell_orders.keys()):
                    if buy_cap <= 0:
                        break
                    # Simulation has wide spreads (fair + 6.5). 
                    # Set filter to 7.0 to allow fills while still blocking extreme spikes.
                    if ask > fair + 7.0:
                        break
                    qty = min(abs(depth.sell_orders[ask]), buy_cap)
                    orders.append(Order(product, ask, qty))
                    buy_cap -= qty

                if buy_cap > 0 and depth.buy_orders:
                    best_bid = max(depth.buy_orders.keys())
                    orders.append(Order(product, best_bid + 1, buy_cap))

            # SAFE SELLING: If emergency (aggression == 0), dump everything at best bid
            if aggression == 0 and position > 0:
                for bid in sorted(depth.buy_orders.keys(), reverse=True):
                    if position <= 0: break
                    qty = min(position, abs(depth.buy_orders[bid]))
                    orders.append(Order(product, bid, -qty))
                    position -= qty
            else:
                # Normal profit taking: more aggressive than v1
                for bid in sorted(depth.buy_orders.keys(), reverse=True):
                    if bid > fair + 1.0 and sell_cap > 0: 
                        qty = min(abs(depth.buy_orders[bid]), sell_cap)
                        orders.append(Order(product, bid, -qty))
                        sell_cap -= qty
                    else:
                        break

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
