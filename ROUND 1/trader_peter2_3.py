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
    """
    Antigravity Round 1 Fragmented Strategy (trader_peter2_3)
    -------------------------------------------------------
    - Concept: Fragmented Quoting + Adverse Selection Avoidance.
    - Signal: 3-Lag Regression (Starfruit) + 10k Anchor (Osmium).
    - Limit: Hard 20-unit constraint.
    - Execution: Slicing orders into multiple layers to hide size and improve fill average.
    """
    
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 20,
            'INTARIAN_PEPPER_ROOT': 20
        }
        
        # Proven Starfruit Signal (3-Lag Regression)
        self.sf_weights = [0.34296, 0.32058, 0.33645] 
        self.sf_intercept = 0.2535
        
        self.history = {} 
        self.traderData = ""

    def update_history(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except:
                self.history = {}

    def get_fair_price(self, product: str, state: TradingState) -> float:
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
        mid_price = (best_bid + best_ask) / 2.0
        
        # Tape Adjustment (Soft)
        tape_adj = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= mid_price: tape_adj += trade.quantity
                else: tape_adj -= trade.quantity
        tape_adj = math.copysign(min(abs(tape_adj) * 0.1, 1.0), tape_adj)
        
        if product == 'ASH_COATED_OSMIUM':
            return 10000.0 + tape_adj
            
        if product == 'INTARIAN_PEPPER_ROOT':
            hist = self.history.get(product, [])
            if not isinstance(hist, list): hist = []
            
            hist.append(mid_price)
            if len(hist) > 3: hist = hist[-3:]
            self.history[product] = hist
            
            if len(hist) < 3: return mid_price + tape_adj
            
            prediction = self.sf_intercept
            for i in range(3):
                prediction += self.sf_weights[i] * hist[-(i+1)]
            
            return prediction + tape_adj
            
        return mid_price

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}
        
        for product in self.limits.keys():
            if product not in state.order_depths: continue
                
            depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            
            position = state.position.get(product, 0)
            limit = self.limits[product]
            
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 0
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 0
            if not best_bid or not best_ask: continue
            
            fair_price = self.get_fair_price(product, state)
            
            # --- 1. Defensive Sniper ---
            # Using higher threshold (1.0/1.5) to avoid bad taker trades
            take_margin = 0.6 if product == 'ASH_COATED_OSMIUM' else 1.2
            
            rem_buy = limit - position
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair_price - take_margin and rem_buy > 0:
                    qty = min(rem_buy, -vol)
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty
                    position += qty
            
            rem_sell = limit + position
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair_price + take_margin and rem_sell > 0:
                    qty = min(rem_sell, vol)
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty
                    position -= qty
            
            # --- 2. Fragmented Maker (The v2.3 Specialty) ---
            # Slice the remaining limit into 3 Layers: 
            # Layer 1: Best Price (Pennying)
            # Layer 2: Deep Liquidity (Fair +/- 2)
            # Layer 3: Catching Wicks (Fair +/- 3)
            
            skew_factor = 0.3
            base_bid = math.floor(fair_price - 1.0 - (position * skew_factor))
            base_ask = math.ceil(fair_price + 1.0 - (position * skew_factor))
            
            # Ensure base doesn't cross fair
            base_bid = min(base_bid, math.floor(fair_price - 0.5))
            base_ask = max(base_ask, math.ceil(fair_price + 0.5))
            
            # Buy Side Fragmentation
            buy_rem = limit - position
            if buy_rem > 0:
                # Layer 1 (Pennying)
                l1_price = min(best_bid + 1, base_bid)
                l1_qty = math.ceil(buy_rem * 0.5)
                orders.append(Order(product, int(l1_price), l1_qty))
                
                # Layer 2 (Protection)
                if buy_rem - l1_qty > 0:
                    l2_price = l1_price - 1
                    l2_qty = buy_rem - l1_qty
                    orders.append(Order(product, int(l2_price), l2_qty))
                    
            # Sell Side Fragmentation
            sell_rem = limit + position
            if sell_rem > 0:
                # Layer 1 (Pennying)
                l1_price = max(best_ask - 1, base_ask)
                l1_qty = math.ceil(sell_rem * 0.5)
                orders.append(Order(product, int(l1_price), -l1_qty))
                
                # Layer 2 (Protection)
                if sell_rem - l1_qty > 0:
                    l2_price = l1_price + 1
                    l2_qty = sell_rem - l1_qty
                    orders.append(Order(product, int(l2_price), -l2_qty))
                
            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
