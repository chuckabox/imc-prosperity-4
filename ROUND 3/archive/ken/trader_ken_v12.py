"""trader_ken_v12.py — The Decoupled Spread Engine

This version aims for a "6k Floor" (steady positive PnL with minimal drawdowns).
It achieves this by abandoning all cross-product directional bets and delta-hedging.

v12 Changes:
1. Decoupled Systems: Hydrogel, VFE, and VEV all operate as independent market makers.
2. No Forced Delta Hedge: Removed logic that forced VFE to offset VEV delta.
   Cross-hedging often leads to "taking" bad prices to satisfy math.
3. 6-Strike Option Engine: Actively market-makes 5000-5500 strikes to maximize spread volume.
4. Tame Hydrogel: Reverted to EWMA for flexibility but with very tight risk limits.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500] 
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]

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

    # ── HYDROGEL (Safe EWMA) ─────────────────────────────────────────────
    HP_EWMA_ALPHA = 0.20
    HP_TAKE_EDGE = 2
    HP_OBI_THRESHOLD = 0.15
    HP_NEUTRAL_FRONT = 8 # Ultra tight risk
    HP_NEUTRAL_SECOND = 4
    HP_LEAN_AGGRESSIVE = 20
    HP_LEAN_DEFENSIVE = 4
    HP_LEAN_OFFSET_DEFENSIVE = 2
    HP_SKEW_SOFT = 20
    HP_SKEW_HARD = 40
    HP_FLATTEN_HARD = 60

    # ── VFE (Pure Spread Collector) ──────────────────────────────────────
    VFE_EWMA_ALPHA = 0.20
    VFE_TAKE_EDGE = 2
    VFE_OBI_THRESHOLD = 0.15
    VFE_NEUTRAL_FRONT = 12
    VFE_NEUTRAL_SECOND = 6
    VFE_LEAN_AGG = 25
    VFE_LEAN_DEF = 5
    VFE_LEAN_OFFSET = 3
    VFE_SKEW_SOFT = 25
    VFE_SKEW_HARD = 50
    VFE_FLATTEN_HARD = 70

    # ── VEV (6-Strike Machine) ───────────────────────────────────────────
    VEV_EWMA_ALPHA = 0.30 # Snappier EWMA for options
    VEV_OBI_THRESHOLD = 0.10
    VEV_NEUTRAL_FRONT = 10
    VEV_NEUTRAL_SECOND = 5
    VEV_LEAN_AGG = 20
    VEV_LEAN_DEF = 4
    VEV_LEAN_OFFSET = 2
    VEV_SKEW_SOFT = 20
    VEV_SKEW_HARD = 40
    VEV_FLATTEN_HARD = 55

    def __init__(self):
        self.history: Dict = {}

    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        # Metadata
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("last_ts", -1)
        self.history.setdefault("day", 0)
        ts = state.timestamp
        last = int(self.history["last_ts"])
        if 0 <= ts < last:
            self.history["day"] = int(self.history["day"]) + 1
        self.history["last_ts"] = ts

    def _save_state(self) -> str:
        return json.dumps(self.history)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int], int, int]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        bv = depth.buy_orders[bb] if bb is not None else 0
        av = -depth.sell_orders[ba] if ba is not None else 0
        return bb, ba, bv, av

    def _obi_mm(
        self,
        symbol: str,
        depth: OrderDepth,
        pos_real: int,
        pos_target: int,
        ewma_key: str,
        *,
        ewma_alpha: float,
        take_edge: int,
        obi_thr: float,
        neutral_front: int,
        neutral_second: int,
        lean_agg: int,
        lean_def: int,
        lean_offset: int,
        skew_soft: int,
        skew_hard: int,
        flatten_hard: int,
    ) -> List[Order]:
        bb, ba, bv, av = self._top(depth)
        if bb is None or ba is None:
            return []
        limit = self.LIMITS[symbol]
        orders: List[Order] = []

        mid = (bb + ba) / 2.0
        prev = self.history.get(ewma_key)
        ewma = mid if prev is None else (1 - ewma_alpha) * prev + ewma_alpha * mid
        self.history[ewma_key] = ewma

        obi = (bv - av) / (bv + av) if (bv + av) > 0 else 0.0

        # Market Taking
        if ba <= ewma - take_edge and pos_real < limit:
            sz = min(limit - pos_real, -depth.sell_orders[ba])
            if sz > 0: orders.append(Order(symbol, ba, sz)); pos_real += sz
        if bb >= ewma + take_edge and pos_real > -limit:
            sz = min(limit + pos_real, depth.buy_orders[bb])
            if sz > 0: orders.append(Order(symbol, bb, -sz)); pos_real -= sz

        # Market Making Quoting
        dist = pos_real - pos_target # relative distance to target inventory
        bullish = obi > obi_thr
        bearish = obi < -obi_thr
        
        room_long = max(0, limit - pos_real)
        room_short = max(0, limit + pos_real)

        if dist >= flatten_hard:
            buy_front = buy_second = 0
        else:
            if bullish: buy_front = min(lean_agg, room_long)
            elif bearish: buy_front = min(lean_def, room_long)
            else: buy_front = min(neutral_front, room_long)
            buy_second = min(neutral_second, max(0, room_long - buy_front))

        if dist <= -flatten_hard:
            sell_front = sell_second = 0
        else:
            if bearish: sell_front = min(lean_agg, room_short)
            elif bullish: sell_front = min(lean_def, room_short)
            else: sell_front = min(neutral_front, room_short)
            sell_second = min(neutral_second, max(0, room_short - sell_front))

        # Inventory-based price skew
        if dist >= skew_hard: skew = -2
        elif dist >= skew_soft: skew = -1
        elif dist <= -skew_hard: skew = 2
        elif dist <= -skew_soft: skew = 1
        else: skew = 0

        # Primary quote selection
        if bullish:
            qbid = bb + 1 + skew; qask = ba + lean_offset + skew
        elif bearish:
            qbid = bb - lean_offset + skew; qask = ba - 1 + skew
        else:
            qbid = bb + 1 + skew; qask = ba - 1 + skew
        if qbid >= qask: qbid = qask - 1

        if buy_front > 0: orders.append(Order(symbol, qbid, buy_front))
        if sell_front > 0: orders.append(Order(symbol, qask, -sell_front))
        if buy_second > 0: orders.append(Order(symbol, qbid - 2, buy_second))
        if sell_second > 0: orders.append(Order(symbol, qask + 2, -sell_second))
        return orders

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        # 1. Independent VEV spread collection (6 Strikes)
        if self.ENABLE_VEV:
            for strike in VEV_STRIKES:
                sym = f"VEV_{strike}"
                if sym not in state.order_depths: continue
                ords = self._obi_mm(
                    sym, state.order_depths[sym], state.position.get(sym, 0),
                    0, f"ewma_{sym}",
                    ewma_alpha=self.VEV_EWMA_ALPHA, take_edge=2,
                    obi_thr=self.VEV_OBI_THRESHOLD,
                    neutral_front=self.VEV_NEUTRAL_FRONT, neutral_second=self.VEV_NEUTRAL_SECOND,
                    lean_agg=self.VEV_LEAN_AGG, lean_def=self.VEV_LEAN_DEF,
                    lean_offset=self.VEV_LEAN_OFFSET,
                    skew_soft=self.VEV_SKEW_SOFT, skew_hard=self.VEV_SKEW_HARD,
                    flatten_hard=self.VEV_FLATTEN_HARD,
                )
                for o in ords: result.setdefault(sym, []).append(o)

        # 2. Independent Hydrogel Engine (Safe limits)
        if self.ENABLE_HYDROGEL and HYDROGEL in state.order_depths:
            ords = self._obi_mm(
                HYDROGEL, state.order_depths[HYDROGEL], state.position.get(HYDROGEL, 0),
                0, "hp_ewma",
                ewma_alpha=self.HP_EWMA_ALPHA, take_edge=self.HP_TAKE_EDGE,
                obi_thr=self.HP_OBI_THRESHOLD,
                neutral_front=self.HP_NEUTRAL_FRONT, neutral_second=self.HP_NEUTRAL_SECOND,
                lean_agg=self.HP_LEAN_AGGRESSIVE, lean_def=self.HP_LEAN_DEFENSIVE,
                lean_offset=self.HP_LEAN_OFFSET_DEFENSIVE,
                skew_soft=self.HP_SKEW_SOFT, skew_hard=self.HP_SKEW_HARD,
                flatten_hard=self.HP_FLATTEN_HARD,
            )
            for o in ords: result.setdefault(HYDROGEL, []).append(o)

        # 3. Independent VFE Engine (Pure spread capture)
        if self.ENABLE_VFE and VFE in state.order_depths:
            ords = self._obi_mm(
                VFE, state.order_depths[VFE], state.position.get(VFE, 0),
                0, "vfe_ewma",
                ewma_alpha=self.VFE_EWMA_ALPHA, take_edge=self.VFE_TAKE_EDGE,
                obi_thr=self.VFE_OBI_THRESHOLD,
                neutral_front=self.VFE_NEUTRAL_FRONT, neutral_second=self.VFE_NEUTRAL_SECOND,
                lean_agg=self.VFE_LEAN_AGG, lean_def=self.VFE_LEAN_DEF,
                lean_offset=self.VFE_LEAN_OFFSET,
                skew_soft=self.VFE_SKEW_SOFT, skew_hard=self.VFE_SKEW_HARD,
                flatten_hard=self.VFE_FLATTEN_HARD,
            )
            for o in ords: result.setdefault(VFE, []).append(o)

        return result, 0, self._save_state()
