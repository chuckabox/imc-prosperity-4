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
    Antigravity Round 1 Top-1% Leader Strategy (trader_peter6)
    ---------------------------------------------------------
    - Goal: Match Top-20 PnL (10k+) by increasing risk appetite.
    - Signal: 4-Lag Micro-price Regression + OFI.
    - Risk: Low Skew (0.1) to allow larger drawdown and recovery.
    - Size: High concentration layers (80% primary).
    """
    
    def __init__(self):
        self.limits = {'ASH_COATED_OSMIUM': 20, 'INTARIAN_PEPPER_ROOT': 20}
        # Optimized 4-Lag Weights for Micro-price
        self.sf_weights = [0.22, 0.20, 0.20, 0.18]
        self.sf_intercept = 0.25
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
        
        # Order Flow Imbalance (OFI)
        bid_vol = sum(depth.buy_orders.values())
        ask_vol = -sum(depth.sell_orders.values())
        micro = (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)
        
        if product == 'ASH_COATED_OSMIUM':
            # Amethyst: Stable 10k but influenced by book pressure
            imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)
            return 10000.0 + (imbalance * 0.4)
            
        if product == 'INTARIAN_PEPPER_ROOT':
            p_hist = self.history.get(product, [])
            if not isinstance(p_hist, list): p_hist = []
            p_hist.append(micro)
            if len(p_hist) > 4: p_hist = p_hist[-4:]
            self.history[product] = p_hist
            if len(p_hist) < 4: return micro
            
            # 4-lag Regression
            pred = self.sf_intercept
            for i in range(4):
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
            
            # --- 1. Aggressive Sniper (Leader Spec: 0.3 threshold) ---
            # Hit Mispriced Orders
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - 0.3 and (lim - pos) > 0:
                    qty = min(lim - pos, -vol)
                    orders.append(Order(product, int(ask), qty))
                    pos += qty
            
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + 0.3 and (lim + pos) > 0:
                    qty = min(lim + pos, vol)
                    orders.append(Order(product, int(bid), -qty))
                    pos -= qty
            
            # --- 2. Low-Skew Quoting (Leader Spec: 0.1 Skew) ---
            # Allows larger inventory positions to capture fuller mean-reversion payoff
            skew = 0.1 
            
            # Quote exactly at Fair +/- 1 with Skew adjustment
            bid_p = math.floor(fair - 1 - (pos * skew))
            ask_p = math.ceil(fair + 1 - (pos * skew))
            
            # Pennying logic
            if not depth.buy_orders or not depth.sell_orders: continue
            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())
            
            final_bid = min(best_bid + 1, bid_p)
            final_ask = max(best_ask - 1, ask_p)
            
            # Safety checks
            final_bid = min(final_bid, math.floor(fair - 0.5))
            final_ask = max(final_ask, math.ceil(fair + 0.5))
            
            # Concentrated Sizes (80% Primary Layer)
            rem_buy = lim - pos
            if rem_buy > 0:
                q1 = math.ceil(rem_buy * 0.8)
                orders.append(Order(product, int(final_bid), q1))
                if (rem_buy - q1) > 0:
                    orders.append(Order(product, int(final_bid - 1), rem_buy - q1))
            
            rem_sell = lim + pos
            if rem_sell > 0:
                q1 = math.ceil(rem_sell * 0.8)
                orders.append(Order(product, int(final_ask), -q1))
                if (rem_sell - q1) > 0:
                    orders.append(Order(product, int(final_ask + 1), -(rem_sell - q1)))
                
            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
