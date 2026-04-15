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
        self.limits = {'ASH_COATED_OSMIUM': 20, 'INTARIAN_PEPPER_ROOT': 20}
        
        # OSMIUM Regression (Re-calibrated for Round 1 volatility)
        self.os_weights = [0.35, 0.30, 0.25] 
        self.os_intercept = 300.0 # Placeholder, adjust based on your specific OSMIUM backtests
        
        self.history = {} 

    def update_history(self, trader_data: str):
        if trader_data:
            try: self.history = json.loads(trader_data)
            except: self.history = {}

    def get_fair_price(self, product: str, state: TradingState) -> float:
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
        mid = (best_bid + best_ask) / 2.0
        
        # Improved Tape Reading: Focus on recent trade direction
        tape_adj = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                # Weight larger trades more heavily
                weight = 1.0 if trade.quantity > 5 else 0.5
                if trade.price >= mid: tape_adj += weight
                else: tape_adj -= weight
        tape_adj = math.copysign(min(abs(tape_adj) * 0.2, 1.5), tape_adj)
        
        if product == 'INTARIAN_PEPPER_ROOT':
            # Mean Reversion Anchor
            return 11500.0 + tape_adj
            
        if product == 'ASH_COATED_OSMIUM':
            hist = self.history.get(product, [])
            if not isinstance(hist, list): hist = []
            hist.append(mid)
            if len(hist) > 3: hist = hist[-3:]
            self.history[product] = hist
            
            if len(hist) < 3: return mid + tape_adj
            
            # Regression-based prediction
            pred = self.os_intercept
            for i in range(3):
                pred += self.os_weights[i] * hist[-(i+1)]
            return pred + tape_adj
            
        return mid

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}
        
        for product in self.limits.keys():
            if product not in state.order_depths: continue
            depth = state.order_depths[product]
            orders: List[Order] = []
            pos = state.position.get(product, 0)
            lim = self.limits[product]
            
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
            if best_bid is None or best_ask is None: continue
            
            fair = self.get_fair_price(product, state)
            
            # 1. THE SNIPER (Taker Logic)
            # Use tight margins for Osmium, wider for Root
            margin = 0.6 if product == 'ASH_COATED_OSMIUM' else 1.2
            
            # Buy from asks below fair
            rem_buy = lim - pos
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - margin and rem_buy > 0:
                    q = min(rem_buy, -vol)
                    orders.append(Order(product, int(ask), q))
                    rem_buy -= q
                    pos += q
            
            # Sell to bids above fair
            rem_sell = lim + pos
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + margin and rem_sell > 0:
                    q = min(rem_sell, vol)
                    orders.append(Order(product, int(bid), -q))
                    rem_sell -= q
                    pos -= q

            # 2. COMPETITIVE MM (Maker Logic)
            # Dynamic skew: push the price further as position approaches limit
            skew = 0.4 
            
            # Calculate where we WANT to be based on our fair price and position
            target_bid = fair - 1.0 - (pos * skew)
            target_ask = fair + 1.0 - (pos * skew)
            
            # Competitive Pennying: 
            # We want to be 1 tick better than the market, but not past our target
            bid_pr = int(max(best_bid + 1, math.floor(target_bid)))
            ask_pr = int(min(best_ask - 1, math.ceil(target_ask)))
            
            # Final sanity check: Don't provide liquidity at a loss relative to fair
            bid_pr = min(bid_pr, math.floor(fair - 0.5))
            ask_pr = max(ask_pr, math.ceil(fair + 0.5))
            
            # Post Maker Orders
            if (lim - pos) > 0:
                orders.append(Order(product, bid_pr, lim - pos))
            if (lim + pos) > 0:
                orders.append(Order(product, ask_pr, -(lim + pos)))
                
            result[product] = orders

        trader_data = json.dumps(self.history)
        return result, 0, trader_data