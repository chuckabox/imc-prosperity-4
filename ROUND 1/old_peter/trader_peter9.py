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
    Antigravity Round 1 Production Alpha (trader_peter9)
    --------------------------------------------------
    - Goal: 10k PnL by maximizing Volume Capture (Avg Fill 6.3+).
    - Signal: 3-Lag Mid-price Regression (v2 core).
    - Tactics: "Spread Squeezing" - Jump the BBO queue to lead the book.
    - Safety: Strictly passive execution + Linear rebalancing.
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
        mid = (best_bid + best_ask) / 2.0
        
        if product == 'ASH_COATED_OSMIUM':
            return 10000.0
            
        if product == 'INTARIAN_PEPPER_ROOT':
            p_hist = self.history.get(product, [])
            if not isinstance(p_hist, list): p_hist = []
            p_hist.append(mid)
            if len(p_hist) > 3: p_hist = p_hist[-3:]
            self.history[product] = p_hist
            if len(p_hist) < 3: return mid
            
            # 3-Lag Predict
            pred = self.sf_intercept
            for i in range(3):
                pred += self.sf_weights[i] * p_hist[-(i+1)]
            return pred
        return mid

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
            
            # --- THE SQUEEZER (Deep Liquidity) ---
            if not depth.buy_orders or not depth.sell_orders: continue

            # If spread is wide, we skip BBO pennying and quote inside
            skew = 0.3
            bid_p = math.floor(fair - 1 - pos * skew)
            ask_p = math.ceil(fair + 1 - pos * skew)
            
            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())
            
            # Queue Jumping: If our fair-quote is better than the BBO, use it.
            # This ensures we get the 6.3 Avg Fill.
            final_bid = bid_p
            final_ask = ask_p
            
            # Ensure we don't cross fair to prevent instant losses
            final_bid = min(final_bid, math.floor(fair - 0.5))
            final_ask = max(final_ask, math.ceil(fair + 0.5))
            
            # Safety: Don't quote too deep in the opposite side
            final_bid = max(final_bid, best_bid - 5)
            final_ask = min(final_ask, best_ask + 5)
            
            rem_buy = lim - pos
            if rem_buy > 0:
                orders.append(Order(product, int(final_bid), rem_buy))
            
            rem_sell = lim + pos
            if rem_sell > 0:
                orders.append(Order(product, int(final_ask), -rem_sell))
                
            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
