"""trader_ken_v9.py — The Delta-Hedged Asian Option MM

This algorithm solves the "La trahison des images" Alpha.
The "Treachery of Images" indicates the options are NOT European options on
the terminal spot price. They are Asian options (settling on the average price).
Realized Vol of VELVETFRUIT_EXTRACT = ~2.15% per day.
Theoretical Asian volatility = 2.15% / sqrt(3) ≈ 1.241%.
Market quoted IV is ~1.25%.
Conclusion: The options are fairly priced! Previous unhedged long-option strategies
(like v6) assumed options were massively cheap (predicting IV was 1.25% against an RV of 2.15%)
and aggressively bought them without hedging. When VFE dropped, it caused heavy losses.

Actions in v9:
1. Two-sided market-making on VEV options based on Asian volatility (1.241%).
2. Compute the exact option-portfolio Delta.
3. Automatically adjust the `VELVETFRUIT_EXTRACT` (VFE) market-making engine to
   track a target Delta-neutralizing inventory, earning VFE spread while passively
   shedding directional exposure.
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

def bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return 1.0 if S > K else 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    return _norm_cdf(d1)


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

    # ── HYDROGEL knobs (tuned via sweep_v3_hp.py) ──────────────────────────
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

    # ── VEV knobs (Asian Delta-Hedged MM) ─────────────────────────────────
    VEV_SIGMA = 0.0125  # Asian volatility approx 2.15/sqrt(3), fits market
    VEV_ACTIVE_STRIKES = [5100, 5200, 5300, 5400]
    VEV_EDGE_REQ = 1.0  # Take 1.0 resting edge
    VEV_PER_STRIKE_CAP = 30
    VEV_QUOTE_SIZE = 12

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
        self.history.setdefault("option_delta", 0.0)
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
        fair = ewma

        obi = (bv - av) / (bv + av) if (bv + av) > 0 else 0.0

        if ba <= fair - take_edge and pos_real < limit:
            sz = min(limit - pos_real, -depth.sell_orders[ba])
            if sz > 0: orders.append(Order(symbol, ba, sz)); pos_real += sz
        if bb >= fair + take_edge and pos_real > -limit:
            sz = min(limit + pos_real, depth.buy_orders[bb])
            if sz > 0: orders.append(Order(symbol, bb, -sz)); pos_real -= sz

        # Dist holds our true skew condition. E.g. if we want target +20 VFE
        # and we hold 0, dist = -20. This pushes the skew threshold positive.
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
        
        # Hydrogel has an explicit target of 0 since it is uncorrelated beta
        return self._obi_mm(
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

    def _vev_logic(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        vfe_mid = self._mid(state.order_depths[VFE])
        if vfe_mid is None:
            return []
        T = self._tte_days(state.timestamp)
        sigma = self.VEV_SIGMA
        
        out: List[Order] = []
        total_delta = 0.0

        for K in VEV_STRIKES:
            sym = f"VEV_{K}"
            pos = state.position.get(sym, 0)
            
            if pos != 0:
                d = bs_delta(vfe_mid, K, T, sigma)
                total_delta += pos * d

            # Only actively trade the chosen active strikes
            if sym not in state.order_depths or K not in self.VEV_ACTIVE_STRIKES:
                continue

            depth = state.order_depths[sym]
            bb, ba, _, _ = self._top(depth)
            if bb is None or ba is None:
                continue
            
            fair = bs_call(vfe_mid, K, T, sigma)
            cap = min(self.LIMITS[sym], self.VEV_PER_STRIKE_CAP)

            # Two-sided quoting!
            quote_bid = math.floor(fair - self.VEV_EDGE_REQ)
            if quote_bid > bb: quote_bid = bb + 1
            
            quote_ask = math.ceil(fair + self.VEV_EDGE_REQ)
            if quote_ask < ba: quote_ask = ba - 1
            
            if quote_bid >= quote_ask:
                quote_bid = quote_ask - 1

            if pos < cap:
                sz = min(self.VEV_QUOTE_SIZE, cap - pos)
                if sz > 0: out.append(Order(sym, quote_bid, sz))
            
            if pos > -cap:
                sz = min(self.VEV_QUOTE_SIZE, cap + pos)
                if sz > 0: out.append(Order(sym, quote_ask, -sz))
                
        self.history["option_delta"] = total_delta
        return out

    def _vfe_logic(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths:
            return []
            
        # Instead of 0, our target inventory is the negative option delta.
        # This naturally skews our VFE quotes to delta hedge our options.
        opt_delta = self.history.get("option_delta", 0.0)
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

        # MUST RUN VEV LOGIC FIRST TO UPDATE `total_delta` state FOR VFE!
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
