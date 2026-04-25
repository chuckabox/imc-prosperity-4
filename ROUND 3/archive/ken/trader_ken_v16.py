"""trader_ken_v16.py — The Oracle Engine

The most robust alpha discovered: Options pricing should be derived 
directly from the underlying (VFE) + a historical extra premium (time value).

v16 Changes:
1. Underlying-Aware Oracle: Replaced option EWMAs with a tick-by-tick valuation.
   Fair = max(VFE_mid - K, 0) + Precomputed_Premium[K]
2. Historical Stability: Uses the long-term Average Extra Premiums found across 
   Day 0 and Day 1 to ensure valuation consistency.
3. No More Falling Knives: Because option prices update instantly when VFE moves,
   the bot won't buy "cheap" calls during an underlying crash.
4. Tame Market-Making: Hydrogel and VFE run passive spread-capture only.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]

# Precomputed Mean Extra Premiums (Market - Intrinsic) from Day 0 + 1
AVG_PREMIUMS = {
    5000: 5.81,
    5100: 19.09,
    5200: 48.85,
    5300: 47.90,
    5400: 17.06,
    5500: 7.31
}

class Trader:
    # ── Feature flags ──────────────────────────────────────────────────────
    ENABLE_HYDROGEL = True
    ENABLE_VFE = True
    ENABLE_VEV = True

    LIMITS: Dict[str, int] = {
        HYDROGEL: 80,
        VFE: 80,
        **{s: 60 for s in VEV_SYMBOLS},
    }

    # ── HYDROGEL / VFE Settings ───────────────────────────────────────────
    HP_LIMIT = 20 # Ultra safe
    VFE_LIMIT = 80
    EWMA_ALPHA = 0.20

    # ── VEV Settings ──────────────────────────────────────────────────────
    VEV_MM_EDGE = 1.0 # Tight 1 tick edge
    VEV_NEUTRAL_FRONT = 40 # High volume, low edge
    VEV_NEUTRAL_SECOND = 20

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

    def _generic_obi_mm(self, symbol: str, depth: OrderDepth, pos: int, fair: float, limit: int) -> List[Order]:
        orders = []
        bb, ba = self._top(depth)
        if bb is None or ba is None: return []

        # Passive MM around Fair
        qbid = int(round(fair - self.VEV_MM_EDGE))
        qask = int(round(fair + self.VEV_MM_EDGE))
        
        # Cross check
        if qbid >= qask: qbid = qask - 1

        room_long = limit - pos
        room_short = limit + pos
        
        if room_long > 0: orders.append(Order(symbol, qbid, room_long))
        if room_short > 0: orders.append(Order(symbol, qask, -room_short))
        return orders

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        # 1. Oracle Prep (Get underlying mid-price)
        vfe_mid = None
        if VFE in state.order_depths:
            bb, ba = self._top(state.order_depths[VFE])
            if bb is not None and ba is not None:
                vfe_mid = (bb + ba) / 2.0
                
                # Update VFE EWMA for its own MM
                prev = self.history.get("vfe_ewma")
                vfe_ewma = vfe_mid if prev is None else (1-self.EWMA_ALPHA)*prev + self.EWMA_ALPHA*vfe_mid
                self.history["vfe_ewma"] = vfe_ewma
                
                # VFE Passive Spread Capture
                if self.ENABLE_VFE:
                    v_ords = self._generic_obi_mm(VFE, state.order_depths[VFE], state.position.get(VFE, 0), vfe_ewma, self.VFE_LIMIT)
                    for o in v_ords: result.setdefault(VFE, []).append(o)

        # 2. Oracle Option Market Making
        if self.ENABLE_VEV and vfe_mid is not None:
            for strike in VEV_STRIKES:
                sym = f"VEV_{strike}"
                if sym not in state.order_depths: continue
                depth = state.order_depths[sym]
                
                # Oracle Value: Intrinsic + Day 0/1 Baseline Premium
                intrinsic = max(vfe_mid - strike, 0)
                fair = intrinsic + AVG_PREMIUMS[strike]
                
                pos = state.position.get(sym, 0)
                limit = 60
                
                # Passive MM around the Oracle price
                ords = self._generic_obi_mm(sym, depth, pos, fair, limit)
                for o in ords: result.setdefault(sym, []).append(o)

        # 3. Simple Hydrogel Scalper
        if self.ENABLE_HYDROGEL and HYDROGEL in state.order_depths:
            bb, ba = self._top(state.order_depths[HYDROGEL])
            if bb and ba:
                mid = (bb + ba) / 2.0
                prev = self.history.get("hp_ewma")
                ewma = mid if prev is None else 0.8*prev + 0.2*mid
                self.history["hp_ewma"] = ewma
                
                pos = state.position.get(HYDROGEL, 0)
                limit = self.HP_LIMIT
                if ba < ewma: result.setdefault(HYDROGEL, []).append(Order(HYDROGEL, ba, limit - pos))
                if bb > ewma: result.setdefault(HYDROGEL, []).append(Order(HYDROGEL, bb, -(limit + pos)))

        return result, 0, self._save_state()
