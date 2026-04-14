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
        # Logs are optional for local, essential for portal
        pass

logger = Logger()

class Trader:
    """
    Antigravity Round 1 Optimized Strategy (trader_peter2)
    -----------------------------------------------------
    - ASH_COATED_OSMIUM (Amethyst): Fixed-point mean reversion at 10,000.
    - INTARIAN_PEPPER_ROOT (Starfruit): 3-Lag Linear Regression Forecast.
    - Execution: Aggressive liquidity taking + Inventory-aware quoting.
    """
    
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 20,
            'INTARIAN_PEPPER_ROOT': 20
        }
        # Multi-lag regression coefficients for Starfruit
        self.sf_coeffs = [0.34296, 0.32058, 0.33645] 
        self.sf_intercept = 0.2535
        
        self.history = {}
        self.traderData = ""

    def update_history(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except:
                self.history = {}

    def get_fair_price(self, product: str, mid_price: float) -> float:
        if product == 'ASH_COATED_OSMIUM':
            return 10000.0
            
        if product == 'INTARIAN_PEPPER_ROOT':
            # Maintain a list of last 3 mid-prices
            prices = self.history.get(product, [])
            if not isinstance(prices, list): prices = []
            
            prices.append(mid_price)
            if len(prices) > 3:
                prices = prices[-3:]
            
            self.history[product] = prices
            
            if len(prices) < 3:
                return mid_price
            
            # Predict next mid: Intercept + W0*P(t) + W1*P(t-1) + W2*P(t-2)
            # Weights from analysis: [0.34296, 0.32058, 0.33645]
            prediction = self.sf_intercept
            for i in range(3):
                prediction += self.sf_coeffs[i] * prices[-(i+1)]
            
            return prediction
            
        return mid_price

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}
        
        for product in ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT']:
            if product not in state.order_depths:
                continue
                
            depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            
            position = state.position.get(product, 0)
            product_limit = self.limits[product]
            
            buy_orders = depth.buy_orders
            sell_orders = depth.sell_orders
            
            if not buy_orders or not sell_orders:
                continue
                
            best_bid = max(buy_orders.keys())
            best_ask = min(sell_orders.keys())
            mid_price = (best_bid + best_ask) / 2.0
            
            # --- 1. Signal Generation ---
            fair_price = self.get_fair_price(product, mid_price)
            
            # --- 2. Aggressive Liquidity Taking ---
            max_buy_qty = product_limit - position
            for ask, vol in sorted(sell_orders.items()):
                # Dynamic buffer for Starfruit to avoid adverse selection
                buffer = 0.5 if product == 'ASH_COATED_OSMIUM' else 1.0 
                if ask <= fair_price - buffer and max_buy_qty > 0:
                    qty = min(max_buy_qty, -vol)
                    orders.append(Order(product, ask, qty))
                    max_buy_qty -= qty
                    position += qty
            
            max_sell_qty = product_limit + position
            for bid, vol in sorted(buy_orders.items(), reverse=True):
                buffer = 0.5 if product == 'ASH_COATED_OSMIUM' else 1.0
                if bid >= fair_price + buffer and max_sell_qty > 0:
                    qty = min(max_sell_qty, vol)
                    orders.append(Order(product, bid, -qty))
                    max_sell_qty -= qty
                    position -= qty
            
            # --- 3. Passive Market Making (Pennying) ---
            # Skew quotes to encourage position reduction
            inventory_skew = 0.3 if product == 'INTARIAN_PEPPER_ROOT' else 0.1
            
            bid_price = math.floor(fair_price - 1 - (position * inventory_skew))
            ask_price = math.ceil(fair_price + 1 - (position * inventory_skew))
            
            # Pennying logic: capture the spread but don't cross fair
            final_bid_price = min(best_bid + 1, bid_price)
            final_ask_price = max(best_ask - 1, ask_price)
            
            # Final sanity check: don't quote past fair
            final_bid_price = min(final_bid_price, math.floor(fair_price - 0.5))
            final_ask_price = max(final_ask_price, math.ceil(fair_price + 0.5))
            
            # Place Limit Orders
            rem_buy = product_limit - position
            if rem_buy > 0:
                orders.append(Order(product, int(final_bid_price), rem_buy))
                
            rem_sell = product_limit + position
            if rem_sell > 0:
                orders.append(Order(product, int(final_ask_price), -rem_sell))
                
            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
