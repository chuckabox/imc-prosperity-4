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
    Peter V2f:
    - Pepper: Robust MM (mid +/- 2, 0.1 skew)
    - Osmium: Bollinger BB (2.0 std dev) + Passive Exit
    """
    LIMIT_OSMIUM = 80
    LIMIT_PEPPER = 80

    def __init__(self):
        self.history = {}

    def _load_state(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except:
                self.history = {}

    def _get_mid(self, depth: OrderDepth) -> float:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb and ba: return (bb + ba) / 2.0
        return bb or ba or 0.0

    def _pepper_logic(self, state: TradingState) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths: return []
        depth = state.order_depths[product]
        pos = state.position.get(product, 0)
        mid = self._get_mid(depth)
        
        # Robust MM: Stronger skew, wider base spread
        skew = pos * 0.1 
        bid = math.floor(mid - 2.0 - skew)
        ask = math.ceil(mid + 2.0 - skew)
        
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb: bid = min(bid, bb + 1)
        if ba: ask = max(ask, ba - 1)
        if bid >= ask: bid = ask - 1

        orders = []
        rb, rs = self.LIMIT_PEPPER - pos, self.LIMIT_PEPPER + pos
        if rb > 0: orders.append(Order(product, int(bid), int(rb)))
        if rs > 0: orders.append(Order(product, int(ask), int(-rs)))
        return orders

    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths: return []
        depth = state.order_depths[product]
        pos = state.position.get(product, 0)
        mid = self._get_mid(depth)
        
        hist = self.history.get("op", [])
        hist.append(mid)
        if len(hist) > 30: hist.pop(0)
        self.history["op"] = hist
        
        orders = []
        if len(hist) < 20: return []

        mean = sum(hist) / len(hist)
        var = sum((x - mean) ** 2 for x in hist) / len(hist)
        std = math.sqrt(max(var, 0.01))
        
        ub, lb = mean + 2.0 * std, mean - 2.0 * std
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None

        # 1. ENTRY (Take if deep deviation)
        rb, rs = self.LIMIT_OSMIUM - pos, self.LIMIT_OSMIUM + pos
        if ba and ba <= lb and rb > 0:
            q = min(rb, abs(depth.sell_orders[ba]), 20)
            orders.append(Order(product, ba, int(q)))
            pos += q
        elif bb and bb >= ub and rs > 0:
            q = min(rs, depth.buy_orders[bb], 20)
            orders.append(Order(product, bb, int(-q)))
            pos -= q

        # 2. EXIT & MM (Passive limit at mean)
        rb, rs = self.LIMIT_OSMIUM - pos, self.LIMIT_OSMIUM + pos
        exit_bid = math.floor(mean - 1)
        exit_ask = math.ceil(mean + 1)
        
        if pos > 0: # Long -> Sell at mean
            orders.append(Order(product, int(exit_ask), int(-min(pos, 40))))
        elif pos < 0: # Short -> Buy at mean
            orders.append(Order(product, int(exit_bid), int(min(abs(pos), 40))))

        return orders

    def run(self, state: TradingState):
        self._load_state(state.traderData)
        res = {}
        pep = self._pepper_logic(state)
        if pep: res["INTARIAN_PEPPER_ROOT"] = pep
        osm = self._osmium_logic(state)
        if osm: res["ASH_COATED_OSMIUM"] = osm
        data = json.dumps(self.history)
        logger.flush(state, res, 0, data)
        return res, 0, data
