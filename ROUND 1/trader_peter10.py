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
    Antigravity Round 1 Institutional Bot (trader_peter10)
    ----------------------------------------------------
    - Goal: 5k-10k PnL by adding Trade Awareness and Fragmentation.
    - Signal: 3-Lag Regression + Market-Trade Momentum (Tape Reading).
    - Execution: Fragmented orders (Layered blocks) + OFI Defense.
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
        
        # --- TAPE READING (Market Trades) ---
        trade_pressure = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                # If trade happened at BBO Ask, it's aggressive buying
                if trade.price >= mid: trade_pressure += trade.quantity
                else: trade_pressure -= trade.quantity
        
        tape_adj = math.copysign(min(abs(trade_pressure) * 0.1, 1.0), trade_pressure)
        
        if product == 'ASH_COATED_OSMIUM':
            return 10000.0 + tape_adj
            
        if product == 'INTARIAN_PEPPER_ROOT':
            p_hist = self.history.get(product, [])
            if not isinstance(p_hist, list): p_hist = []
            p_hist.append(mid)
            if len(p_hist) > 3: p_hist = p_hist[-3:]
            self.history[product] = p_hist
            if len(p_hist) < 3: return mid + tape_adj
            
            # 3-Lag Predict
            pred = self.sf_intercept
            for i in range(3):
                pred += self.sf_weights[i] * p_hist[-(i+1)]
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
            
            # --- 1. SNIPER (1.2 Threshold) ---
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

            # --- 2. FRAGMENTED MAKER (Anti-Pennying) ---
            skew = 0.3
            base_bid = math.floor(fair - 1 - pos * skew)
            base_ask = math.ceil(fair + 1 - pos * skew)
            
            # Fragment the 20-unit limit into 4 blocks of 5
            q_per_block = 5
            
            # Buy Side
            buy_remaining = lim - pos
            if buy_remaining > 0:
                for i in range(4):
                    if buy_remaining <= 0: break
                    price = int(base_bid - i)
                    # Safety: ensure we don't cross fair too much
                    if price > fair - 0.5: price = math.floor(fair - 1)
                    q = min(buy_remaining, q_per_block)
                    orders.append(Order(product, price, q))
                    buy_remaining -= q
            
            # Sell Side
            sell_remaining = lim + pos
            if sell_remaining > 0:
                for i in range(4):
                    if sell_remaining <= 0: break
                    price = int(base_ask + i)
                    if price < fair + 0.5: price = math.ceil(fair + 1)
                    q = min(sell_remaining, q_per_block)
                    orders.append(Order(product, price, -q))
                    sell_remaining -= q
                
            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
