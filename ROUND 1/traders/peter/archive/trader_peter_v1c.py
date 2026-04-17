import json
import math
from typing import Dict, List, Any

from datamodel import Order, OrderDepth, TradingState, Symbol


class Logger:
    def __init__(self) -> None:
        pass

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        pass

    def flush(self, *args, **kwargs) -> None:
        pass


logger = Logger()


class Trader:
    """
    Peter V1c: High-Frequency Market Maker
    - 20-period EMA Fair Price
    - Continuous Quoting (spread >= 2)
    - Tight Edge (1-2 ticks)
    - Smooth Linear Inventory Leaning
    """

    LIMIT_OSMIUM = 80
    LIMIT_PEPPER = 80
    
    WINDOW_SIZE = 25
    WARMUP = 20
    EMA_SPAN = 20

    def __init__(self):
        self.limits = {
            "ASH_COATED_OSMIUM": self.LIMIT_OSMIUM,
            "INTARIAN_PEPPER_ROOT": self.LIMIT_PEPPER,
        }
        self.history = {}

    def _load_state(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except Exception:
                self.history = {}

    def _ema(self, prices: list, span: int) -> float:
        if not prices: return 0.0
        alpha = 2.0 / (span + 1)
        val = prices[0]
        for p in prices[1:]:
            val = alpha * p + (1 - alpha) * val
        return val

    def _get_wmid(self, depth: OrderDepth) -> float:
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if best_bid and best_ask:
            b_qty = depth.buy_orders[best_bid]
            a_qty = abs(depth.sell_orders[best_ask])
            return (best_bid * a_qty + best_ask * b_qty) / (b_qty + a_qty)
        return best_bid or best_ask or 0.0

    def _mm_logic(self, product: str, state: TradingState) -> List[Order]:
        if product not in state.order_depths: return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)
        limit = self.limits[product]
        wmid = self._get_wmid(depth)
        
        hist = self.history.get(product, [])
        hist.append(wmid)
        if len(hist) > self.WINDOW_SIZE: hist.pop(0)
        self.history[product] = hist

        if len(hist) < self.WARMUP: return []

        # 20-period EMA Fair Price
        fair = self._ema(hist, self.EMA_SPAN)
        
        # Smooth linear dynamic leaning (max skew 5 ticks at limit)
        inv_skew = (pos / limit) * 5.0 

        # Tight Edge: Target 1-2 ticks edge. Spread of ~2-3.
        edge = 1.0 
        
        bid_price = round(fair - edge - inv_skew)
        ask_price = round(fair + edge - inv_skew)
        
        # Continuous Quoting: ensure spread is at least 2 ticks wide
        if ask_price - bid_price < 2:
            ask_price = bid_price + 2

        orders = []
        buy_cap = limit - pos
        sell_cap = limit + pos

        # Post continuous Buy/Sell orders
        if buy_cap > 0:
            orders.append(Order(product, int(bid_price), buy_cap))
        if sell_cap > 0:
            orders.append(Order(product, int(ask_price), -sell_cap))

        return orders

    def run(self, state: TradingState):
        self._load_state(state.traderData)
        result = {}
        
        for product in self.limits.keys():
            ords = self._mm_logic(product, state)
            if ords: result[product] = ords

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
