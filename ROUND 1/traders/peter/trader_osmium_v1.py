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

        # 3-lag regression weights for Pepper Root (Trend following)
        self.sf_weights = [0.34296, 0.32058, 0.33645]
        self.sf_intercept = 0.2535
        
        # Osmium Constants (from analysis)
        self.OSMIUM_ANCHOR = 10000.0
        self.OSMIUM_STD = 5.7

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
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else self.OSMIUM_ANCHOR
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else self.OSMIUM_ANCHOR
        mid = (best_bid + best_ask) / 2.0

        # Pattern 2: High variance around 10k, but hidden pattern exists.
        # We use a slight tape adjustment for bias.
        tape_volume = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= mid:
                    tape_volume += trade.quantity
                else:
                    tape_volume -= trade.quantity

        tape_adj = math.copysign(min(abs(tape_volume) * 0.2, 3.0), tape_volume)
        return self.OSMIUM_ANCHOR + tape_adj

    def get_pepper_fair(self, state: TradingState) -> float:
        product = 'INTARIAN_PEPPER_ROOT'
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None

        if best_bid is None and best_ask is None:
            return self.history.get('_pepper_last', 12500.0)

        mid = ((best_bid or best_ask) + (best_ask or best_bid)) / 2.0
        self.history['_pepper_last'] = mid

        hist = self.history.get(product, [])
        if not isinstance(hist, list): hist = []
        hist.append(mid)
        if len(hist) > 20: hist = hist[-20:]
        self.history[product] = hist

        if len(hist) < 3: return mid

        # Regression for trend
        prediction = self.sf_intercept
        regression_hist = hist[-3:]
        for i in range(3):
            prediction += self.sf_weights[i] * regression_hist[-(i + 1)]
        
        return prediction

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ── ASH_COATED_OSMIUM: Aggressive Market Making ──
        product = 'ASH_COATED_OSMIUM'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            fair = self.get_osmium_fair(state)
            
            orders: List[Order] = []
            rem_buy = limit - position
            rem_sell = limit + position
            
            # Z-Score Taker Logic (Z > 2.0)
            z_score = (fair - self.OSMIUM_ANCHOR) / self.OSMIUM_STD
            
            # 1. TAKER PHASE
            # If price is far from fair, we take aggressively to bring inventory into play
            take_margin = 1.0 # Very tight for high precision
            for ask, vol in sorted(depth.sell_orders.items()):
                # If ask is cheap relative to fair, buy
                if ask <= fair - take_margin and rem_buy > 0:
                    qty = min(rem_buy, -vol)
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty
                    position += qty
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                # If bid is expensive relative to fair, sell
                if bid >= fair + take_margin and rem_sell > 0:
                    qty = min(rem_sell, vol)
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty
                    position -= qty

            # 2. AGGRESSIVE MAKER PHASE
            # We sit 1 point inside the best quotes but always centered on fair
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(fair - 1)
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(fair + 1)
            
            skew = -0.1 * position # Inventory skew
            bid_price = math.floor(fair - 1.0 + skew)
            ask_price = math.ceil(fair + 1.0 + skew)
            
            # Pennying the spread
            final_bid = min(best_bid + 1, bid_price)
            final_ask = max(best_ask - 1, ask_price)
            
            # Safety: Don't cross fair
            final_bid = min(final_bid, math.floor(fair))
            final_ask = max(final_ask, math.ceil(fair))
            
            if rem_buy > 0:
                orders.append(Order(product, int(final_bid), rem_buy))
            if rem_sell > 0:
                orders.append(Order(product, int(final_ask), -rem_sell))
            result[product] = orders

        # ── INTARIAN_PEPPER_ROOT: Trend Following ────────────────
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            fair = self.get_pepper_fair(state)
            
            orders = []
            rem_buy = limit - position
            rem_sell = limit + position
            
            # Taker (aggressive) if predicted trend is strong
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - 1.0 and rem_buy > 0:
                    qty = min(rem_buy, -vol)
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty
                    position += qty
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + 1.0 and rem_sell > 0:
                    qty = min(rem_sell, vol)
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty
                    position -= qty

            # Passive placement
            if rem_buy > 0:
                bid_price = math.floor(fair - 1.5)
                orders.append(Order(product, int(bid_price), rem_buy))
            if rem_sell > 0:
                ask_price = math.ceil(fair + 1.5)
                orders.append(Order(product, int(ask_price), -rem_sell))

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
