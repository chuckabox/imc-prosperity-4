"""trader_ken_v8_balanced.py — v6-style upside with empirical reliability controls.

Philosophy:
- Keep the strong HYDROGEL + VFE MM engines from v6.
- Keep VEV long-vol entries as primary alpha capture.
- Add only "guard-rail" controls:
  1) empirical intrinsic+premium fair for VEV (online per-strike EWMA),
  2) opportunistic VEV unwind when clearly rich vs fair,
  2) sparse, partial VFE hedge only when portfolio delta gets extreme.
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
    sqrt_t = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1)


HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]
TIMESTAMP_UNITS_PER_DAY = 1_000_000


class Trader:
    ENABLE_HYDROGEL = True
    ENABLE_VFE_MM = True
    ENABLE_VEV = True
    ENABLE_GUARD_HEDGE = False

    LIMITS: Dict[str, int] = {
        HYDROGEL: 80,
        VFE: 80,
        **{s: 60 for s in VEV_SYMBOLS},
    }

    # HYDROGEL knobs
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

    # VFE MM knobs
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

    # VEV alpha knobs
    VEV_SIGMA = 0.018
    VEV_ACTIVE_STRIKES = [5000, 5100, 5200, 5300, 5400]
    VEV_BID_EDGE_REQ = 1.2
    VEV_TAKE_EDGE = 6.5
    VEV_PER_STRIKE_CAP = 48
    VEV_BID_SIZE = 12
    VEV_EXIT_EDGE = 10.0
    VEV_EXIT_MAX = 6
    VEV_PREM_ALPHA = 0.05
    VEV_PREM_BOUNDS: Dict[str, Tuple[float, float]] = {
        "VEV_5000": (2.0, 12.0),
        "VEV_5100": (10.0, 28.0),
        "VEV_5200": (30.0, 70.0),
        "VEV_5300": (30.0, 70.0),
        "VEV_5400": (8.0, 28.0),
    }
    VEV_PREM_INIT: Dict[str, float] = {
        "VEV_5000": 6.0,
        "VEV_5100": 19.0,
        "VEV_5200": 49.0,
        "VEV_5300": 48.0,
        "VEV_5400": 17.0,
    }
    VEV_TAKE_EDGE_BY_STRIKE: Dict[int, float] = {
        5000: 5.0,
        5100: 6.0,
        5200: 6.5,
        5300: 6.5,
        5400: 6.5,
    }
    VEV_BID_EDGE_BY_STRIKE: Dict[int, float] = {
        5000: 0.8,
        5100: 1.0,
        5200: 1.2,
        5300: 1.2,
        5400: 1.3,
    }
    VEV_CAP_BY_STRIKE: Dict[int, int] = {
        5000: 34,
        5100: 48,
        5200: 48,
        5300: 44,
        5400: 42,
    }

    # Reliability guard rail: hedge only extreme delta
    HEDGE_TRIGGER = 52.0
    HEDGE_RATIO = 0.25
    HEDGE_MAX = 10

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
        self.history.setdefault("vev_prem", {})
        self.history.setdefault("last_ts", -1)
        self.history.setdefault("day", 0)
        if not isinstance(self.history["vev_prem"], dict):
            self.history["vev_prem"] = {}
        for sym, init in self.VEV_PREM_INIT.items():
            self.history["vev_prem"].setdefault(sym, init)
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
            if sz > 0:
                orders.append(Order(symbol, ba, sz))
                pos += sz
        if bb >= fair + take_edge and pos > -limit:
            sz = min(limit + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(symbol, bb, -sz))
                pos -= sz

        bullish = obi > obi_thr
        bearish = obi < -obi_thr
        room_long = max(0, limit - pos)
        room_short = max(0, limit + pos)

        if pos >= flatten_hard:
            buy_front = buy_second = 0
        else:
            if bullish:
                buy_front = min(lean_agg, room_long)
            elif bearish:
                buy_front = min(lean_def, room_long)
            else:
                buy_front = min(neutral_front, room_long)
            buy_second = min(neutral_second, max(0, room_long - buy_front))

        if pos <= -flatten_hard:
            sell_front = sell_second = 0
        else:
            if bearish:
                sell_front = min(lean_agg, room_short)
            elif bullish:
                sell_front = min(lean_def, room_short)
            else:
                sell_front = min(neutral_front, room_short)
            sell_second = min(neutral_second, max(0, room_short - sell_front))

        if pos >= skew_hard:
            skew = -2
        elif pos >= skew_soft:
            skew = -1
        elif pos <= -skew_hard:
            skew = 2
        elif pos <= -skew_soft:
            skew = 1
        else:
            skew = 0

        if bullish:
            qbid = bb + 1 + skew
            qask = ba + lean_offset + skew
        elif bearish:
            qbid = bb - lean_offset + skew
            qask = ba - 1 + skew
        else:
            qbid = bb + 1 + skew
            qask = ba - 1 + skew

        if qbid >= qask:
            qbid = qask - 1

        if buy_front > 0:
            orders.append(Order(symbol, qbid, buy_front))
        if sell_front > 0:
            orders.append(Order(symbol, qask, -sell_front))
        if buy_second > 0:
            orders.append(Order(symbol, qbid - 2, buy_second))
        if sell_second > 0:
            orders.append(Order(symbol, qask + 2, -sell_second))
        return orders

    def _hydrogel_logic(self, state: TradingState) -> List[Order]:
        if HYDROGEL not in state.order_depths:
            return []
        return self._obi_mm(
            HYDROGEL,
            state.order_depths[HYDROGEL],
            state.position.get(HYDROGEL, 0),
            "hp_ewma",
            ewma_alpha=self.HP_EWMA_ALPHA,
            take_edge=self.HP_TAKE_EDGE,
            obi_thr=self.HP_OBI_THRESHOLD,
            neutral_front=self.HP_NEUTRAL_FRONT,
            neutral_second=self.HP_NEUTRAL_SECOND,
            lean_agg=self.HP_LEAN_AGGRESSIVE,
            lean_def=self.HP_LEAN_DEFENSIVE,
            lean_offset=self.HP_LEAN_OFFSET_DEFENSIVE,
            skew_soft=self.HP_SKEW_SOFT,
            skew_hard=self.HP_SKEW_HARD,
            flatten_hard=self.HP_FLATTEN_HARD,
        )

    def _vfe_mm_logic(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        return self._obi_mm(
            VFE,
            state.order_depths[VFE],
            state.position.get(VFE, 0),
            "vfe_ewma",
            ewma_alpha=self.VFE_EWMA_ALPHA,
            take_edge=self.VFE_TAKE_EDGE,
            obi_thr=self.VFE_OBI_THRESHOLD,
            neutral_front=self.VFE_NEUTRAL_FRONT,
            neutral_second=self.VFE_NEUTRAL_SECOND,
            lean_agg=self.VFE_LEAN_AGG,
            lean_def=self.VFE_LEAN_DEF,
            lean_offset=self.VFE_LEAN_OFFSET,
            skew_soft=self.VFE_SKEW_SOFT,
            skew_hard=self.VFE_SKEW_HARD,
            flatten_hard=self.VFE_FLATTEN_HARD,
        )

    def _vev_logic(self, state: TradingState) -> Tuple[List[Order], float]:
        if VFE not in state.order_depths:
            return [], 0.0
        vfe_mid = self._mid(state.order_depths[VFE])
        if vfe_mid is None:
            return [], 0.0
        tte = self._tte_days(state.timestamp)
        sigma = self.VEV_SIGMA
        out: List[Order] = []
        opt_delta = 0.0

        for k in self.VEV_ACTIVE_STRIKES:
            sym = f"VEV_{k}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            bb, ba, _, _ = self._top(depth)
            if bb is None or ba is None:
                continue
            intrinsic = max(vfe_mid - k, 0.0)
            # Keep BS as a soft anchor, but trade mainly on empirical time value.
            bs_fair = bs_call(vfe_mid, k, tte, sigma)
            obs_prem = mid = (bb + ba) / 2.0
            obs_prem = mid - intrinsic
            prem_state = self.history["vev_prem"].get(sym, self.VEV_PREM_INIT.get(sym, 0.0))
            prem = (1.0 - self.VEV_PREM_ALPHA) * prem_state + self.VEV_PREM_ALPHA * obs_prem
            lo, hi = self.VEV_PREM_BOUNDS.get(sym, (0.0, 1e9))
            prem = max(lo, min(hi, prem))
            self.history["vev_prem"][sym] = prem

            emp_fair = intrinsic + prem
            fair = 0.2 * bs_fair + 0.8 * emp_fair
            delta = bs_delta(vfe_mid, k, tte, sigma)
            pos = state.position.get(sym, 0)
            cap = min(self.LIMITS[sym], self.VEV_CAP_BY_STRIKE.get(k, self.VEV_PER_STRIKE_CAP))
            take_edge = self.VEV_TAKE_EDGE_BY_STRIKE.get(k, self.VEV_TAKE_EDGE)
            bid_edge = self.VEV_BID_EDGE_BY_STRIKE.get(k, self.VEV_BID_EDGE_REQ)

            if ba < fair - take_edge and pos < cap:
                size = min(cap - pos, -depth.sell_orders[ba])
                if size > 0:
                    out.append(Order(sym, ba, size))
                    pos += size

            quote_bid = bb + 1
            if quote_bid <= fair - bid_edge and pos < cap:
                size = min(self.VEV_BID_SIZE, cap - pos)
                if size > 0:
                    out.append(Order(sym, quote_bid, size))
                    pos += size

            # Reliability guard: take profit / de-risk when market gets clearly rich.
            rich_edge = bb - fair
            if rich_edge >= self.VEV_EXIT_EDGE and pos > 0:
                size = min(pos, depth.buy_orders[bb], self.VEV_EXIT_MAX)
                if size > 0:
                    out.append(Order(sym, bb, -size))
                    pos -= size

            opt_delta += pos * delta

        return out, opt_delta

    def _guard_hedge_logic(self, state: TradingState, opt_delta: float) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        bb, ba, _, _ = self._top(state.order_depths[VFE])
        if bb is None or ba is None:
            return []
        vfe_pos = state.position.get(VFE, 0)
        residual = opt_delta + vfe_pos
        if abs(residual) < self.HEDGE_TRIGGER:
            return []

        target = -self.HEDGE_RATIO * residual
        qty = int(max(-self.HEDGE_MAX, min(self.HEDGE_MAX, target)))
        if qty == 0:
            return []

        limit = self.LIMITS[VFE]
        if qty > 0:
            qty = min(qty, limit - vfe_pos)
            if qty > 0:
                return [Order(VFE, ba, qty)]
            return []
        qty = min(-qty, limit + vfe_pos)
        if qty > 0:
            return [Order(VFE, bb, -qty)]
        return []

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        if self.ENABLE_HYDROGEL:
            for o in self._hydrogel_logic(state):
                result.setdefault(o.symbol, []).append(o)

        if self.ENABLE_VFE_MM:
            for o in self._vfe_mm_logic(state):
                result.setdefault(o.symbol, []).append(o)

        opt_delta = 0.0
        if self.ENABLE_VEV:
            vev_orders, opt_delta = self._vev_logic(state)
            for o in vev_orders:
                result.setdefault(o.symbol, []).append(o)

        if self.ENABLE_GUARD_HEDGE and self.ENABLE_VEV:
            for o in self._guard_hedge_logic(state, opt_delta):
                result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save_state()
