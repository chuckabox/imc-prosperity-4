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
        # We disable print to save log space in the competition
        pass

logger = Logger()

class Trader:
    """
    Antigravity Round 1 Leaderboard Strategy
    -----------------------------------------
    - ASH_COATED_OSMIUM: Fixed-point mean reversion based on historical 10,000 anchor.
    - INTARIAN_PEPPER_ROOT: Dynamic EMA-based mean reversion with responsiveness.
    - Execution: Multi-layered liquidity taking followed by inventory-skewed pennying.
    """
    
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 20,
            'INTARIAN_PEPPER_ROOT': 20
        }
        self.ema_alphas = {
            'INTARIAN_PEPPER_ROOT': 0.15,
            'ASH_COATED_OSMIUM': 0.05
        }
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
            return 10000.0  # Proven stable anchor
            
        if product not in self.history:
            self.history[product] = mid_price
            return mid_price
            
        alpha = self.ema_alphas.get(product, 0.1)
        prev_ema = self.history[product]
        new_ema = (alpha * mid_price) + (1 - alpha) * prev_ema
        self.history[product] = new_ema
        return new_ema

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
            
            # Extract basic market stats
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
            # Buying (Sweeping asks below fair)
            max_buy_qty = product_limit - position
            for ask, vol in sorted(sell_orders.items()):
                # Use a small buffer to ensure profit after spread/drift
                buffer = 0.6 if product == 'ASH_COATED_OSMIUM' else 1.5
                if ask <= fair_price - buffer and max_buy_qty > 0:
                    qty = min(max_buy_qty, -vol)
                    orders.append(Order(product, ask, qty))
                    max_buy_qty -= qty
                    position += qty
            
            # Selling (Sweeping bids above fair)
            max_sell_qty = product_limit + position
            for bid, vol in sorted(buy_orders.items(), reverse=True):
                buffer = 0.6 if product == 'ASH_COATED_OSMIUM' else 1.5
                if bid >= fair_price + buffer and max_sell_qty > 0:
                    qty = min(max_sell_qty, vol)
                    orders.append(Order(product, bid, -qty))
                    max_sell_qty -= qty
                    position -= qty
            
            # --- 3. Passive Market Making (Pennying) ---
            # Calculate position-shifted 'ideal' prices to manage inventory risk
            inventory_skew = 0.2  # 1 tick shift for every 5 units of position
            res_buy = math.floor(fair_price - 1 - (position * inventory_skew))
            res_sell = math.ceil(fair_price + 1 - (position * inventory_skew))
            
            final_bid_price = min(best_bid + 1, res_buy)
            final_ask_price = max(best_ask - 1, res_sell)
            
            # Safety check: Ensure we don't market make past our fair value estimate
            final_bid_price = min(final_bid_price, math.floor(fair_price - 0.5))
            final_ask_price = max(final_ask_price, math.ceil(fair_price + 0.5))
            
            # Place Limit Orders
            pending_buy = product_limit - position
            if pending_buy > 0:
                orders.append(Order(product, int(final_bid_price), pending_buy))
                
            pending_sell = product_limit + position
            if pending_sell > 0:
                orders.append(Order(product, int(final_ask_price), -pending_sell))
                
            result[product] = orders

        # Persist history for the next tick
        trader_data = json.dumps(self.history)
        
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
