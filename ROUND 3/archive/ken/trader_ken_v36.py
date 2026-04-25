"""trader_ken_v36.py

High-conviction experiment:
- Concentrate entirely on HYDROGEL mean-reversion + market making.
- Disable VFE/VEV to avoid cross-product noise and risk leakage.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDRO = "HYDROGEL_PACK"


class Trader:
    ENABLE_HYDRO = True

    LIMIT = 80
    ANCHOR = 10000.0
    ALPHA_FAST = 0.30
    ALPHA_SLOW = 0.06

    MAKER_EDGE = 2.0
    TAKER_EDGE = 2.2
    TAKER_MAX = 26
    MAKER_MAX = 52

    INV_SKEW = 0.12
    INV_TRIGGER = 30

    OPEN_PHASE_TS = 120_000
    OPEN_SCALE = 0.85

    def __init__(self):
        self.h: Dict = {}

    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.h = json.loads(state.traderData)
            except Exception:
                self.h = {}
        self.h.setdefault("ewma_fast", None)
        self.h.setdefault("ewma_slow", None)

    def _save(self) -> str:
        return json.dumps(self.h)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    @staticmethod
    def _best_vols(depth: OrderDepth) -> Tuple[int, int]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        bv = depth.buy_orders.get(bb, 0) if bb is not None else 0
        av = -depth.sell_orders.get(ba, 0) if ba is not None else 0
        return max(0, int(bv)), max(0, int(av))

    def _logic(self, state: TradingState) -> List:
        depth = state.order_depths.get(HYDRO)
        if depth is None:
            return []
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []

        pos = int(state.position.get(HYDRO, 0))
        mid = (bb + ba) / 2.0

        prev_f = self.h["ewma_fast"]
        prev_s = self.h["ewma_slow"]
        ewma_fast = mid if prev_f is None else (1 - self.ALPHA_FAST) * prev_f + self.ALPHA_FAST * mid
        ewma_slow = mid if prev_s is None else (1 - self.ALPHA_SLOW) * prev_s + self.ALPHA_SLOW * mid
        self.h["ewma_fast"] = ewma_fast
        self.h["ewma_slow"] = ewma_slow

        bv, av = self._best_vols(depth)
        den = bv + av
        micro = (bb * av + ba * bv) / den if den > 0 else mid
        imbalance = (bv - av) / den if den > 0 else 0.0

        # Blend: anchored slow fair + microprice + fast mean-rev trigger component.
        fair = 0.35 * self.ANCHOR + 0.35 * ewma_slow + 0.20 * micro + 0.10 * ewma_fast
        signal = ewma_fast - ewma_slow

        inv_adj = 0.0
        if abs(pos) > self.INV_TRIGGER:
            inv_adj = self.INV_SKEW * pos

        q_bid = int(round(fair - self.MAKER_EDGE + 0.7 * imbalance - inv_adj))
        q_ask = int(round(fair + self.MAKER_EDGE + 0.7 * imbalance - inv_adj))

        if q_bid >= ba:
            q_bid = ba - 1
        if q_ask <= bb:
            q_ask = bb + 1
        if q_bid >= q_ask:
            q_bid = q_ask - 1

        scale = self.OPEN_SCALE if int(state.timestamp) <= self.OPEN_PHASE_TS else 1.0
        taker_max = max(4, int(self.TAKER_MAX * scale))
        maker_max = max(8, int(self.MAKER_MAX * scale))

        orders = []
        # Mean-reversion taking: fade stretched top-of-book around fair and fast/slow divergence.
        if ba <= fair - self.TAKER_EDGE and signal <= 0.8 and pos < self.LIMIT:
            sz = min(taker_max, self.LIMIT - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(HYDRO, ba, sz))
                pos += sz
        if bb >= fair + self.TAKER_EDGE and signal >= -0.8 and pos > -self.LIMIT:
            sz = min(taker_max, self.LIMIT + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(HYDRO, bb, -sz))
                pos -= sz

        room_long = min(self.LIMIT - pos, maker_max)
        room_short = min(self.LIMIT + pos, maker_max)
        if room_long > 0:
            orders.append(Order(HYDRO, q_bid, room_long))
        if room_short > 0:
            orders.append(Order(HYDRO, q_ask, -room_short))
        return orders

    def run(self, state: TradingState):
        self._load(state)
        result: Dict[str, List] = {}
        if self.ENABLE_HYDRO:
            h_orders = self._logic(state)
            for o in h_orders:
                result.setdefault(o.symbol, []).append(o)
        return result, 0, self._save()

