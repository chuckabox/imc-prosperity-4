"""trader_ken_v11.py — The Anchor & Spread strategy

This version fixes the massive PnL drops identified in previous rounds.
Analysis showed that HYDROGEL_PACK was creating drawdowns by chasing local trends
using an lagging EWMA. 

v11 Changes:
1. HYDROGEL_PACK: Hard-anchored "Fair Value" to 9995.0. No more trend-chase.
2. Risk tightening: Reduced HYDROGEL neutral inventory sizes.
3. Options: Maintained v10's "This is not a pipe" model-free MM logic.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]

# Empirical Deltas from Day 0 Regression
EMPIRICAL_DELTAS = {
    "VEV_4000": 0.74,
    "VEV_4500": 0.66,
    "VEV_5000": 0.65,
    "VEV_5100": 0.56,
    "VEV_5200": 0.43,
    "VEV_5300": 0.27,
    "VEV_5400": 0.14,
    "VEV_5500": 0.06,
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

    # ── HYDROGEL knobs (Anchored 9995 Logic) ──────────────────────────────
    HP_FAIR_PRICE = 9995.0
    HP_TAKE_EDGE = 1  # Aggressive takers around 9995 anchor
    HP_OBI_THRESHOLD = 0.10
    HP_NEUTRAL_FRONT = 10 # Tightened from 20
    HP_NEUTRAL_SECOND = 8  # Tightened from 12
    HP_LEAN_AGGRESSIVE = 25
    HP_LEAN_DEFENSIVE = 5
    HP_LEAN_OFFSET_DEFENSIVE = 2
    HP_SKEW_SOFT = 25
    HP_SKEW_HARD = 50
    HP_FLATTEN_HARD = 70

    # ── VFE knobs ─────────────────────────────────────────────────────────
    VFE_EWMA_ALPHA = 0.20
    VFE_TAKE_EDGE = 2
    VFE_OBI_THRESHOLD = 0.15
    VFE_NEUTRAL_FRONT = 15
    VFE_NEUTRAL_SECOND = 8
    VFE_LEAN_AGG = 25
    VFE_LEAN_DEF = 5
    VFE_LEAN_OFFSET = 3
    VFE_SKEW_SOFT = 25
    VFE_SKEW_HARD = 50
    VFE_FLATTEN_HARD = 70

    # ── VEV knobs (Model-Free OBI MM) ─────────────────────────────────────
    VEV_ACTIVE_STRIKES = [5100, 5200, 5300, 5400]
    VEV_EWMA_ALPHA = 0.25
    VEV_OBI_THRESHOLD = 0.10
    VEV_NEUTRAL_FRONT = 12
    VEV_NEUTRAL_SECOND = 6
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
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("opt_delta_total", 0.0)
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
        fixed_fair: Optional[float] = None, # New: Skip EWMA if fair is known
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
        if fixed_fair is not None:
            fair = fixed_fair
        else:
            prev = self.history.get(ewma_key)
            ewma = mid if prev is None else (1 - ewma_alpha) * prev + ewma_alpha * mid
            self.history[ewma_key] = ewma
            fair = ewma

        obi = (bv - av) / (bv + av) if (bv + av) > 0 else 0.0

        if ba <= fair - take_edge and pos_real < limit:
            sz = min(limit - pos_real, -depth.sell_orders[ba])
            if sz > 0: orders.append(Order(symbol, ba, sz)); pos_real += sz
        if bb >= fair + take_edge and pos_real > -limit:
            sz = min(limit + pos_real, depth.buy_orders[bb])
            if sz > 0: orders.append(Order(symbol, bb, -sz)); pos_real -= sz

        dist = pos_real - pos_target
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

        if dist >= skew_hard: skew = -2
        elif dist >= skew_soft: skew = -1
        elif dist <= -skew_hard: skew = 2
        elif dist <= -skew_soft: skew = 1
        else: skew = 0

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

    def _hydrogel_logic(self, state: TradingState) -> List[Order]:
        if HYDROGEL not in state.order_depths:
            return []
        return self._obi_mm(
            HYDROGEL, state.order_depths[HYDROGEL], state.position.get(HYDROGEL, 0),
            0, "hp_ewma",
            fixed_fair=self.HP_FAIR_PRICE, # The Anchor fix
            ewma_alpha=0.20, take_edge=self.HP_TAKE_EDGE,
            obi_thr=self.HP_OBI_THRESHOLD,
            neutral_front=self.HP_NEUTRAL_FRONT, neutral_second=self.HP_NEUTRAL_SECOND,
            lean_agg=self.HP_LEAN_AGGRESSIVE, lean_def=self.HP_LEAN_DEFENSIVE,
            lean_offset=self.HP_LEAN_OFFSET_DEFENSIVE,
            skew_soft=self.HP_SKEW_SOFT, skew_hard=self.HP_SKEW_HARD,
            flatten_hard=self.HP_FLATTEN_HARD,
        )

    def _vev_logic(self, state: TradingState) -> List[Order]:
        total_delta = 0.0
        orders_all: List[Order] = []

        # 1st Pass: Compute total delta for ALL strikes we hold
        for sym, d in EMPIRICAL_DELTAS.items():
            pos = state.position.get(sym, 0)
            if pos != 0:
                total_delta += pos * d
        self.history["opt_delta_total"] = total_delta

        # 2nd Pass: Market make the active strikes
        for strike in self.VEV_ACTIVE_STRIKES:
            sym = f"VEV_{strike}"
            if sym not in state.order_depths: continue
            
            strike_orders = self._obi_mm(
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
            orders_all.extend(strike_orders)
            
        return orders_all

    def _vfe_logic(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths:
            return []
            
        opt_delta = self.history.get("opt_delta_total", 0.0)
        target_vfe = int(round(-opt_delta))
        
        return self._obi_mm(
            VFE, state.order_depths[VFE], state.position.get(VFE, 0),
            target_vfe, "vfe_ewma",
            ewma_alpha=self.VFE_EWMA_ALPHA, take_edge=self.VFE_TAKE_EDGE,
            obi_thr=self.VFE_OBI_THRESHOLD,
            neutral_front=self.VFE_NEUTRAL_FRONT, neutral_second=self.VFE_NEUTRAL_SECOND,
            lean_agg=self.VFE_LEAN_AGG, lean_def=self.VFE_LEAN_DEF,
            lean_offset=self.VFE_LEAN_OFFSET,
            skew_soft=self.VFE_SKEW_SOFT, skew_hard=self.VFE_SKEW_HARD,
            flatten_hard=self.VFE_FLATTEN_HARD,
        )

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        if self.ENABLE_VEV:
            for o in self._vev_logic(state):
                result.setdefault(o.symbol, []).append(o)

        if self.ENABLE_HYDROGEL:
            for o in self._hydrogel_logic(state):
                result.setdefault(o.symbol, []).append(o)

        if self.ENABLE_VFE:
            for o in self._vfe_logic(state):
                result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save_state()
