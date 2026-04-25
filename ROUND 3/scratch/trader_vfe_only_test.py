"""trader_vfe_only_test.py — VFE-only OBI market maker.

Mirror of v3 HYDROGEL logic, applied to VELVETFRUIT_EXTRACT. Sanity
check: does spread capture work on the underlying given its 5-6 wide
top-of-book and ~14 stdev mid swings?
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

VFE = "VELVETFRUIT_EXTRACT"


class Trader:
    LIMIT = 80
    EWMA_ALPHA = 0.20
    TAKE_EDGE = 2
    OBI_THR = 0.15
    NEUTRAL_FRONT = 15
    NEUTRAL_SECOND = 8
    LEAN_AGG = 25
    LEAN_DEF = 5
    LEAN_OFFSET = 3
    SKEW_SOFT = 25
    SKEW_HARD = 50
    FLATTEN_HARD = 70

    def __init__(self):
        self.history: Dict = {}

    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("ewma", None)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int], int, int]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        bv = depth.buy_orders[bb] if bb is not None else 0
        av = -depth.sell_orders[ba] if ba is not None else 0
        return bb, ba, bv, av

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        if VFE not in state.order_depths:
            return result, 0, json.dumps(self.history)
        depth = state.order_depths[VFE]
        bb, ba, bv, av = self._top(depth)
        if bb is None or ba is None:
            return result, 0, json.dumps(self.history)

        mid = (bb + ba) / 2.0
        prev = self.history.get("ewma")
        ewma = mid if prev is None else (1 - self.EWMA_ALPHA) * prev + self.EWMA_ALPHA * mid
        self.history["ewma"] = ewma
        fair = ewma

        obi = (bv - av) / (bv + av) if (bv + av) > 0 else 0.0
        pos = state.position.get(VFE, 0)
        orders: List[Order] = []

        if ba <= fair - self.TAKE_EDGE and pos < self.LIMIT:
            sz = min(self.LIMIT - pos, -depth.sell_orders[ba])
            if sz > 0: orders.append(Order(VFE, ba, sz)); pos += sz
        if bb >= fair + self.TAKE_EDGE and pos > -self.LIMIT:
            sz = min(self.LIMIT + pos, depth.buy_orders[bb])
            if sz > 0: orders.append(Order(VFE, bb, -sz)); pos -= sz

        bullish = obi > self.OBI_THR
        bearish = obi < -self.OBI_THR

        room_long = max(0, self.LIMIT - pos)
        room_short = max(0, self.LIMIT + pos)

        if pos >= self.FLATTEN_HARD:
            buy_front = buy_second = 0
        else:
            if bullish: buy_front = min(self.LEAN_AGG, room_long)
            elif bearish: buy_front = min(self.LEAN_DEF, room_long)
            else: buy_front = min(self.NEUTRAL_FRONT, room_long)
            buy_second = min(self.NEUTRAL_SECOND, max(0, room_long - buy_front))

        if pos <= -self.FLATTEN_HARD:
            sell_front = sell_second = 0
        else:
            if bearish: sell_front = min(self.LEAN_AGG, room_short)
            elif bullish: sell_front = min(self.LEAN_DEF, room_short)
            else: sell_front = min(self.NEUTRAL_FRONT, room_short)
            sell_second = min(self.NEUTRAL_SECOND, max(0, room_short - sell_front))

        if pos >= self.SKEW_HARD: skew = -2
        elif pos >= self.SKEW_SOFT: skew = -1
        elif pos <= -self.SKEW_HARD: skew = 2
        elif pos <= -self.SKEW_SOFT: skew = 1
        else: skew = 0

        if bullish:
            qbid = bb + 1 + skew; qask = ba + self.LEAN_OFFSET + skew
        elif bearish:
            qbid = bb - self.LEAN_OFFSET + skew; qask = ba - 1 + skew
        else:
            qbid = bb + 1 + skew; qask = ba - 1 + skew

        if qbid >= qask: qbid = qask - 1

        if buy_front > 0: orders.append(Order(VFE, qbid, buy_front))
        if sell_front > 0: orders.append(Order(VFE, qask, -sell_front))
        if buy_second > 0: orders.append(Order(VFE, qbid - 2, buy_second))
        if sell_second > 0: orders.append(Order(VFE, qask + 2, -sell_second))

        result[VFE] = orders
        return result, 0, json.dumps(self.history)
