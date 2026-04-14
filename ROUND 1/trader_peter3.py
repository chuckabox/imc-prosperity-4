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
    Antigravity Round 1 High-Frequency Strategy (trader_peter3)
    ----------------------------------------------------------
    - Signal: 3-Lag Regression (Starfruit) + 10k Anchor (Amethyst).
    - Execution: 3-Layered Liquidity Provision + Imbalance Weighting.
    - Goal: 6,000+ Shells per run.
    """
    
    def __init__(self):
        self.limits = {'ASH_COATED_OSMIUM': 20, 'INTARIAN_PEPPER_ROOT': 20}
        self.sf_coeffs = [0.34296, 0.32058, 0.33645]
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
        if not depth.buy_orders or not depth.sell_orders:
            # Try to get from history or default
            prices = self.history.get(product, [])
            return prices[-1] if prices else 10000.0

        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        mid_price = (best_bid + best_ask) / 2.0
        
        # Order Flow Imbalance (OFI) Adjustment
        bid_vol = sum(depth.buy_orders.values())
        ask_vol = -sum(depth.sell_orders.values())
        imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)
        imbalance_adj = imbalance * 0.5 # Shift fair value up to 0.5 ticks based on book pressure
        
        if product == 'ASH_COATED_OSMIUM':
            return 10000.0 + imbalance_adj
            
        if product == 'INTARIAN_PEPPER_ROOT':
            prices = self.history.get(product, [])
            if not isinstance(prices, list): prices = []
            prices.append(mid_price)
            if len(prices) > 3: prices = prices[-3:]
            self.history[product] = prices
            
            if len(prices) < 3: return mid_price + imbalance_adj
            
            prediction = self.sf_intercept
            for i in range(3):
                prediction += self.sf_coeffs[i] * prices[-(i+1)]
            return prediction + imbalance_adj
            
        return mid_price

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}
        
        for product in ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT']:
            if product not in state.order_depths: continue
                
            depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            position = state.position.get(product, 0)
            limit = self.limits[product]
            
            fair_price = self.get_fair_price(product, state)
            
            # 1. Aggressive Taker (Wider Thresholds)
            # Buy takes
            rem_buy = limit - position
            for price, vol in sorted(depth.sell_orders.items()):
                # Version 3: More aggressive takers for Starfruit
                threshold = 0.4 if product == 'ASH_COATED_OSMIUM' else 0.8
                if price <= fair_price - threshold and rem_buy > 0:
                    qty = min(rem_buy, -vol)
                    orders.append(Order(product, price, qty))
                    rem_buy -= qty
                    position += qty
            
            # Sell takes
            rem_sell = limit + position
            for price, vol in sorted(depth.buy_orders.items(), reverse=True):
                threshold = 0.4 if product == 'ASH_COATED_OSMIUM' else 0.8
                if price >= fair_price + threshold and rem_sell > 0:
                    qty = min(rem_sell, vol)
                    orders.append(Order(product, price, -qty))
                    rem_sell -= qty
                    position -= qty
            
            # 2. Multi-Layer Maker (3 Layers)
            # Increase skew slightly for more aggressive rebalancing
            skew = 0.4 if product == 'INTARIAN_PEPPER_ROOT' else 0.15
            
            if not depth.buy_orders or not depth.sell_orders: continue

            # Layer 1: Pennying (Tight)
            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())
            
            l1_bid = min(best_bid + 1, math.floor(fair_price - 1 - position * skew))
            l1_ask = max(best_ask - 1, math.ceil(fair_price + 1 - position * skew))
            
            # Ensure we don't cross fair
            l1_bid = min(l1_bid, math.floor(fair_price - 0.5))
            l1_ask = max(l1_ask, math.ceil(fair_price + 0.5))
            
            # Distribute remaining limit across layers
            # Layer 1: 50%, Layer 2: 30%, Layer 3: 20%
            remaining_buy = limit - position
            if remaining_buy > 0:
                q1 = math.ceil(remaining_buy * 0.5)
                orders.append(Order(product, int(l1_bid), q1))
                remaining_buy -= q1
                if remaining_buy > 0:
                    q2 = math.ceil(remaining_buy * 0.6)
                    orders.append(Order(product, int(l1_bid - 1), q2)) # Deeper layer
                    remaining_buy -= q2
                    if remaining_buy > 0:
                        orders.append(Order(product, int(l1_bid - 2), remaining_buy))
            
            remaining_sell = limit + position
            if remaining_sell > 0:
                q1 = math.ceil(remaining_sell * 0.5)
                orders.append(Order(product, int(l1_ask), -q1))
                remaining_sell -= q1
                if remaining_sell > 0:
                    q2 = math.ceil(remaining_sell * 0.6)
                    orders.append(Order(product, int(l1_ask + 1), -q2))
                    remaining_sell -= q2
                    if remaining_sell > 0:
                        orders.append(Order(product, int(l1_ask + 2), -remaining_sell))
            
            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
