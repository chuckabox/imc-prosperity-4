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
    Antigravity Round 1 Alpha Strategy (trader_peter4)
    -------------------------------------------------
    - Signal: 5-Lag Micro-price Regression.
    - Execution: Sniper Taking + Exponential Inventory Skew.
    - Targeting: 7,000+ Shells.
    """
    
    def __init__(self):
        self.limits = {'ASH_COATED_OSMIUM': 20, 'INTARIAN_PEPPER_ROOT': 20}
        # 5-Lag Coefficients
        self.sf_weights = [0.20941, 0.19636, 0.20509, 0.18717, 0.20197]
        self.sf_intercept = 0.30103
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
        
        # Calculate Micro-Price
        bid_vol = sum(depth.buy_orders.values())
        ask_vol = -sum(depth.sell_orders.values())
        micro_price = (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)
        
        if product == 'ASH_COATED_OSMIUM':
            return 10000.0
            
        if product == 'INTARIAN_PEPPER_ROOT':
            p_hist = self.history.get(product, [])
            if not isinstance(p_hist, list): p_hist = []
            
            p_hist.append(micro_price)
            if len(p_hist) > 5: p_hist = p_hist[-5:]
            self.history[product] = p_hist
            
            if len(p_hist) < 5: return micro_price
            
            # Linear Regression Prediction
            pred = self.sf_intercept
            for i in range(5):
                pred += self.sf_weights[i] * p_hist[-(i+1)]
            return pred
            
        return micro_price

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
            
            # --- 1. Sniper Mode (Market Taking) ---
            # Hit asks if fair is high
            rem_buy = lim - pos
            for ask, vol in sorted(depth.sell_orders.items()):
                # Tight buffer for sniper (0.4 for Amethyst, 0.6 for Starfruit)
                threshold = 0.4 if product == 'ASH_COATED_OSMIUM' else 0.6
                if ask <= fair - threshold and rem_buy > 0:
                    qty = min(rem_buy, -vol)
                    orders.append(Order(product, int(ask), qty))
                    rem_buy -= qty
                    pos += qty
            
            # Hit bids if fair is low
            rem_sell = lim + pos
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                threshold = 0.4 if product == 'ASH_COATED_OSMIUM' else 0.6
                if bid >= fair + threshold and rem_sell > 0:
                    qty = min(rem_sell, vol)
                    orders.append(Order(product, int(bid), -qty))
                    rem_sell -= qty
                    pos -= qty
            
            # --- 2. Predictive Quoting (Market Making) ---
            # Use exponential inventory skewing
            # Skew = (pos/limit)^2 * sign(pos)
            skew_factor = 0.5 * (abs(pos) / lim) ** 2
            if pos < 0: skew_factor = -skew_factor
            
            bid_price = math.floor(fair - 1 - skew_factor * 3)
            ask_price = math.ceil(fair + 1 - skew_factor * 3)
            
            # Penny the BBO but respect fair value
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 0
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 999999
            
            final_bid = min(best_bid + 1, bid_price)
            final_ask = max(best_ask - 1, ask_price)
            
            # Safety: ensure we don't cross fair
            final_bid = min(final_bid, math.floor(fair - 0.5))
            final_ask = max(final_ask, math.ceil(fair + 0.5))
            
            # Layered orders (2 Layers: 70% / 30%)
            buy_rem = lim - pos
            if buy_rem > 0:
                q1 = math.ceil(buy_rem * 0.7)
                orders.append(Order(product, int(final_bid), q1))
                if buy_rem - q1 > 0:
                    orders.append(Order(product, int(final_bid - 1), buy_rem - q1))
            
            sell_rem = lim + pos
            if sell_rem > 0:
                q1 = math.ceil(sell_rem * 0.7)
                orders.append(Order(product, int(final_ask), -q1))
                if sell_rem - q1 > 0:
                    orders.append(Order(product, int(final_ask + 1), -(sell_rem - q1)))
            
            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
