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

        # 3-lag regression weights for Pepper Root (Trend tracking)
        self.sf_weights = [0.34296, 0.32058, 0.33645]
        self.sf_intercept = 0.2535
        
        # Osmium Constants (Locked to 10k for robustness)
        self.OSMIUM_ANCHOR = 10000.0

        self.history = {}

    def update_history(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except:
                self.history = {}

    def get_osmium_fair(self, state: TradingState) -> float:
        # Standard 10k anchor. No tape adjustments to avoid overfitting.
        return self.OSMIUM_ANCHOR

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
        if len(hist) > 10: hist = hist[-10:]
        self.history[product] = hist

        if len(hist) < 3: return mid

        prediction = self.sf_intercept
        regression_hist = hist[-3:]
        for i in range(3):
            prediction += self.sf_weights[i] * regression_hist[-(i + 1)]
        
        return prediction

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ── ASH_COATED_OSMIUM: Stable Mean Reversion ──
        product = 'ASH_COATED_OSMIUM'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            fair = self.get_osmium_fair(state)
            
            orders: List[Order] = []
            rem_buy = limit - position
            rem_sell = limit + position
            
            # Taker buffer: 5.0 (High edge requirement)
            take_margin = 5.0 
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

            # Passive Market Making with Inventory Skew
            # This is the "Pattern 2" capture: harvesting the 16-22 point spread.
            skew = -0.1 * position 
            bid_price = math.floor(fair - 2.0 + skew) # 2.0 margin for safety
            ask_price = math.ceil(fair + 2.0 + skew)
            
            if rem_buy > 0:
                orders.append(Order(product, int(bid_price), rem_buy))
            if rem_sell > 0:
                orders.append(Order(product, int(ask_price), -rem_sell))
            result[product] = orders

        # ── INTARIAN_PEPPER_ROOT: Robust Trend ──
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            fair = self.get_pepper_fair(state)
            
            orders = []
            rem_buy = limit - position
            rem_sell = limit + position
            
            # Taker edge: 1.5
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - 1.5 and rem_buy > 0:
                    qty = min(rem_buy, -vol)
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty
                    position += qty
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + 1.5 and rem_sell > 0:
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
