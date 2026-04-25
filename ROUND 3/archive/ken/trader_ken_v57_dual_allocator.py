"""trader_ken_v57_dual_allocator.py

Dual-agent architecture:
- Agent H (Hydro execution): maker-first with selective taker.
- Agent O (Options timing): sparse residual z-score taker on selected strikes.
- Allocator: aggressive hydro + sparse options in high-vol only.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDRO = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100]

PREM_INIT: Dict[int, float] = {5000: 5.81, 5100: 19.09}
PREM_BOUNDS: Dict[int, Tuple[float, float]] = {5000: (2.0, 14.0), 5100: (10.0, 30.0)}
STRIKE_CAP: Dict[int, int] = {5000: 36, 5100: 28}
VEV_DELTA_APPROX: Dict[int, float] = {5000: 0.82, 5100: 0.70}


class Trader:
    # Shared risk
    HP_LIMIT = 80
    VFE_LIMIT = 80
    NET_DELTA_HARD = 64.0
    NET_DELTA_SOFT = 44.0

    # Hydro agent
    HP_ANCHOR = 9993.0
    HP_ALPHA = 0.20
    HP_MAKER_EDGE = 2.0
    HP_TAKER_EDGE = 3.0
    HP_MAKER_BASE = 34
    HP_TAKER_BASE = 14
    HP_TAKER_SPREAD_MAX = 13

    # Options agent
    PREM_ALPHA = 0.06
    PREM_VAR_ALPHA = 0.08
    VEV_Z_ENTRY = 2.05
    VEV_SPREAD_MAX = {5000: 8, 5100: 6}
    VEV_TAKER_BASE = {5000: 4, 5100: 2}

    # VFE support
    VFE_ALPHA = 0.20
    VFE_MAKER_EDGE = 2.3
    VFE_TAKER_EDGE = 5.0
    VFE_TAKER_BASE = 9
    VFE_MAKER_BASE = 14

    # Allocator regime params
    VOL_ALPHA = 0.10
    VOL_ON = 1.45
    VOL_OFF = 1.05

    def __init__(self):
        self.h: Dict = {}

    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.h = json.loads(state.traderData)
            except Exception:
                self.h = {}
        self.h.setdefault("hp_ewma", None)
        self.h.setdefault("vfe_ewma", None)
        self.h.setdefault("prem", {})
        self.h.setdefault("prem_var", {})
        self.h.setdefault("vfe_jump_ewma", 0.0)
        self.h.setdefault("last_vfe_mid", None)
        self.h.setdefault("opt_regime_on", False)
        for k in VEV_STRIKES:
            self.h["prem"].setdefault(str(k), PREM_INIT[k])
            self.h["prem_var"].setdefault(str(k), 9.0)

    def _save(self) -> str:
        return json.dumps(self.h)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    def _net_delta(self, state: TradingState) -> float:
        d = float(state.position.get(VFE, 0))
        for k in VEV_STRIKES:
            d += state.position.get(f"VEV_{k}", 0) * VEV_DELTA_APPROX[k]
        return d

    def _allocator(self, state: TradingState, vfe_mid: Optional[float]) -> Tuple[float, float]:
        """Return (hydro_scale, opt_scale)."""
        net_delta = abs(self._net_delta(state))
        risk_scale = 1.0
        if net_delta >= self.NET_DELTA_HARD:
            risk_scale = 0.35
        elif net_delta >= self.NET_DELTA_SOFT:
            risk_scale = 0.65

        # Update volatility regime off VFE jumps.
        if vfe_mid is not None and self.h.get("last_vfe_mid") is not None:
            jump = abs(float(vfe_mid) - float(self.h["last_vfe_mid"]))
            prev = float(self.h.get("vfe_jump_ewma", 0.0))
            vol = (1 - self.VOL_ALPHA) * prev + self.VOL_ALPHA * jump
            self.h["vfe_jump_ewma"] = vol
            on = bool(self.h.get("opt_regime_on", False))
            if on:
                if vol < self.VOL_OFF:
                    on = False
            else:
                if vol > self.VOL_ON:
                    on = True
            self.h["opt_regime_on"] = on
        if vfe_mid is not None:
            self.h["last_vfe_mid"] = vfe_mid

        opt_on = bool(self.h.get("opt_regime_on", False))
        # Budget split
        hydro_scale = risk_scale * (0.95 if opt_on else 1.05)
        opt_scale = risk_scale * (0.55 if opt_on else 0.10)
        return hydro_scale, opt_scale

    def _hydro_agent(self, state: TradingState, scale: float) -> List[Order]:
        d = state.order_depths.get(HYDRO)
        if d is None:
            return []
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0
        prev = self.h["hp_ewma"]
        ew = mid if prev is None else (1 - self.HP_ALPHA) * prev + self.HP_ALPHA * mid
        self.h["hp_ewma"] = ew
        fair = 0.6 * ew + 0.4 * self.HP_ANCHOR
        pos = int(state.position.get(HYDRO, 0))
        lim = self.HP_LIMIT

        taker_max = max(1, int(self.HP_TAKER_BASE * scale))
        maker_max = max(4, int(self.HP_MAKER_BASE * scale))
        spread = ba - bb

        orders: List[Order] = []
        if spread <= self.HP_TAKER_SPREAD_MAX:
            if ba <= fair - self.HP_TAKER_EDGE and pos < lim:
                sz = min(taker_max, lim - pos, -d.sell_orders.get(ba, 0))
                if sz > 0:
                    orders.append(Order(HYDRO, ba, sz))
                    pos += sz
            if bb >= fair + self.HP_TAKER_EDGE and pos > -lim:
                sz = min(taker_max, lim + pos, d.buy_orders.get(bb, 0))
                if sz > 0:
                    orders.append(Order(HYDRO, bb, -sz))
                    pos -= sz

        qbid = int(round(fair - self.HP_MAKER_EDGE))
        qask = int(round(fair + self.HP_MAKER_EDGE))
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

    def _opt_agent(self, state: TradingState, vfe_mid: float, scale: float) -> List[Order]:
        if scale <= 0:
            return []
        cands = []
        for k in VEV_STRIKES:
            sym = f"VEV_{k}"
            d = state.order_depths.get(sym)
            if d is None:
                continue
            bb, ba = self._top(d)
            if bb is None or ba is None or ba <= bb:
                continue
            spread = ba - bb
            if spread > self.VEV_SPREAD_MAX[k]:
                continue

            mid = (bb + ba) / 2.0
            intr = max(vfe_mid - k, 0.0)
            prem_obs = mid - intr
            key = str(k)
            prev = float(self.h["prem"][key])
            prem = (1 - self.PREM_ALPHA) * prev + self.PREM_ALPHA * prem_obs
            lo, hi = PREM_BOUNDS[k]
            prem = max(lo, min(hi, prem))
            self.h["prem"][key] = prem

            resid = prem_obs - prem
            pv = float(self.h["prem_var"][key])
            nv = (1 - self.PREM_VAR_ALPHA) * pv + self.PREM_VAR_ALPHA * (resid * resid)
            nv = max(1.0, nv)
            self.h["prem_var"][key] = nv
            z = resid / (nv ** 0.5)
            fair = intr + prem
            cands.append((abs(z), z, k, sym, bb, ba, fair))

        if not cands:
            return []
        cands.sort(reverse=True, key=lambda x: x[0])
        _, z, k, sym, bb, ba, fair = cands[0]
        if abs(z) < self.VEV_Z_ENTRY:
            return []
        d = state.order_depths[sym]
        pos = int(state.position.get(sym, 0))
        lim = STRIKE_CAP[k]
        taker_max = max(1, int(self.VEV_TAKER_BASE[k] * scale))
        orders: List[Order] = []
        if z <= -self.VEV_Z_ENTRY and ba <= fair and pos < lim:
            sz = min(taker_max, lim - pos, -d.sell_orders.get(ba, 0))
            if sz > 0:
                orders.append(Order(sym, ba, sz))
        elif z >= self.VEV_Z_ENTRY and bb >= fair and pos > -lim:
            sz = min(taker_max, lim + pos, d.buy_orders.get(bb, 0))
            if sz > 0:
                orders.append(Order(sym, bb, -sz))
        return orders

    def _vfe_agent(self, state: TradingState, scale: float) -> List[Order]:
        d = state.order_depths.get(VFE)
        if d is None:
            return []
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0
        prev = self.h["vfe_ewma"]
        ew = mid if prev is None else (1 - self.VFE_ALPHA) * prev + self.VFE_ALPHA * mid
        self.h["vfe_ewma"] = ew
        fair = ew
        pos = int(state.position.get(VFE, 0))
        lim = self.VFE_LIMIT
        taker_max = max(1, int(self.VFE_TAKER_BASE * scale))
        maker_max = max(2, int(self.VFE_MAKER_BASE * scale))

        orders: List[Order] = []
        if ba <= fair - self.VFE_TAKER_EDGE and pos < lim:
            sz = min(taker_max, lim - pos, -d.sell_orders.get(ba, 0))
            if sz > 0:
                orders.append(Order(VFE, ba, sz))
                pos += sz
        if bb >= fair + self.VFE_TAKER_EDGE and pos > -lim:
            sz = min(taker_max, lim + pos, d.buy_orders.get(bb, 0))
            if sz > 0:
                orders.append(Order(VFE, bb, -sz))
                pos -= sz

        qbid = int(round(fair - self.VFE_MAKER_EDGE))
        qask = int(round(fair + self.VFE_MAKER_EDGE))
        if qbid >= ba:
            qbid = ba - 1
        if qask <= bb:
            qask = bb + 1
        if qbid < qask:
            room_long = min(lim - pos, maker_max)
            room_short = min(lim + pos, maker_max)
            if room_long > 0:
                orders.append(Order(VFE, qbid, room_long))
            if room_short > 0:
                orders.append(Order(VFE, qask, -room_short))
        return orders

    def run(self, state: TradingState):
        self._load(state)
        result: Dict[str, List[Order]] = {}

        vfe_mid = None
        vd = state.order_depths.get(VFE)
        if vd is not None:
            bb, ba = self._top(vd)
            if bb is not None and ba is not None:
                vfe_mid = (bb + ba) / 2.0

        hydro_scale, opt_scale = self._allocator(state, vfe_mid)

        for o in self._hydro_agent(state, hydro_scale):
            result.setdefault(o.symbol, []).append(o)

        if vfe_mid is not None:
            for o in self._opt_agent(state, vfe_mid, opt_scale):
                result.setdefault(o.symbol, []).append(o)

        for o in self._vfe_agent(state, max(hydro_scale, opt_scale)):
            result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save()

