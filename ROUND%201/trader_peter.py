import json
import math
from typing import Dict, List, Any
from datamodel import Order, OrderDepth, TradingState, Symbol

class Trader:
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 20,
            'INTARIAN_PEPPER_ROOT': 20
        }
        self.traderData = ""
        self.history = {}

    def run(self, state: TradingState):
        result = {}
        
        for product in self.limits:
            if product not in state.order_depths:
                continue
                
            depth = state.order_depths[product]
            orders = []
            pos = state.position.get(product, 0)
            limit = self.limits[product]
            
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
            
            if best_bid is None or best_ask is None:
                continue
                
            mid = (best_bid + best_ask) / 2.0
            
            if product == 'ASH_COATED_OSMIUM':
                fair = 10000.0
            else:
                if product not in self.history:
                    self.history[product] = mid
                alpha = 0.4
                fair = alpha * mid + (1 - alpha) * self.history[product]
                self.history[product] = fair

            # 1. TAKER: Conservatively cross spread
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - 2.0:
                    qty = min(limit - pos, -vol)
                    if qty > 0:
                        orders.append(Order(product, ask, qty))
                        pos += qty
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + 2.0:
                    qty = min(limit + pos, vol)
                    if qty > 0:
                        orders.append(Order(product, bid, -qty))
                        pos -= qty

            # 2. MAKER: Single level pennying with skew
            skew = int(pos / 5.0)
            
            bid_p = min(best_bid + 1, int(fair - 1)) - skew
            ask_p = max(best_ask - 1, int(fair + 1)) - skew
            
            # Boundary Squeeze
            if pos >= 15:
                ask_p = min(ask_p, int(fair))
            if pos <= -15:
                bid_p = max(bid_p, int(fair))

            # Allocation
            can_buy = limit - pos
            if can_buy > 0 and bid_p < fair:
                orders.append(Order(product, int(bid_p), can_buy))
            
            can_sell = limit + pos
            if can_sell > 0 and ask_p > fair:
                orders.append(Order(product, int(ask_p), -can_sell))
                
            result[product] = orders

        return result, 0, self.traderData
