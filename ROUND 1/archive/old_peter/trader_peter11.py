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
    Antigravity Round 1 Final - Version 11 (200k XIREC Target)
    ---------------------------------------------------------
    - Correction: Regression for OSMIUM, Anchor for PEPPER_ROOT.
    - Correction: Limits set to 80 Units.
    - Strategy: 3-Lag Regression + Tape Reading + Fragmented MM.
    """
    
    def __init__(self):
        self.limits = {'ASH_COATED_OSMIUM': 80, 'INTARIAN_PEPPER_ROOT': 80}
        # Osmium Regression Weights
        self.os_weights = [0.3616, 0.3148, 0.2925]
        self.os_intercept = 309.9
        self.history = {}
        self.traderData = ""

    def update_history(self, trader_data: str):
        if trader_data:
            try: self.history = json.loads(trader_data)
            except: self.history = {}

    def get_fair_price(self, product: str, state: TradingState) -> float:
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 11500
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 11500
        mid = (best_bid + best_ask) / 2.0
        
        # Tape Reading Influence
        trade_pressure = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= mid: trade_pressure += trade.quantity
                else: trade_pressure -= trade.quantity
        tape_adj = math.copysign(min(abs(trade_pressure) * 0.1, 1.0), trade_pressure)
        
        if product == 'INTARIAN_PEPPER_ROOT':
            # "Steady like Emeralds" - Fixed Anchor at 11,500
            return 11500.0 + tape_adj
            
        if product == 'ASH_COATED_OSMIUM':
            # "Volatile but Hidden Pattern" - 3-Lag Regression
            p_hist = self.history.get(product, [])
            if not isinstance(p_hist, list): p_hist = []
            p_hist.append(mid)
            if len(p_hist) > 3: p_hist = p_hist[-3:]
            self.history[product] = p_hist
            if len(p_hist) < 3: return mid + tape_adj
            
            pred = self.os_intercept
            for i in range(3):
                pred += self.os_weights[i] * p_hist[-(i+1)]
            return pred + tape_adj
            
        return mid + tape_adj

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
            
            # --- 1. THE SNIPER (1.2 Threshold) ---
            rem_buy = lim - pos
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - 1.2 and rem_buy > 0:
                    q = min(rem_buy, -vol)
                    orders.append(Order(product, int(ask), q))
                    rem_buy -= q
                    pos += q
            
            rem_sell = lim + pos
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + 1.2 and rem_sell > 0:
                    q = min(rem_sell, vol)
                    orders.append(Order(product, int(bid), -q))
                    rem_sell -= q
                    pos -= q

            # --- 2. FRAGMENTED MM (Anti-Pennying) ---
            skew = 0.25 # Linear rebalancing
            base_bid = math.floor(fair - 1 - pos * skew)
            base_ask = math.ceil(fair + 1 - pos * skew)
            
            block_size = 20 # Sliced into 4 blocks of 20 units
            
            # Buy Side
            buy_rem = lim - pos
            if buy_rem > 0:
                for i in range(4):
                    if buy_rem <= 0: break
                    price = int(base_bid - i)
                    if price > fair - 0.5: price = math.floor(fair - 1)
                    q = min(buy_rem, block_size)
                    orders.append(Order(product, price, q))
                    buy_rem -= q
            
            # Sell Side
            sell_rem = lim + pos
            if sell_rem > 0:
                for i in range(4):
                    if sell_rem <= 0: break
                    price = int(base_ask + i)
                    if price < fair + 0.5: price = math.ceil(fair + 1)
                    q = min(sell_rem, block_size)
                    orders.append(Order(product, price, -q))
                    sell_rem -= q
                
            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
