
import json
import math
import sys
from typing import Dict, List, Any
from datamodel import Order, OrderDepth, TradingState, Symbol

class Trader:
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 80,
            'INTARIAN_PEPPER_ROOT': 80,
        }
        self.history = {}

    def _load_state(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except Exception:
                self.history = {}

    def run(self, state: TradingState):
        self._load_state(state.traderData)
        result = {}

        # --- PEPPER ROOT ---
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            depth = state.order_depths[product]
            pos = state.position.get(product, 0)
            orders = []
            
            bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
            ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
            
            if bb and ba:
                mid = (bb + ba) / 2.0
                fair = mid - (pos * 0.04) # Lean away from inventory
                
                # Take liquidity
                for ask, vol in sorted(depth.sell_orders.items()):
                    if ask < fair and (self.limits[product] - pos) > 0:
                        qty = min(self.limits[product] - pos, -vol)
                        orders.append(Order(product, ask, qty))
                        pos += qty
                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if bid > fair and (self.limits[product] + pos) > 0:
                        qty = min(self.limits[product] + pos, vol)
                        orders.append(Order(product, bid, -qty))
                        pos -= qty
                
                # Passive quotes
                rem_buy = self.limits[product] - pos
                rem_sell = self.limits[product] + pos
                
                bid_price = min(bb + 1, math.floor(fair))
                ask_price = max(ba - 1, math.ceil(fair))
                
                if bid_price >= ask_price:
                    bid_price = math.floor(fair - 0.5)
                    ask_price = math.ceil(fair + 0.5)
                
                if rem_buy > 0: orders.append(Order(product, int(bid_price), min(rem_buy, 20)))
                if rem_sell > 0: orders.append(Order(product, int(ask_price), -min(rem_sell, 20)))
                result[product] = orders

        # --- OSMIUM ---
        product = 'ASH_COATED_OSMIUM'
        if product in state.order_depths:
            depth = state.order_depths[product]
            pos = state.position.get(product, 0)
            orders = []
            bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
            ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
            if bb and ba:
                mid = (bb + ba) / 2.0
                fair = mid - (pos * 0.05)
                # Tape pattern check
                if product in state.market_trades:
                    for trade in state.market_trades[product]:
                        if abs(trade.quantity) >= 15: # Extreme pattern
                             if trade.price > mid: fair -= 1 # Bearish tilt
                             else: fair += 1 # Bullish tilt
                
                # Take liquidity
                for ask, vol in sorted(depth.sell_orders.items()):
                    if ask < fair - 2 and (self.limits[product] - pos) > 0:
                        qty = min(self.limits[product] - pos, -vol)
                        orders.append(Order(product, ask, qty))
                        pos += qty
                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if bid > fair + 2 and (self.limits[product] + pos) > 0:
                        qty = min(self.limits[product] + pos, vol)
                        orders.append(Order(product, bid, -qty))
                        pos -= qty

                bid_price = min(bb + 1, math.floor(fair - 0.5))
                ask_price = max(ba - 1, math.ceil(fair + 0.5))
                if bid_price >= ask_price:
                    bid_price = math.floor(fair - 1)
                    ask_price = math.ceil(fair + 1)
                
                if (self.limits[product] - pos) > 0:
                    orders.append(Order(product, int(bid_price), min(self.limits[product] - pos, 20)))
                if (self.limits[product] + pos) > 0:
                    orders.append(Order(product, int(ask_price), -min(self.limits[product] + pos, 20)))
                result[product] = orders

        trader_data = json.dumps(self.history)
        return result, 0, trader_data
