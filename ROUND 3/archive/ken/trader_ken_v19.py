"""trader_ken_v19.py — Controlled Inventory Engine

v18 had large VEV drawdowns: the guarded maker posted full position room
(up to 48 units per strike) in a single order. A 60-tick VFE move would
instantly cost ~1400 PNL from VEV_5200 alone (48 contracts * 0.5 delta * 60).

Fix: cap VEV maker orders at 8 units per side. This limits worst-case
single-strike exposure to ~200 PNL per 60-tick VFE move, while still
capturing the bid-ask spread over many small fills.

HYDROGEL + VFE logic unchanged from v18 (they're the profit drivers).
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]

PREM_INIT: Dict[int, float] = {
    5000: 5.81,
    5100: 19.09,
    5200: 48.85,
    5300: 47.90,
    5400: 17.06,
    5500: 7.31,
}

PREM_BOUNDS: Dict[int, Tuple[float, float]] = {
    5000: (2.0, 14.0),
    5100: (10.0, 30.0),
    5200: (30.0, 72.0),
    5300: (30.0, 72.0),
    5400: (8.0, 30.0),
    5500: (3.0, 15.0),
}

STRIKE_CAP: Dict[int, int] = {
    5000: 32,
    5100: 44,
    5200: 48,
    5300: 44,
    5400: 36,
    5500: 28,
}


class Trader:
    ENABLE_HYDROGEL = True
    ENABLE_VFE = True
    ENABLE_VEV = True

    # HYDROGEL
    HP_LIMIT = 80
    HP_ANCHOR = 9993.0
    HP_EWMA_ALPHA = 0.20
    HP_TAKER_EDGE = 2.0
    HP_MAKER_EDGE = 2.0
    HP_TAKER_MAX = 20

    # VFE
    VFE_LIMIT = 80
    VFE_EWMA_ALPHA = 0.20
    VFE_MAKER_EDGE = 2.0
    VFE_TAKER_EDGE = 4.0
    VFE_TAKER_MAX = 15

    # VEV
    PREM_ALPHA = 0.05
    VEV_MAKER_EDGE = 2.0
    VEV_MAKER_SIZE = 8  # FIX: cap per-side order size (was full room, up to 48)

    def __init__(self):
        self.history: Dict = {}

    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("prem", {})
        for k in VEV_STRIKES:
            self.history["prem"].setdefault(str(k), PREM_INIT[k])

    def _save_state(self) -> str:
        return json.dumps(self.history)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    def _guarded_maker(
        self,
        symbol: str,
        depth: OrderDepth,
        pos: int,
        fair: float,
        limit: int,
        edge: float,
        max_qty: Optional[int] = None,
    ) -> List[Order]:
        orders = []
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []

        qbid = int(round(fair - edge))
        qask = int(round(fair + edge))

        # Spread guard: never cross the book (prevents taker penalty)
        if qbid >= ba:
            qbid = ba - 1
        if qask <= bb:
            qask = bb + 1
        if qbid >= qask:
            qbid = qask - 1

        room_long = limit - pos
        room_short = limit + pos
        if max_qty is not None:
            room_long = min(room_long, max_qty)
            room_short = min(room_short, max_qty)

        if room_long > 0:
            orders.append(Order(symbol, qbid, room_long))
        if room_short > 0:
            orders.append(Order(symbol, qask, -room_short))
        return orders

    def _hydrogel_logic(self, state: TradingState) -> List[Order]:
        depth = state.order_depths.get(HYDROGEL)
        if depth is None:
            return []
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        prev = self.history.get("hp_ewma")
        ewma = mid if prev is None else (1 - self.HP_EWMA_ALPHA) * prev + self.HP_EWMA_ALPHA * mid
        self.history["hp_ewma"] = ewma
        fair = 0.6 * ewma + 0.4 * self.HP_ANCHOR

        pos = state.position.get(HYDROGEL, 0)
        lim = self.HP_LIMIT
        orders: List[Order] = []

        # Taker: capture obvious mispricings first
        if ba <= fair - self.HP_TAKER_EDGE and pos < lim:
            sz = min(self.HP_TAKER_MAX, lim - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(HYDROGEL, ba, sz))
                pos += sz
        if bb >= fair + self.HP_TAKER_EDGE and pos > -lim:
            sz = min(self.HP_TAKER_MAX, lim + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(HYDROGEL, bb, -sz))
                pos -= sz

        # Maker: fill remaining room passively (no max_qty cap — HYDROGEL is our main edge)
        orders.extend(self._guarded_maker(HYDROGEL, depth, pos, fair, lim, self.HP_MAKER_EDGE))
        return orders

    def _vfe_logic(self, state: TradingState) -> Tuple[List[Order], Optional[float]]:
        depth = state.order_depths.get(VFE)
        if depth is None:
            return [], None
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return [], None

        mid = (bb + ba) / 2.0
        prev = self.history.get("vfe_ewma")
        ewma = mid if prev is None else (1 - self.VFE_EWMA_ALPHA) * prev + self.VFE_EWMA_ALPHA * mid
        self.history["vfe_ewma"] = ewma
        fair = ewma

        pos = state.position.get(VFE, 0)
        lim = self.VFE_LIMIT
        orders: List[Order] = []

        if ba <= fair - self.VFE_TAKER_EDGE and pos < lim:
            sz = min(self.VFE_TAKER_MAX, lim - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(VFE, ba, sz))
                pos += sz
        if bb >= fair + self.VFE_TAKER_EDGE and pos > -lim:
            sz = min(self.VFE_TAKER_MAX, lim + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(VFE, bb, -sz))
                pos -= sz

        orders.extend(self._guarded_maker(VFE, depth, pos, fair, lim, self.VFE_MAKER_EDGE))
        return orders, mid

    def _vev_logic(self, state: TradingState, vfe_mid: float) -> List[Order]:
        orders: List[Order] = []

        for strike in VEV_STRIKES:
            sym = f"VEV_{strike}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            bb, ba = self._top(depth)
            if bb is None or ba is None:
                continue

            obs_mid = (bb + ba) / 2.0
            intrinsic = max(vfe_mid - strike, 0.0)
            obs_prem = obs_mid - intrinsic
            prem_key = str(strike)
            prev_prem = float(self.history["prem"][prem_key])
            prem = (1 - self.PREM_ALPHA) * prev_prem + self.PREM_ALPHA * obs_prem
            lo, hi = PREM_BOUNDS[strike]
            prem = max(lo, min(hi, prem))
            self.history["prem"][prem_key] = prem

            fair = intrinsic + prem
            pos = state.position.get(sym, 0)
            lim = STRIKE_CAP[strike]

            # Pure passive maker, capped at VEV_MAKER_SIZE per side
            # Prevents large unhedged delta exposure from bulk fills
            orders.extend(
                self._guarded_maker(sym, depth, pos, fair, lim, self.VEV_MAKER_EDGE, max_qty=self.VEV_MAKER_SIZE)
            )

        return orders

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        if self.ENABLE_HYDROGEL:
            for o in self._hydrogel_logic(state):
                result.setdefault(o.symbol, []).append(o)

        vfe_orders, vfe_mid = self._vfe_logic(state)
        if self.ENABLE_VFE:
            for o in vfe_orders:
                result.setdefault(o.symbol, []).append(o)

        if self.ENABLE_VEV and vfe_mid is not None:
            for o in self._vev_logic(state, vfe_mid):
                result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save_state()
