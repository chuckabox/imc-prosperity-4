import json
import math
from typing import Dict, List, Any
from datamodel import Order, OrderDepth, TradingState, Symbol

class Logger:
    def __init__(self) -> None:
        self.logs = ""
    def flush(self, state: TradingState, orders: Dict[Symbol, List[Order]], conversions: int, trader_data: str) -> None:
        pass

logger = Logger()

class Trader:
    """
    Antigravity Round 1 Refined Leader (trader_peter8)
    -------------------------------------------------
    - Goal: 10k PnL by upgrading the v2 leader with Micro-price awareness.
    - Logic: 3-Lag Micro-price Regression + Passive Market Making.
    - Safety: No aggressive takes; strictly inventory-skewed quoting.
    """
    
    def __init__(self):
        self.limits = {'ASH_COATED_OSMIUM': 20, 'INTARIAN_PEPPER_ROOT': 20}
        self.sf_weights = [0.34296, 0.32058, 0.33645]
        self.sf_intercept = 0.2535
        self.history = {}
        self.traderData = ""

    def update_history(self, trader_data: str):
        if trader_data:
            try: self.history = json.loads(trader_data)
            except: self.history = {}

    def get_fair_price(self, product: str, state: TradingState) -> float:
        depth = state.order_depths[product]
        if not depth.buy_orders or not depth.sell_orders:
            p_hist = self.history.get(product, [])
            return p_hist[-1] if p_hist else 10000.0

        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        
        # Micro-Price (Volume Weighted Mid)
        bid_vol = sum(depth.buy_orders.values())
        ask_vol = -sum(depth.sell_orders.values())
        micro = (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)
        
        if product == 'ASH_COATED_OSMIUM':
            return 10000.0
            
        if product == 'INTARIAN_PEPPER_ROOT':
            p_hist = self.history.get(product, [])
            if not isinstance(p_hist, list): p_hist = []
            p_hist.append(micro)
            if len(p_hist) > 3: p_hist = p_hist[-3:]
            self.history[product] = p_hist
            if len(p_hist) < 3: return micro
            
            # Predict
            pred = self.sf_intercept
            for i in range(3):
                pred += self.sf_weights[i] * p_hist[-(i+1)]
            return pred
        return micro

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}
        
        for product in ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT']:
            if product not in state.order_depths: continue
            
            depth = state.order_depths[product]
            orders: List[Order] = []
            pos = state.position.get(product, 0)
            lim = self.limits[product]
            
            fair = self.get_fair_price(product, state)
            
            # --- PURE PASSIVE MARKET MAKING ---
            if not depth.buy_orders or not depth.sell_orders: continue
            
            skew = 0.3
            bid_p = math.floor(fair - 1 - pos * skew)
            ask_p = math.ceil(fair + 1 - pos * skew)
            
            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())
            
            # Pennying logic: always try to lead the BBO
            final_bid = min(best_bid + 1, bid_p)
            final_ask = max(best_ask - 1, ask_p)
            
            # Safety checks
            final_bid = min(final_bid, math.floor(fair - 0.5))
            final_ask = max(final_ask, math.ceil(fair + 0.5))
            
            if (lim - pos) > 0:
                orders.append(Order(product, int(final_bid), lim - pos))
            if (lim + pos) > 0:
                orders.append(Order(product, int(final_ask), -(lim + pos)))
                
            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
