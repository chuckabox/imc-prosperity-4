"""trader_ken_v17.py — The Guarded Oracle Engine

Fixes the catastrophic -7000 drop caused by accidental Taker limit orders.
When quoting around a mathematical Fair value, if the quote crosses the 
market's best bid or ask, the simulator treats it as a Taker order,
eating a massive 3-to-5 tick spread penalty.

v17 explicitly adds "Spread Guards" to force quoting to be strictly Passive.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]

# Precomputed Mean Extra Premiums from Day 0 + 1
AVG_PREMIUMS = {
    5000: 5.81,
    5100: 19.09,
    5200: 48.85,
    5300: 47.90,
    5400: 17.06,
    5500: 7.31
}

class Trader:
    ENABLE_HYDROGEL = True
    ENABLE_VFE = True
    ENABLE_VEV = True

    LIMITS: Dict[str, int] = {
        HYDROGEL: 80,
        VFE: 80,
        **{s: 60 for s in VEV_SYMBOLS},
    }

    HP_LIMIT = 20 
    VFE_LIMIT = 80
    EWMA_ALPHA = 0.20
    VEV_MM_EDGE = 1.0 

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

    def _save_state(self) -> str:
        return json.dumps(self.history)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    def _guarded_maker(self, symbol: str, depth: OrderDepth, pos: int, fair: float, limit: int, edge: float) -> List[Order]:
        orders = []
        bb, ba = self._top(depth)
        if bb is None or ba is None: return []

        # Desired passive quotes
        qbid = int(round(fair - edge))
        qask = int(round(fair + edge))
        
        # ── CRITICAL FIX: The Spread Guard ──
        # Do not allow our maker quotes to cross the market book, 
        # which would trigger a massive taker penalty.
        if qbid >= ba: qbid = ba - 1
        if qask <= bb: qask = bb + 1
        if qbid >= qask: qbid = qask - 1

        room_long = limit - pos
        room_short = limit + pos
        
        if room_long > 0: orders.append(Order(symbol, qbid, room_long))
        if room_short > 0: orders.append(Order(symbol, qask, -room_short))
        return orders

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        vfe_mid = None
        if VFE in state.order_depths:
            bb, ba = self._top(state.order_depths[VFE])
            if bb is not None and ba is not None:
                vfe_mid = (bb + ba) / 2.0
                
                prev = self.history.get("vfe_ewma")
                vfe_ewma = vfe_mid if prev is None else (1-self.EWMA_ALPHA)*prev + self.EWMA_ALPHA*vfe_mid
                self.history["vfe_ewma"] = vfe_ewma
                
                if self.ENABLE_VFE:
                    v_ords = self._guarded_maker(VFE, state.order_depths[VFE], state.position.get(VFE, 0), vfe_ewma, self.VFE_LIMIT, edge=2.0)
                    for o in v_ords: result.setdefault(VFE, []).append(o)

        if self.ENABLE_VEV and vfe_mid is not None:
            for strike in VEV_STRIKES:
                sym = f"VEV_{strike}"
                if sym not in state.order_depths: continue
                depth = state.order_depths[sym]
                
                # Oracle Value: instantly updates with VFE, never catches falling knives
                intrinsic = max(vfe_mid - strike, 0)
                fair = intrinsic + AVG_PREMIUMS[strike]
                
                pos = state.position.get(sym, 0)
                limit = 60
                
                # Guared Maker using true Fair value
                ords = self._guarded_maker(sym, depth, pos, fair, limit, self.VEV_MM_EDGE)
                for o in ords: result.setdefault(sym, []).append(o)

        if self.ENABLE_HYDROGEL and HYDROGEL in state.order_depths:
            bb, ba = self._top(state.order_depths[HYDROGEL])
            if bb is not None and ba is not None:
                mid = (bb + ba) / 2.0
                prev = self.history.get("hp_ewma")
                ewma = mid if prev is None else 0.8*prev + 0.2*mid
                self.history["hp_ewma"] = ewma
                
                pos = state.position.get(HYDROGEL, 0)
                limit = self.HP_LIMIT
                
                # Use Guarded Maker instead of blind taker orders
                ords = self._guarded_maker(HYDROGEL, state.order_depths[HYDROGEL], pos, ewma, limit, edge=1.0)
                for o in ords: result.setdefault(HYDROGEL, []).append(o)

        return result, 0, self._save_state()
