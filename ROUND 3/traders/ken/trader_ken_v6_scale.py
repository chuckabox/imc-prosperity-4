"""trader_ken_v6_scale.py — v4_full + scaled VEV (no hedge).

We tried delta-hedging in v5_hedge: it lost 2.6k vs v4_full because in
this capsule VFE drifts +0.3%/day, so long-option-delta exposure is a
*positive* expected return. Hedging it away costs more than the noise
reduction is worth.

v6 doubles down: keep the unhedged stance from v4_full, but scale the
VEV resting-bid book up so we capture more of the IV/RV spread alpha
AND ride more of the VFE drift.

Differences vs v4_full:
  • VEV_PER_STRIKE_CAP: 30 → 50    (closer to the 60 limit)
  • VEV_BID_SIZE:        8 → 12
  • VEV_BID_EDGE_REQ:    2 → 1     (fill more often; smaller per-trade edge)
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]
TIMESTAMP_UNITS_PER_DAY = 1_000_000


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

    # ── HYDROGEL knobs (tuned via sweep_v3_hp.py — see ROUND 3/scratch/sweep_v3_hp.log) ─
    # Sweep top-10 all share thr=0.10, loff=2; nf/lagg are no-ops in that regime.
    HP_EWMA_ALPHA = 0.20
    HP_TAKE_EDGE = 2
    HP_OBI_THRESHOLD = 0.10
    HP_NEUTRAL_FRONT = 20
    HP_NEUTRAL_SECOND = 12
    HP_LEAN_AGGRESSIVE = 30
    HP_LEAN_DEFENSIVE = 6
    HP_LEAN_OFFSET_DEFENSIVE = 2
    HP_SKEW_SOFT = 25
    HP_SKEW_HARD = 50
    HP_FLATTEN_HARD = 70

    # ── VFE knobs (smaller passives — narrower spread) ─────────────────────
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

    # ── VEV knobs (resting bids, no hedge — VFE MM absorbs delta) ──────────
    VEV_SIGMA = 0.018
    VEV_ACTIVE_STRIKES = [5100, 5200, 5300, 5400]
    VEV_BID_EDGE_REQ = 1.0
    VEV_TAKE_EDGE = 8.0
    VEV_PER_STRIKE_CAP = 50
    VEV_BID_SIZE = 12

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

    @staticmethod
    def _mid(depth: OrderDepth) -> Optional[float]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0

    def _tte_days(self, ts: int) -> float:
        day = int(self.history.get("day", 0))
        return max(0.01, (8 - day) - ts / TIMESTAMP_UNITS_PER_DAY)

    # ── Generic OBI-aware MM (used by HYDROGEL and VFE) ────────────────────
    def _obi_mm(
        self,
        symbol: str,
        depth: OrderDepth,
        pos: int,
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
        fair = ewma

        obi = (bv - av) / (bv + av) if (bv + av) > 0 else 0.0

        if ba <= fair - take_edge and pos < limit:
            sz = min(limit - pos, -depth.sell_orders[ba])
            if sz > 0: orders.append(Order(symbol, ba, sz)); pos += sz
        if bb >= fair + take_edge and pos > -limit:
            sz = min(limit + pos, depth.buy_orders[bb])
            if sz > 0: orders.append(Order(symbol, bb, -sz)); pos -= sz

        bullish = obi > obi_thr
        bearish = obi < -obi_thr
        room_long = max(0, limit - pos)
        room_short = max(0, limit + pos)

        if pos >= flatten_hard:
            buy_front = buy_second = 0
        else:
            if bullish: buy_front = min(lean_agg, room_long)
            elif bearish: buy_front = min(lean_def, room_long)
            else: buy_front = min(neutral_front, room_long)
            buy_second = min(neutral_second, max(0, room_long - buy_front))

        if pos <= -flatten_hard:
            sell_front = sell_second = 0
        else:
            if bearish: sell_front = min(lean_agg, room_short)
            elif bullish: sell_front = min(lean_def, room_short)
            else: sell_front = min(neutral_front, room_short)
            sell_second = min(neutral_second, max(0, room_short - sell_front))

        if pos >= skew_hard: skew = -2
        elif pos >= skew_soft: skew = -1
        elif pos <= -skew_hard: skew = 2
        elif pos <= -skew_soft: skew = 1
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
            "hp_ewma",
            ewma_alpha=self.HP_EWMA_ALPHA, take_edge=self.HP_TAKE_EDGE,
            obi_thr=self.HP_OBI_THRESHOLD,
            neutral_front=self.HP_NEUTRAL_FRONT, neutral_second=self.HP_NEUTRAL_SECOND,
            lean_agg=self.HP_LEAN_AGGRESSIVE, lean_def=self.HP_LEAN_DEFENSIVE,
            lean_offset=self.HP_LEAN_OFFSET_DEFENSIVE,
            skew_soft=self.HP_SKEW_SOFT, skew_hard=self.HP_SKEW_HARD,
            flatten_hard=self.HP_FLATTEN_HARD,
        )

    def _vfe_logic(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        return self._obi_mm(
            VFE, state.order_depths[VFE], state.position.get(VFE, 0),
            "vfe_ewma",
            ewma_alpha=self.VFE_EWMA_ALPHA, take_edge=self.VFE_TAKE_EDGE,
            obi_thr=self.VFE_OBI_THRESHOLD,
            neutral_front=self.VFE_NEUTRAL_FRONT, neutral_second=self.VFE_NEUTRAL_SECOND,
            lean_agg=self.VFE_LEAN_AGG, lean_def=self.VFE_LEAN_DEF,
            lean_offset=self.VFE_LEAN_OFFSET,
            skew_soft=self.VFE_SKEW_SOFT, skew_hard=self.VFE_SKEW_HARD,
            flatten_hard=self.VFE_FLATTEN_HARD,
        )

    def _vev_logic(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        vfe_mid = self._mid(state.order_depths[VFE])
        if vfe_mid is None:
            return []
        T = self._tte_days(state.timestamp)
        sigma = self.VEV_SIGMA
        out: List[Order] = []

        for K in self.VEV_ACTIVE_STRIKES:
            sym = f"VEV_{K}"
            if sym not in state.order_depths:
                continue
            depth = state.order_depths[sym]
            bb, ba, _, _ = self._top(depth)
            if bb is None or ba is None:
                continue
            fair = bs_call(vfe_mid, K, T, sigma)
            pos = state.position.get(sym, 0)
            cap = min(self.LIMITS[sym], self.VEV_PER_STRIKE_CAP)

            if ba < fair - self.VEV_TAKE_EDGE and pos < cap:
                size = min(cap - pos, -depth.sell_orders[ba])
                if size > 0:
                    out.append(Order(sym, ba, size)); pos += size

            quote_bid = bb + 1
            if quote_bid <= fair - self.VEV_BID_EDGE_REQ and pos < cap:
                size = min(self.VEV_BID_SIZE, cap - pos)
                if size > 0:
                    out.append(Order(sym, quote_bid, size))
        return out

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        if self.ENABLE_HYDROGEL:
            for o in self._hydrogel_logic(state):
                result.setdefault(o.symbol, []).append(o)

        if self.ENABLE_VFE:
            for o in self._vfe_logic(state):
                result.setdefault(o.symbol, []).append(o)

        if self.ENABLE_VEV:
            for o in self._vev_logic(state):
                result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save_state()
