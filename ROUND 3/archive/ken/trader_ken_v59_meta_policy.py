"""trader_ken_v59_meta_policy.py

Stricter sibling of v58:
- Faster defense activation and slower release.
- Slightly lower option aggressiveness.
- More conservative maker widths in costly states.
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
STRIKE_CAP: Dict[int, int] = {5000: 38, 5100: 30}
VEV_DELTA_APPROX: Dict[int, float] = {5000: 0.82, 5100: 0.70}


class Trader:
    HP_LIMIT = 80
    VFE_LIMIT = 80
    HP_ANCHOR = 9993.0
    HP_EWMA_ALPHA = 0.20
    VFE_EWMA_ALPHA = 0.20
    PREM_ALPHA = 0.05
    PREM_VAR_ALPHA = 0.08

    A_HP_MAKER_EDGE = 2.4
    A_HP_TAKER_EDGE = 2.8
    A_HP_TAKER_MAX = 16
    A_VFE_MAKER_EDGE = 2.4
    A_VFE_TAKER_EDGE = 4.8
    A_VFE_TAKER_MAX = 10
    A_VEV_Z_ENTRY = 1.85
    A_VEV_TAKER = {5000: 7, 5100: 5}

    B_HP_MAKER_EDGE = 3.1
    B_HP_TAKER_EDGE = 4.6
    B_HP_TAKER_MAX = 6
    B_VFE_MAKER_EDGE = 3.0
    B_VFE_TAKER_EDGE = 6.0
    B_VFE_TAKER_MAX = 5
    B_VEV_Z_ENTRY = 2.25
    B_VEV_TAKER = {5000: 3, 5100: 2}

    VEV_SPREAD_MAX = {5000: 7, 5100: 5}
    NET_DELTA_SOFT = 45.0
    NET_DELTA_HARD = 60.0
    VOL_ALPHA = 0.12
    COST_ON = 1.15
    COST_OFF = 0.85

    def __init__(self):
        self.h: Dict = {}

    def _load(self, state: TradingState):
        if state.traderData:
            try:
                self.h = json.loads(state.traderData)
            except Exception:
                self.h = {}
        self.h.setdefault("hp_ewma", None)
        self.h.setdefault("vfe_ewma", None)
        self.h.setdefault("prem", {})
        self.h.setdefault("prem_var", {})
        self.h.setdefault("last_vfe_mid", None)
        self.h.setdefault("cost_ewma", 0.0)
        self.h.setdefault("defense_on", False)
        for k in VEV_STRIKES:
            self.h["prem"].setdefault(str(k), PREM_INIT[k])
            self.h["prem_var"].setdefault(str(k), 9.0)

    def _save(self):
        return json.dumps(self.h)

    @staticmethod
    def _top(d: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(d.buy_orders.keys()) if d.buy_orders else None
        ba = min(d.sell_orders.keys()) if d.sell_orders else None
        return bb, ba

    def _net_delta(self, state: TradingState) -> float:
        d = float(state.position.get(VFE, 0))
        for k in VEV_STRIKES:
            d += state.position.get(f"VEV_{k}", 0) * VEV_DELTA_APPROX[k]
        return d

    def _scale(self, state: TradingState) -> float:
        nd = abs(self._net_delta(state))
        if nd >= self.NET_DELTA_HARD:
            return 0.30
        if nd >= self.NET_DELTA_SOFT:
            return 0.60
        return 1.0

    def _update_policy(self, vfe_mid: Optional[float], hydro_spread: Optional[int]):
        jump = 0.0
        if vfe_mid is not None and self.h.get("last_vfe_mid") is not None:
            jump = abs(float(vfe_mid) - float(self.h["last_vfe_mid"]))
        if vfe_mid is not None:
            self.h["last_vfe_mid"] = vfe_mid
        hs = float(hydro_spread if hydro_spread is not None else 12.0)
        cost_proxy = 0.62 * jump + 0.38 * max(0.0, hs - 10.0)
        prev = float(self.h.get("cost_ewma", 0.0))
        c = (1 - self.VOL_ALPHA) * prev + self.VOL_ALPHA * cost_proxy
        self.h["cost_ewma"] = c
        on = bool(self.h.get("defense_on", False))
        if on:
            if c < self.COST_OFF:
                on = False
        else:
            if c > self.COST_ON:
                on = True
        self.h["defense_on"] = on
        return on

    def _guarded_maker(self, sym: str, d: OrderDepth, pos: int, fair: float, limit: int, edge: float, mx: int) -> List[Order]:
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return []
        qbid = int(round(fair - edge))
        qask = int(round(fair + edge))
        if qbid >= ba:
            qbid = ba - 1
        if qask <= bb:
            qask = bb + 1
        if qbid >= qask:
            qbid = qask - 1
        out = []
        rl = min(limit - pos, mx)
        rs = min(limit + pos, mx)
        if rl > 0:
            out.append(Order(sym, qbid, rl))
        if rs > 0:
            out.append(Order(sym, qask, -rs))
        return out

    def _hydro(self, state: TradingState, scale: float, defense: bool):
        d = state.order_depths.get(HYDRO)
        if d is None:
            return []
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0
        prev = self.h["hp_ewma"]
        ew = mid if prev is None else (1 - self.HP_EWMA_ALPHA) * prev + self.HP_EWMA_ALPHA * mid
        self.h["hp_ewma"] = ew
        fair = 0.58 * ew + 0.42 * self.HP_ANCHOR
        pos = int(state.position.get(HYDRO, 0))
        lim = self.HP_LIMIT
        if defense:
            maker_edge, taker_edge, taker_base = self.B_HP_MAKER_EDGE, self.B_HP_TAKER_EDGE, self.B_HP_TAKER_MAX
        else:
            maker_edge, taker_edge, taker_base = self.A_HP_MAKER_EDGE, self.A_HP_TAKER_EDGE, self.A_HP_TAKER_MAX
        taker = max(1, int(taker_base * scale))
        maker = max(4, int(24 * scale))
        out: List[Order] = []
        if ba - bb <= 12:
            if ba <= fair - taker_edge and pos < lim:
                q = min(taker, lim - pos, -d.sell_orders.get(ba, 0))
                if q > 0:
                    out.append(Order(HYDRO, ba, q))
                    pos += q
            if bb >= fair + taker_edge and pos > -lim:
                q = min(taker, lim + pos, d.buy_orders.get(bb, 0))
                if q > 0:
                    out.append(Order(HYDRO, bb, -q))
                    pos -= q
        out.extend(self._guarded_maker(HYDRO, d, pos, fair, lim, maker_edge, maker))
        return out

    def _vfe(self, state: TradingState, scale: float, defense: bool):
        d = state.order_depths.get(VFE)
        if d is None:
            return [], None
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return [], None
        mid = (bb + ba) / 2.0
        prev = self.h["vfe_ewma"]
        ew = mid if prev is None else (1 - self.VFE_EWMA_ALPHA) * prev + self.VFE_EWMA_ALPHA * mid
        self.h["vfe_ewma"] = ew
        fair = ew
        pos = int(state.position.get(VFE, 0))
        lim = self.VFE_LIMIT
        if defense:
            maker_edge, taker_edge, taker_base = self.B_VFE_MAKER_EDGE, self.B_VFE_TAKER_EDGE, self.B_VFE_TAKER_MAX
        else:
            maker_edge, taker_edge, taker_base = self.A_VFE_MAKER_EDGE, self.A_VFE_TAKER_EDGE, self.A_VFE_TAKER_MAX
        taker = max(1, int(taker_base * scale))
        maker = max(2, int(12 * scale))
        out: List[Order] = []
        if ba <= fair - taker_edge and pos < lim:
            q = min(taker, lim - pos, -d.sell_orders.get(ba, 0))
            if q > 0:
                out.append(Order(VFE, ba, q))
                pos += q
        if bb >= fair + taker_edge and pos > -lim:
            q = min(taker, lim + pos, d.buy_orders.get(bb, 0))
            if q > 0:
                out.append(Order(VFE, bb, -q))
                pos -= q
        out.extend(self._guarded_maker(VFE, d, pos, fair, lim, maker_edge, maker))
        return out, mid

    def _vev(self, state: TradingState, vfe_mid: float, scale: float, defense: bool):
        if defense:
            z_entry = self.B_VEV_Z_ENTRY
            base_map = self.B_VEV_TAKER
        else:
            z_entry = self.A_VEV_Z_ENTRY
            base_map = self.A_VEV_TAKER

        cands = []
        for k in VEV_STRIKES:
            sym = f"VEV_{k}"
            d = state.order_depths.get(sym)
            if d is None:
                continue
            bb, ba = self._top(d)
            if bb is None or ba is None:
                continue
            if ba - bb > self.VEV_SPREAD_MAX[k]:
                continue
            mid = (bb + ba) / 2.0
            intr = max(vfe_mid - k, 0.0)
            obs = mid - intr
            key = str(k)
            prev = float(self.h["prem"][key])
            prem = (1 - self.PREM_ALPHA) * prev + self.PREM_ALPHA * obs
            lo, hi = PREM_BOUNDS[k]
            prem = max(lo, min(hi, prem))
            self.h["prem"][key] = prem
            dev = obs - prem
            pv = float(self.h["prem_var"][key])
            nv = (1 - self.PREM_VAR_ALPHA) * pv + self.PREM_VAR_ALPHA * (dev * dev)
            nv = max(1.0, nv)
            self.h["prem_var"][key] = nv
            z = dev / (nv ** 0.5)
            fair = intr + prem
            cands.append((abs(z), z, k, sym, bb, ba, fair))

        if not cands:
            return []
        cands.sort(reverse=True, key=lambda x: x[0])
        _, z, k, sym, bb, ba, fair = cands[0]
        if abs(z) < z_entry:
            return []
        d = state.order_depths[sym]
        pos = int(state.position.get(sym, 0))
        lim = STRIKE_CAP[k]
        taker = max(1, int(base_map[k] * scale))
        out = []
        if z <= -z_entry and ba <= fair and pos < lim:
            q = min(taker, lim - pos, -d.sell_orders.get(ba, 0))
            if q > 0:
                out.append(Order(sym, ba, q))
        elif z >= z_entry and bb >= fair and pos > -lim:
            q = min(taker, lim + pos, d.buy_orders.get(bb, 0))
            if q > 0:
                out.append(Order(sym, bb, -q))
        return out

    def run(self, state: TradingState):
        self._load(state)
        res: Dict[str, List[Order]] = {}

        vfe_mid = None
        vd = state.order_depths.get(VFE)
        if vd is not None:
            bb, ba = self._top(vd)
            if bb is not None and ba is not None:
                vfe_mid = (bb + ba) / 2.0
        h_spread = None
        hd = state.order_depths.get(HYDRO)
        if hd is not None:
            bb, ba = self._top(hd)
            if bb is not None and ba is not None:
                h_spread = ba - bb

        defense = self._update_policy(vfe_mid, h_spread)
        scale = self._scale(state)

        for o in self._hydro(state, scale, defense):
            res.setdefault(o.symbol, []).append(o)
        vfe_orders, vfe_mid2 = self._vfe(state, scale, defense)
        for o in vfe_orders:
            res.setdefault(o.symbol, []).append(o)
        vref = vfe_mid2 if vfe_mid2 is not None else vfe_mid
        if vref is not None:
            for o in self._vev(state, vref, scale, defense):
                res.setdefault(o.symbol, []).append(o)

        return res, 0, self._save()

