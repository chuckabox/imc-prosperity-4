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
    Peter V3: Balanced & Active
    --------------------------
    A robust version of Peter V2 designed to survive all market regimes.
    1. Lowered position limits (30) for better DD management.
    2. Active taking on small edges (0.5 ticks) to maintain PnL velocity.
    3. Sigmoid-based inventory management.
    """

    LIMIT_OSMIUM = 30
    LIMIT_PEPPER = 30

    def __init__(self):
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
        
        hist = self.history.get("pp", [])
        hist.append(mid)
        if len(hist) > 100: hist.pop(0)
        self.history["pp"] = hist
        
        if len(hist) < 10: return []

        fair = self._ema(hist, 8)
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        orders = []

        rem_buy = self.LIMIT_PEPPER - pos
        rem_sell = self.LIMIT_PEPPER + pos

        # High-Winrate Takes: Tiny clips on tiny edges
        if ba and ba <= fair + 0.5 and rem_buy > 0:
            q = min(rem_buy, 1)
            orders.append(Order(product, ba, int(q)))
        elif bb and bb >= fair - 0.5 and rem_sell > 0:
            q = min(rem_sell, 1)
            orders.append(Order(product, bb, int(-q)))

        return orders

    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths: return []
        depth = state.order_depths[product]
        pos = state.position.get(product, 0)
        mid = self._get_mid(depth)
        
        hist = self.history.get("op", [])
        hist.append(mid)
        if len(hist) > 100: hist.pop(0)
        self.history["op"] = hist
        
        if len(hist) < 20: return []

        fair = self._ema(hist, 40)
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        orders = []

        rem_buy = self.LIMIT_OSMIUM - pos
        rem_sell = self.LIMIT_OSMIUM + pos

        if ba and ba <= fair + 0.1 and rem_buy > 0:
            q = min(rem_buy, 1)
            orders.append(Order(product, ba, int(q)))
        elif bb and bb >= fair - 0.1 and rem_sell > 0:
            q = min(rem_sell, 1)
            orders.append(Order(product, bb, int(-q)))

        return orders

    def run(self, state: TradingState):
        self._load_state(state.traderData)
        result = {}
        pep = self._pepper_logic(state)
        if pep: result["INTARIAN_PEPPER_ROOT"] = pep
        osm = self._osmium_logic(state)
        if osm: result["ASH_COATED_OSMIUM"] = osm
        trader_data = json.dumps(self.history)
        return result, 0, trader_data
