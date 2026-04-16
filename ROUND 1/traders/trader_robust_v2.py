import json
import math
import collections
from typing import Dict, List, Any
from datamodel import Order, OrderDepth, TradingState, Symbol

class Logger:
    def __init__(self) -> None:
        pass
    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        pass
    def flush(self, state: TradingState, orders: Dict[Symbol, List[Order]], conversions: int, trader_data: str) -> None:
        pass

class Trader:
    def __init__(self):
        self.limits = {'ASH_COATED_OSMIUM': 80, 'INTARIAN_PEPPER_ROOT': 80}
        self.emas = {}
        # Changed to dict of lists to be easily JSON serialized
        self.history = {}

    def run(self, state: TradingState):
        if state.traderData:
            try:
                data = json.loads(state.traderData)
                self.emas = data.get("emas", {})
                self.history = data.get("history", {})
            except:
                pass
                
        result = {}
        for product in self.limits.keys():
            if product not in state.order_depths: continue
            
            depth = state.order_depths[product]
            pos = state.position.get(product, 0)
            lim = self.limits[product]
            
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 0
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 0
            if not best_bid or not best_ask: continue
            
            mid = (best_bid + best_ask) / 2.0
            
            # --- TAPE IMBALANCE ---
            v_b = depth.buy_orders[best_bid]
            v_a = abs(depth.sell_orders[best_ask])
            imb = (v_b - v_a) / (v_b + v_a)
            
            # Update Hist
            phist = self.history.get(product, [])
            phist.append(mid)
            if len(phist) > 5:
                phist = phist[-5:]
            self.history[product] = phist

            # --- FAIR VALUE CALCULATION ---
            fair = mid
            target = 0
            spread_bps = max(1.5, mid * 0.00015) 

            # Hidden Pattern AR(3) detection for Osmium
            if product == 'ASH_COATED_OSMIUM' and len(phist) >= 3:
                # 309.9 + 0.3616*p[-1] + 0.3148*p[-2] + 0.2925*p[-3]
                ar_pred = 309.9 + (0.3616 * phist[-1]) + (0.3148 * phist[-2]) + (0.2925 * phist[-3])
                fair = ar_pred + imb * spread_bps
                
                # Dynamic targets based on distance to FV
                if mid < ar_pred - spread_bps:
                    target = lim
                elif mid > ar_pred + spread_bps:
                    target = -lim
                else:
                    target = 0
            else:
                # Robust Momentum Validation Model (For Pepper and External Data)
                if product not in self.emas:
                    self.emas[product] = {'fast': mid, 'slow': mid}
                    
                fast_ema = self.emas[product]['fast'] * 0.8 + mid * 0.2
                slow_ema = self.emas[product]['slow'] * 0.95 + mid * 0.05
                self.emas[product]['fast'] = fast_ema
                self.emas[product]['slow'] = slow_ema
                
                threshold_bps = mid * 0.00005 
                if fast_ema > slow_ema + threshold_bps:
                    target = lim
                elif fast_ema < slow_ema - threshold_bps:
                    target = -lim
                
                fair = fast_ema + imb * spread_bps
            
            # --- MARKET MAKING ---
            # Increase skew weight to prevent being trapped in trends
            skew = (pos - target) * (spread_bps / lim) * 2.0 
            
            buy_price = math.floor(fair - spread_bps - skew)
            sell_price = math.ceil(fair + spread_bps - skew)
            
            orders = []
            block = 20
            
            buy_rem = lim - pos
            if buy_rem > 0:
                for i in range(4):
                    if buy_rem <= 0: break
                    p = int(buy_price - i)
                    q = min(buy_rem, block)
                    orders.append(Order(product, p, q))
                    buy_rem -= q
                    
            sell_rem = lim + pos
            if sell_rem > 0:
                for i in range(4):
                    if sell_rem <= 0: break
                    p = int(sell_price + i)
                    q = min(sell_rem, block)
                    orders.append(Order(product, p, -q))
                    sell_rem -= q
                    
            result[product] = orders
            
        trader_state = {
            "emas": self.emas,
            "history": self.history
        }
        return result, 0, json.dumps(trader_state)
