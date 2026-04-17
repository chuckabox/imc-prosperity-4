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
    Peter V2e:
    - Pepper: Pure Market Maker (mid_price + inventory skew)
    - Osmium: Bollinger Band Mean Reversion (2 std dev)
    """

    LIMIT_OSMIUM = 80
    LIMIT_PEPPER = 80

    def __init__(self):
        self.history = {}

    def _load_state(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except Exception:
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
        
        orders = []
        rem_buy = self.LIMIT_PEPPER - pos
        rem_sell = self.LIMIT_PEPPER + pos
        
        # Pure market maker, quote around mid_price
        # Linear inventory leaning
        skew = pos * 0.05 
        bid_price = math.floor(mid - 1.0 - skew)
        ask_price = math.ceil(mid + 1.0 - skew)
        
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None

        if bb: bid_price = min(bid_price, bb + 1)
        if ba: ask_price = max(ask_price, ba - 1)
        if bid_price >= ask_price:
            bid_price = ask_price - 1

        if rem_buy > 0:
            orders.append(Order(product, int(bid_price), int(rem_buy)))
        if rem_sell > 0:
            orders.append(Order(product, int(ask_price), int(-rem_sell)))

        return orders

    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths: return []
        depth = state.order_depths[product]
        pos = state.position.get(product, 0)
        mid = self._get_mid(depth)
        
        hist = self.history.get("op", [])
        hist.append(mid)
        # 20 periods for Bollinger
        if len(hist) > 20: hist.pop(0)
        self.history["op"] = hist
        
        orders = []
        rem_buy = self.LIMIT_OSMIUM - pos
        rem_sell = self.LIMIT_OSMIUM + pos
        
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None

        if len(hist) > 1:
            mean = sum(hist) / len(hist)
            variance = sum((x - mean) ** 2 for x in hist) / len(hist)
            std_dev = math.sqrt(variance)
            
            upper_band = mean + 2 * std_dev
            lower_band = mean - 2 * std_dev
            
            # Entry: > 2 std dev
            if ba and ba <= lower_band and rem_buy > 0:
                q = min(rem_buy, abs(depth.sell_orders.get(ba, 0)), 20)
                orders.append(Order(product, ba, int(q)))
                pos += int(q)
                rem_buy = self.LIMIT_OSMIUM - pos
                rem_sell = self.LIMIT_OSMIUM + pos
                
            if bb and bb >= upper_band and rem_sell > 0:
                q = min(rem_sell, depth.buy_orders.get(bb, 0), 20)
                orders.append(Order(product, bb, int(-q)))
                pos -= int(q)
                rem_buy = self.LIMIT_OSMIUM - pos
                rem_sell = self.LIMIT_OSMIUM + pos
                
            # Exit: mean reversion
            if pos > 0 and bb and bb >= mean:
                q = min(pos, depth.buy_orders.get(bb, 0), 10)
                if q > 0: orders.append(Order(product, bb, int(-q)))
            elif pos < 0 and ba and ba <= mean:
                q = min(abs(pos), abs(depth.sell_orders.get(ba, 0)), 10)
                if q > 0: orders.append(Order(product, ba, int(q)))

        return orders

    def run(self, state: TradingState):
        self._load_state(state.traderData)
        result = {}
        
        pep = self._pepper_logic(state)
        if pep: result["INTARIAN_PEPPER_ROOT"] = pep
        
        osm = self._osmium_logic(state)
        if osm: result["ASH_COATED_OSMIUM"] = osm
        
        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
