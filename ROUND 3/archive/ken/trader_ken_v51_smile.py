"""trader_ken_v51_smile.py

New architecture: smile-residual statistical arb.

Core idea:
- Build call premium surface each tick from VEV chain.
- Fit quadratic smile over centered moneyness (K - S).
- Trade only strongest residual dislocations (under/over-valued vs smile).
- Keep portfolio delta near zero via VFE hedge.

This is intentionally different from prior EWMA-per-strike strategies.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

import numpy as np
from datamodel import Order, OrderDepth, TradingState

VFE = "VELVETFRUIT_EXTRACT"
HYDRO = "HYDROGEL_PACK"
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]

DELTA = {
    4000: 0.95,
    4500: 0.90,
    5000: 0.82,
    5100: 0.70,
    5200: 0.57,
    5300: 0.44,
    5400: 0.31,
    5500: 0.21,
    6000: 0.08,
    6500: 0.03,
}


class Trader:
    # Smile module
    VEV_LIMIT = 26
    VEV_ENTRY_Z = 1.85
    VEV_SPREAD_MAX = 5
    VEV_TAKER_MAX = 5
    VEV_VAR_ALPHA = 0.08

    # Hedge module
    VFE_LIMIT = 80
    VFE_HEDGE_GAIN = 0.70
    VFE_HEDGE_TAKER_MAX = 24
    VFE_MAKER_EDGE = 2.8
    VFE_MAKER_MAX = 12

    # Optional small hydro carry
    ENABLE_HYDRO = True
    HYDRO_LIMIT = 40
    HYDRO_ALPHA = 0.14
    HYDRO_EDGE = 2.4
    HYDRO_TAKER_EDGE = 4.0
    HYDRO_TAKER_MAX = 6

    # Risk
    NET_DELTA_HARD = 65.0
    NET_DELTA_SOFT = 45.0

    def __init__(self):
        self.h: Dict = {}

    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.h = json.loads(state.traderData)
            except Exception:
                self.h = {}
        self.h.setdefault("resid_var", {})
        self.h.setdefault("vfe_ewma", None)
        self.h.setdefault("hydro_ewma", None)
        for k in STRIKES:
            self.h["resid_var"].setdefault(str(k), 4.0)

    def _save(self) -> str:
        return json.dumps(self.h)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    def _net_delta(self, state: TradingState) -> float:
        d = float(state.position.get(VFE, 0))
        for k in STRIKES:
            d += state.position.get(f"VEV_{k}", 0) * DELTA[k]
        return d

    def _risk_scale(self, state: TradingState) -> float:
        nd = abs(self._net_delta(state))
        if nd >= self.NET_DELTA_HARD:
            return 0.35
        if nd >= self.NET_DELTA_SOFT:
            return 0.65
        return 1.0

    def _build_chain(self, state: TradingState, s_mid: float):
        rows = []
        for k in STRIKES:
            sym = f"VEV_{k}"
            d = state.order_depths.get(sym)
            if d is None:
                continue
            bb, ba = self._top(d)
            if bb is None or ba is None or ba <= bb:
                continue
            spread = ba - bb
            mid = (bb + ba) / 2.0
            intrinsic = max(s_mid - k, 0.0)
            prem = mid - intrinsic
            rows.append((k, sym, bb, ba, spread, mid, prem))
        return rows

    def _smile_fit(self, chain, s_mid: float):
        if len(chain) < 4:
            return None
        xs = []
        ys = []
        for k, _sym, _bb, _ba, _sp, _mid, prem in chain:
            xs.append((k - s_mid) / 100.0)
            ys.append(prem)
        x = np.array(xs, dtype=float)
        y = np.array(ys, dtype=float)
        try:
            coef = np.polyfit(x, y, 2)
        except Exception:
            return None
        return coef

    def _vev_smile_logic(self, state: TradingState, s_mid: float, scale: float) -> List[Order]:
        chain = self._build_chain(state, s_mid)
        coef = self._smile_fit(chain, s_mid)
        if coef is None:
            return []

        cands = []
        for k, sym, bb, ba, spread, _mid, prem in chain:
            if spread > self.VEV_SPREAD_MAX:
                continue
            x = (k - s_mid) / 100.0
            fair_prem = float(np.polyval(coef, x))
            resid = prem - fair_prem
            key = str(k)
            prev_var = float(self.h["resid_var"].get(key, 4.0))
            var = (1 - self.VEV_VAR_ALPHA) * prev_var + self.VEV_VAR_ALPHA * (resid * resid)
            var = max(1.0, var)
            self.h["resid_var"][key] = var
            z = resid / (var ** 0.5)
            cands.append((abs(z), z, k, sym, bb, ba))

        if not cands:
            return []

        # Trade top two dislocations to express relative-value.
        cands.sort(reverse=True, key=lambda t: t[0])
        top = cands[:2]
        orders: List[Order] = []
        taker_max = max(1, int(self.VEV_TAKER_MAX * scale))
        for _az, z, k, sym, bb, ba in top:
            if abs(z) < self.VEV_ENTRY_Z:
                continue
            d = state.order_depths[sym]
            pos = int(state.position.get(sym, 0))
            lim = self.VEV_LIMIT
            if z > 0 and pos > -lim:
                sz = min(taker_max, lim + pos, d.buy_orders.get(bb, 0))
                if sz > 0:
                    orders.append(Order(sym, bb, -sz))
            elif z < 0 and pos < lim:
                sz = min(taker_max, lim - pos, -d.sell_orders.get(ba, 0))
                if sz > 0:
                    orders.append(Order(sym, ba, sz))
        return orders

    def _vfe_hedge_logic(self, state: TradingState, s_mid: float, scale: float) -> List[Order]:
        d = state.order_depths.get(VFE)
        if d is None:
            return []
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return []

        # Target neutralize option delta.
        desired = 0.0
        for k in STRIKES:
            desired += state.position.get(f"VEV_{k}", 0) * (-DELTA[k])
        desired = max(-self.VFE_LIMIT, min(self.VFE_LIMIT, desired))

        pos = int(state.position.get(VFE, 0))
        gap = desired - pos
        orders: List[Order] = []
        hedge_max = max(1, int(self.VFE_HEDGE_TAKER_MAX * scale))
        if gap > 3 and pos < self.VFE_LIMIT:
            sz = min(hedge_max, int(gap * self.VFE_HEDGE_GAIN), self.VFE_LIMIT - pos, -d.sell_orders.get(ba, 0))
            if sz > 0:
                orders.append(Order(VFE, ba, sz))
                pos += sz
        elif gap < -3 and pos > -self.VFE_LIMIT:
            sz = min(hedge_max, int((-gap) * self.VFE_HEDGE_GAIN), self.VFE_LIMIT + pos, d.buy_orders.get(bb, 0))
            if sz > 0:
                orders.append(Order(VFE, bb, -sz))
                pos -= sz

        # Light maker around ewma.
        mid = (bb + ba) / 2.0
        prev = self.h["vfe_ewma"]
        ew = mid if prev is None else 0.84 * prev + 0.16 * mid
        self.h["vfe_ewma"] = ew
        qbid = int(round(ew - self.VFE_MAKER_EDGE))
        qask = int(round(ew + self.VFE_MAKER_EDGE))
        if qbid >= ba:
            qbid = ba - 1
        if qask <= bb:
            qask = bb + 1
        if qbid < qask:
            room_long = min(self.VFE_LIMIT - pos, self.VFE_MAKER_MAX)
            room_short = min(self.VFE_LIMIT + pos, self.VFE_MAKER_MAX)
            if room_long > 0:
                orders.append(Order(VFE, qbid, room_long))
            if room_short > 0:
                orders.append(Order(VFE, qask, -room_short))
        return orders

    def _hydro_logic(self, state: TradingState, scale: float) -> List[Order]:
        if not self.ENABLE_HYDRO:
            return []
        d = state.order_depths.get(HYDRO)
        if d is None:
            return []
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0
        prev = self.h["hydro_ewma"]
        ew = mid if prev is None else (1 - self.HYDRO_ALPHA) * prev + self.HYDRO_ALPHA * mid
        self.h["hydro_ewma"] = ew
        fair = ew
        pos = int(state.position.get(HYDRO, 0))
        lim = self.HYDRO_LIMIT
        taker_max = max(1, int(self.HYDRO_TAKER_MAX * scale))
        maker_max = max(2, int(18 * scale))

        orders: List[Order] = []
        if ba <= fair - self.HYDRO_TAKER_EDGE and pos < lim:
            sz = min(taker_max, lim - pos, -d.sell_orders.get(ba, 0))
            if sz > 0:
                orders.append(Order(HYDRO, ba, sz))
                pos += sz
        if bb >= fair + self.HYDRO_TAKER_EDGE and pos > -lim:
            sz = min(taker_max, lim + pos, d.buy_orders.get(bb, 0))
            if sz > 0:
                orders.append(Order(HYDRO, bb, -sz))
                pos -= sz

        qbid = int(round(fair - self.HYDRO_EDGE))
        qask = int(round(fair + self.HYDRO_EDGE))
        if qbid >= ba:
            qbid = ba - 1
        if qask <= bb:
            qask = bb + 1
        if qbid < qask:
            room_long = min(lim - pos, maker_max)
            room_short = min(lim + pos, maker_max)
            if room_long > 0:
                orders.append(Order(HYDRO, qbid, room_long))
            if room_short > 0:
                orders.append(Order(HYDRO, qask, -room_short))
        return orders

    def run(self, state: TradingState):
        self._load(state)
        result: Dict[str, List[Order]] = {}

        # Need VFE top for smile center
        vd = state.order_depths.get(VFE)
        s_mid = None
        if vd is not None:
            bb, ba = self._top(vd)
            if bb is not None and ba is not None:
                s_mid = (bb + ba) / 2.0

        scale = self._risk_scale(state)

        if s_mid is not None:
            for o in self._vev_smile_logic(state, s_mid, scale):
                result.setdefault(o.symbol, []).append(o)
            for o in self._vfe_hedge_logic(state, s_mid, scale):
                result.setdefault(o.symbol, []).append(o)

        for o in self._hydro_logic(state, scale):
            result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save()

