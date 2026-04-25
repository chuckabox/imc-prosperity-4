"""trader_ken_v60_meta_policy_smile.py

Meta-policy + volatility-smile residual options engine.
- Keeps v58-style alpha/defense switching for execution-cost control.
- Replaces simple per-strike premium reversion with smile residual trading:
  fit premium ~ a + b*x + c*x^2 (x = strike - spot), then trade residual z-score.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDRO = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_ALL = [5000, 5100, 5200]
VEV_TRADE = [5000, 5100]

STRIKE_CAP: Dict[int, int] = {5000: 38, 5100: 30, 5200: 24}
VEV_DELTA_APPROX: Dict[int, float] = {5000: 0.82, 5100: 0.70, 5200: 0.56}


class Trader:
    HP_LIMIT = 80
    VFE_LIMIT = 80
    HP_ANCHOR = 9993.0
    HP_EWMA_ALPHA = 0.20
    VFE_EWMA_ALPHA = 0.20
    RES_VAR_ALPHA = 0.10

    # Policy A (alpha)
    A_HP_MAKER_EDGE = 2.2
    A_HP_TAKER_EDGE = 2.5
    A_HP_TAKER_MAX = 20
    A_VFE_MAKER_EDGE = 2.2
    A_VFE_TAKER_EDGE = 4.5
    A_VFE_TAKER_MAX = 12
    A_VEV_Z_ENTRY = 1.50
    A_VEV_TAKER = {5000: 8, 5100: 6}

    # Policy B (defense)
    B_HP_MAKER_EDGE = 2.8
    B_HP_TAKER_EDGE = 4.2
    B_HP_TAKER_MAX = 8
    B_VFE_MAKER_EDGE = 2.8
    B_VFE_TAKER_EDGE = 5.6
    B_VFE_TAKER_MAX = 7
    B_VEV_Z_ENTRY = 2.00
    B_VEV_TAKER = {5000: 4, 5100: 2}

    VEV_SPREAD_MAX = {5000: 8, 5100: 6, 5200: 8}
    NET_DELTA_SOFT = 50.0
    NET_DELTA_HARD = 65.0
    VOL_ALPHA = 0.10
    COST_ON = 1.35
    COST_OFF = 1.00

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
        self.h.setdefault("last_vfe_mid", None)
        self.h.setdefault("cost_ewma", 0.0)
        self.h.setdefault("defense_on", False)
        self.h.setdefault("res_var", {})
        for k in VEV_ALL:
            self.h["res_var"].setdefault(str(k), 9.0)

    def _save(self):
        return json.dumps(self.h)

    @staticmethod
    def _top(d: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(d.buy_orders.keys()) if d.buy_orders else None
        ba = min(d.sell_orders.keys()) if d.sell_orders else None
        return bb, ba

    def _net_delta(self, state: TradingState) -> float:
        d = float(state.position.get(VFE, 0))
        for k in VEV_TRADE:
            d += state.position.get(f"VEV_{k}", 0) * VEV_DELTA_APPROX[k]
        return d

    def _scale(self, state: TradingState) -> float:
        nd = abs(self._net_delta(state))
        if nd >= self.NET_DELTA_HARD:
            return 0.35
        if nd >= self.NET_DELTA_SOFT:
            return 0.65
        return 1.0

    def _update_policy(self, vfe_mid: Optional[float], hydro_spread: Optional[int]):
        jump = 0.0
        if vfe_mid is not None and self.h.get("last_vfe_mid") is not None:
            jump = abs(float(vfe_mid) - float(self.h["last_vfe_mid"]))
        if vfe_mid is not None:
            self.h["last_vfe_mid"] = vfe_mid
        hs = float(hydro_spread if hydro_spread is not None else 12.0)
        cost_proxy = 0.55 * jump + 0.45 * max(0.0, hs - 10.0)
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
        fair = 0.6 * ew + 0.4 * self.HP_ANCHOR
        pos = int(state.position.get(HYDRO, 0))
        lim = self.HP_LIMIT
        if defense:
            maker_edge, taker_edge, taker_base = self.B_HP_MAKER_EDGE, self.B_HP_TAKER_EDGE, self.B_HP_TAKER_MAX
        else:
            maker_edge, taker_edge, taker_base = self.A_HP_MAKER_EDGE, self.A_HP_TAKER_EDGE, self.A_HP_TAKER_MAX
        taker = max(1, int(taker_base * scale))
        maker = max(4, int(28 * scale))
        out: List[Order] = []
        if ba - bb <= 13:
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
        maker = max(3, int(16 * scale))
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

    @staticmethod
    def _solve3(xs: List[float], ys: List[float]) -> Optional[Tuple[float, float, float]]:
        if len(xs) != 3 or len(ys) != 3:
            return None
        x1, x2, x3 = xs
        y1, y2, y3 = ys
        a11, a12, a13 = 1.0, x1, x1 * x1
        a21, a22, a23 = 1.0, x2, x2 * x2
        a31, a32, a33 = 1.0, x3, x3 * x3
        det = (
            a11 * (a22 * a33 - a23 * a32)
            - a12 * (a21 * a33 - a23 * a31)
            + a13 * (a21 * a32 - a22 * a31)
        )
        if abs(det) < 1e-9:
            return None
        det_a = (
            y1 * (a22 * a33 - a23 * a32)
            - a12 * (y2 * a33 - a23 * y3)
            + a13 * (y2 * a32 - a22 * y3)
        )
        det_b = (
            a11 * (y2 * a33 - a23 * y3)
            - y1 * (a21 * a33 - a23 * a31)
            + a13 * (a21 * y3 - y2 * a31)
        )
        det_c = (
            a11 * (a22 * y3 - y2 * a32)
            - a12 * (a21 * y3 - y2 * a31)
            + y1 * (a21 * a32 - a22 * a31)
        )
        return det_a / det, det_b / det, det_c / det

    def _vev_smile(self, state: TradingState, vfe_mid: float, scale: float, defense: bool):
        if defense:
            z_entry = self.B_VEV_Z_ENTRY
            base_map = self.B_VEV_TAKER
        else:
            z_entry = self.A_VEV_Z_ENTRY
            base_map = self.A_VEV_TAKER

        points = []
        books: Dict[int, Tuple[OrderDepth, int, int, float]] = {}
        for k in VEV_ALL:
            sym = f"VEV_{k}"
            d = state.order_depths.get(sym)
            if d is None:
                continue
            bb, ba = self._top(d)
            if bb is None or ba is None:
                continue
            spr = ba - bb
            if spr > self.VEV_SPREAD_MAX[k]:
                continue
            mid = (bb + ba) / 2.0
            intr = max(vfe_mid - k, 0.0)
            prem = mid - intr
            x = float(k - vfe_mid)
            points.append((k, x, prem))
            books[k] = (d, bb, ba, mid)

        if len(points) < 2:
            return []

        # Prefer quadratic fit when 3 points are available.
        coeff = None
        if len(points) >= 3:
            pts = sorted(points, key=lambda t: abs(t[1]))[:3]
            coeff = self._solve3([p[1] for p in pts], [p[2] for p in pts])

        # Fallback linear premium(x) = a + b*x from first 2 points.
        if coeff is None:
            p1, p2 = points[0], points[1]
            x1, y1 = p1[1], p1[2]
            x2, y2 = p2[1], p2[2]
            if abs(x2 - x1) < 1e-9:
                return []
            b = (y2 - y1) / (x2 - x1)
            a = y1 - b * x1

            def fit(x: float) -> float:
                return a + b * x
        else:
            a, b, c = coeff

            def fit(x: float) -> float:
                return a + b * x + c * x * x

        cands = []
        for k in VEV_TRADE:
            if k not in books:
                continue
            d, bb, ba, mid = books[k]
            x = float(k - vfe_mid)
            intr = max(vfe_mid - k, 0.0)
            obs_prem = mid - intr
            model_prem = fit(x)
            fair = intr + model_prem
            resid = obs_prem - model_prem
            key = str(k)
            pv = float(self.h["res_var"][key])
            nv = (1 - self.RES_VAR_ALPHA) * pv + self.RES_VAR_ALPHA * (resid * resid)
            nv = max(1.0, nv)
            self.h["res_var"][key] = nv
            z = resid / (nv ** 0.5)
            cands.append((abs(z), z, k, d, bb, ba, fair))

        if not cands:
            return []
        cands.sort(reverse=True, key=lambda x: x[0])
        _, z, k, d, bb, ba, fair = cands[0]
        if abs(z) < z_entry:
            return []
        pos = int(state.position.get(f"VEV_{k}", 0))
        lim = STRIKE_CAP[k]
        taker = max(1, int(base_map[k] * scale))
        out = []
        if z <= -z_entry and ba <= fair and pos < lim:
            q = min(taker, lim - pos, -d.sell_orders.get(ba, 0))
            if q > 0:
                out.append(Order(f"VEV_{k}", ba, q))
        elif z >= z_entry and bb >= fair and pos > -lim:
            q = min(taker, lim + pos, d.buy_orders.get(bb, 0))
            if q > 0:
                out.append(Order(f"VEV_{k}", bb, -q))
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
            for o in self._vev_smile(state, vref, scale, defense):
                res.setdefault(o.symbol, []).append(o)

        return res, 0, self._save()

