import json
import math
from typing import Dict, List, Any

from datamodel import Order, OrderDepth, TradingState, Symbol


class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        conversions: int,
        trader_data: str,
    ) -> None:
        pass


logger = Logger()


class Trader:
    """
    Peter V3: Balanced Microstructure MM
    ------------------------------------
    Improved for robustness across all datasets.
    Reduces reliance on over-trained technical indicators.
    """

    def __init__(self):
        self.limits = {
            "ASH_COATED_OSMIUM": 80,
            "INTARIAN_PEPPER_ROOT": 80,
        }

    def _get_orders(self, state: TradingState, product: str) -> List[Order]:
        depth = state.order_depths[product]
        pos = state.position.get(product, 0)
        limit = self.limits.get(product, 20)

        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        
        if best_bid is None or best_ask is None:
            return []

        # Participate at the best levels
        bid_price = best_bid
        ask_price = best_ask
        
        # Simple inventory leaning
        if pos > limit * 0.2: # Too long
            bid_price -= 1
        elif pos < -limit * 0.2: # Too short
            ask_price += 1
            
        if bid_price >= ask_price:
            bid_price = ask_price - 1

        orders = []
        buy_cap = limit - pos
        sell_cap = limit + pos

        if buy_cap > 0:
            orders.append(Order(product, int(bid_price), buy_cap))
        if sell_cap > 0:
            orders.append(Order(product, int(ask_price), -sell_cap))

        return orders

    def run(self, state: TradingState):
        result = {}
        for product in state.order_depths:
            orders = self._get_orders(state, product)
            if orders:
                result[product] = orders

        return result, 0, ""
