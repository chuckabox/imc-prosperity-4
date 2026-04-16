import json
import math
import numpy as np
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
    Robust Generalizable Trader.
    - No hardcoded constant price anchors.
    - Adapts to rolling mean over past 100 ticks.
    """
    
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 80, 
            'INTARIAN_PEPPER_ROOT': 80
        }
        self.window = 100
        self.history = {}

    def update_history(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except:
                self.history = {}

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}
        
        for product in self.limits.keys():
            if product not in state.order_depths:
                continue
                
            depth = state.order_depths[product]
            orders: List[Order] = []
            pos = state.position.get(product, 0)
            lim = self.limits[product]
            
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
            mid = (best_bid + best_ask) / 2.0
            
            # Save history
            p_hist = self.history.get(product, [])
            p_hist.append(mid)
            if len(p_hist) > self.window:
                p_hist = p_hist[-self.window:]
            self.history[product] = p_hist
            
            # Calculate rolling fair
            if len(p_hist) < 10:
                fair = mid
            else:
                fair = sum(p_hist) / len(p_hist)
                
            # Inventory skew
            skew = (pos / lim) * 2.0  # Max skew 2 ticks
            
            base_bid = math.floor(fair - 1.5 - skew)
            base_ask = math.ceil(fair + 1.5 - skew)
            
            # Layered execution
            block_size = 20
            
            buy_pending = lim - pos
            if buy_pending > 0:
                for i in range(4):
                    if buy_pending <= 0: break
                    price = int(base_bid - i)
                    q = min(buy_pending, block_size)
                    orders.append(Order(product, price, q))
                    buy_pending -= q
                    
            sell_pending = lim + pos
            if sell_pending > 0:
                for i in range(4):
                    if sell_pending <= 0: break
                    price = int(base_ask + i)
                    q = min(sell_pending, block_size)
                    orders.append(Order(product, price, -q))
                    sell_pending -= q
                    
            result[product] = orders

        trader_data = json.dumps(self.history)
        return result, 0, trader_data
