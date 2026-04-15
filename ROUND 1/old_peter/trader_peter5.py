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
    Antigravity Round 1 High-Gain Strategy (trader_peter5)
    ----------------------------------------------------
    - Signal: 3-Lag Linear Regression (High Confidence).
    - Mode: Aggressive Scalper (Risky).
    - Tactics: Zero-buffer snipes + Delayed inventory rebalancing.
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
            prices = self.history.get(product, [])
            return prices[-1] if prices else 10000.0
        
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
            
            # Predict
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
            
            # --- RISKY SNIPER (0.1 Threshold) ---
            rem_buy = lim - pos
            for ask, vol in sorted(depth.sell_orders.items()):
                # Version 5: Aggressive zero-buffer snipe
                if ask <= fair - 0.1 and rem_buy > 0:
                    qty = min(rem_buy, -vol)
                    orders.append(Order(product, int(ask), qty))
                    rem_buy -= qty
                    pos += qty
            
            rem_sell = lim + pos
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + 0.1 and rem_sell > 0:
                    qty = min(rem_sell, vol)
                    orders.append(Order(product, int(bid), -qty))
                    rem_sell -= qty
                    pos -= qty
            
            # --- AGGRESSIVE MAKER ---
            # Skew is lower (0.15) to allow holding positions during swings
            skew = 0.15
            
            bid_p = math.floor(fair - 1 - pos * skew)
            ask_p = math.ceil(fair + 1 - pos * skew)
            
            # Lead quoting: if fair is better than BBO+1, used fair
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 0
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 999999
            
            final_bid = min(best_bid + 1, bid_p)
            final_ask = max(best_ask - 1, ask_p)
            
            # Safety checks
            final_bid = min(final_bid, math.floor(fair - 0.5))
            final_ask = max(final_ask, math.ceil(fair + 0.5))
            
            buy_rem = lim - pos
            if buy_rem > 0:
                orders.append(Order(product, int(final_bid), buy_rem))
            
            sell_rem = lim + pos
            if sell_rem > 0:
                orders.append(Order(product, int(final_ask), -sell_rem))
                
            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
