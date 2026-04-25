"""trader_ken_v24.py — reliability + best-overall hybrid.

Design:
- Keep v22/v18-style upside in normal mode.
- Use v23-style trailing drawdown guard only when needed.
- Exit protection faster to avoid sacrificing too much edge.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]
TRACKED = [HYDROGEL, VFE, *VEV_SYMBOLS]

PREM_INIT: Dict[int, float] = {
    5000: 5.81,
    5100: 19.09,
    5200: 48.85,
    5300: 47.90,
    5400: 17.06,
    5500: 7.31,
}
PREM_BOUNDS: Dict[int, Tuple[float, float]] = {
    5000: (2.0, 14.0),
    5100: (10.0, 30.0),
    5200: (30.0, 72.0),
    5300: (30.0, 72.0),
    5400: (8.0, 30.0),
    5500: (3.0, 15.0),
}
STRIKE_CAP: Dict[int, int] = {
    5000: 32,
    5100: 44,
    5200: 48,
    5300: 44,
    5400: 36,
    5500: 28,
}
VEV_DELTA_APPROX: Dict[int, float] = {
    5000: 0.82,
    5100: 0.70,
    5200: 0.57,
    5300: 0.44,
    5400: 0.31,
    5500: 0.21,
}


class Trader:
    ENABLE_HYDROGEL = True
    ENABLE_VFE = True
    ENABLE_VEV = True

    # HYDROGEL
    HP_LIMIT = 80
    HP_ANCHOR = 9993.0
    HP_EWMA_ALPHA = 0.20
    HP_TAKER_EDGE = 2.0
    HP_MAKER_EDGE = 2.0
    HP_TAKER_MAX = 20

    # VFE
    VFE_LIMIT = 80
    VFE_EWMA_ALPHA = 0.20
    VFE_MAKER_EDGE = 2.0
    VFE_TAKER_EDGE = 4.0
    VFE_TAKER_MAX = 15

    # VEV
    PREM_ALPHA = 0.05
    VEV_MAKER_EDGE = 2.0

    # Base risk governor (looser than v23 in normal mode)
    RISK_NET_DELTA_TRIGGER = 62.0
    RISK_HP_POS_TRIGGER = 68
    RISK_ADVERSE_MOVE = 3.0
    RISK_MIN_SCALE = 0.45

    # Trailing DD guard (only meaningful giveback)
    DD_TRIGGER = 1450.0
    DD_RELEASE = 650.0
    DD_PROTECT_TICKS = 45

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
        self.history.setdefault("prem", {})
        self.history.setdefault("last_vfe_mid", None)
        self.history.setdefault("prev_mid", {})
        self.history.setdefault("prev_pos", {})
        self.history.setdefault("mtm_proxy", 0.0)
        self.history.setdefault("mtm_peak", 0.0)
        self.history.setdefault("protect_ticks_left", 0)
        for k in VEV_STRIKES:
            self.history["prem"].setdefault(str(k), PREM_INIT[k])

    def _save_state(self) -> str:
        return json.dumps(self.history)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    def _mid(self, state: TradingState, symbol: str) -> Optional[float]:
        d = state.order_depths.get(symbol)
        if d is None:
            return None
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0

    def _portfolio_net_delta(self, state: TradingState) -> float:
        net = float(state.position.get(VFE, 0))
        for k in VEV_STRIKES:
            net += state.position.get(f"VEV_{k}", 0) * VEV_DELTA_APPROX[k]
        return net

    def _update_drawdown_guard(self, state: TradingState) -> bool:
        prev_mid = self.history["prev_mid"]
        prev_pos = self.history["prev_pos"]
        step = 0.0
        for s in TRACKED:
            m = self._mid(state, s)
            pm = prev_mid.get(s)
            pp = float(prev_pos.get(s, 0))
            if m is not None and pm is not None:
                step += pp * (m - float(pm))
        mtm = float(self.history["mtm_proxy"]) + step
        peak = max(float(self.history["mtm_peak"]), mtm)
        dd = peak - mtm

        protect = int(self.history.get("protect_ticks_left", 0))
        if dd >= self.DD_TRIGGER:
            protect = self.DD_PROTECT_TICKS
        elif protect > 0:
            protect -= 1
            if dd <= self.DD_RELEASE:
                protect = 0

        self.history["mtm_proxy"] = mtm
        self.history["mtm_peak"] = peak
        self.history["protect_ticks_left"] = protect
        return protect > 0

    def _refresh_snapshot(self, state: TradingState) -> None:
        for s in TRACKED:
            m = self._mid(state, s)
            if m is not None:
                self.history["prev_mid"][s] = m
            self.history["prev_pos"][s] = int(state.position.get(s, 0))

    def _guarded_maker(
        self,
        symbol: str,
        depth: OrderDepth,
        pos: int,
        fair: float,
        limit: int,
        edge: float,
        max_qty: int,
        one_sided_flatten: bool,
    ) -> List[Order]:
        orders = []
        bb, ba = self._top(depth)
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

        room_long = min(limit - pos, max_qty)
        room_short = min(limit + pos, max_qty)
        if one_sided_flatten:
            if pos > 0:
                room_long = 0
            elif pos < 0:
                room_short = 0

        if room_long > 0:
            orders.append(Order(symbol, qbid, room_long))
        if room_short > 0:
            orders.append(Order(symbol, qask, -room_short))
        return orders

    def _risk_state(self, state: TradingState, vfe_mid: Optional[float], protect_mode: bool) -> Tuple[float, bool]:
        hp_pos = abs(state.position.get(HYDROGEL, 0))
        net_delta = abs(self._portfolio_net_delta(state))
        score = 0.0
        score += 0.45 * min(1.0, hp_pos / float(self.HP_LIMIT))
        score += 0.55 * min(1.0, net_delta / float(self.VFE_LIMIT))
        last_vfe = self.history.get("last_vfe_mid")
        if vfe_mid is not None and last_vfe is not None:
            dv = float(vfe_mid) - float(last_vfe)
            signed = self._portfolio_net_delta(state)
            if (signed > 0 and dv < -self.RISK_ADVERSE_MOVE) or (signed < 0 and dv > self.RISK_ADVERSE_MOVE):
                score += 0.20

        risk_off = protect_mode or hp_pos >= self.RISK_HP_POS_TRIGGER or net_delta >= self.RISK_NET_DELTA_TRIGGER or score >= 0.98
        scale = max(self.RISK_MIN_SCALE, 1.0 - min(1.0, score))
        if protect_mode:
            scale = min(scale, 0.55)
        return scale, risk_off

    def _hydrogel_logic(self, state: TradingState, scale: float, risk_off: bool, protect_mode: bool) -> List[Order]:
        d = state.order_depths.get(HYDROGEL)
        if d is None:
            return []
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0
        prev = self.history.get("hp_ewma")
        ewma = mid if prev is None else (1 - self.HP_EWMA_ALPHA) * prev + self.HP_EWMA_ALPHA * mid
        self.history["hp_ewma"] = ewma
        fair = 0.6 * ewma + 0.4 * self.HP_ANCHOR
        pos = state.position.get(HYDROGEL, 0)
        lim = self.HP_LIMIT
        taker_max = max(5, int(self.HP_TAKER_MAX * scale))
        maker_max = max(6, int(30 * scale))
        orders: List[Order] = []

        if (not risk_off) and ba <= fair - self.HP_TAKER_EDGE and pos < lim:
            sz = min(taker_max, lim - pos, -d.sell_orders[ba])
            if sz > 0:
                orders.append(Order(HYDROGEL, ba, sz))
                pos += sz
        if (not risk_off) and bb >= fair + self.HP_TAKER_EDGE and pos > -lim:
            sz = min(taker_max, lim + pos, d.buy_orders[bb])
            if sz > 0:
                orders.append(Order(HYDROGEL, bb, -sz))
                pos -= sz

        edge = self.HP_MAKER_EDGE + (1.0 if risk_off else 0.0)
        orders.extend(self._guarded_maker(HYDROGEL, d, pos, fair, lim, edge, maker_max, one_sided_flatten=protect_mode))
        return orders

    def _vfe_logic(self, state: TradingState, scale: float, risk_off: bool, protect_mode: bool) -> Tuple[List[Order], Optional[float]]:
        d = state.order_depths.get(VFE)
        if d is None:
            return [], None
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return [], None
        mid = (bb + ba) / 2.0
        prev = self.history.get("vfe_ewma")
        ewma = mid if prev is None else (1 - self.VFE_EWMA_ALPHA) * prev + self.VFE_EWMA_ALPHA * mid
        self.history["vfe_ewma"] = ewma
        fair = ewma
        pos = state.position.get(VFE, 0)
        lim = self.VFE_LIMIT
        taker_max = max(4, int(self.VFE_TAKER_MAX * scale))
        maker_max = max(5, int(24 * scale))
        orders: List[Order] = []

        if (not risk_off) and ba <= fair - self.VFE_TAKER_EDGE and pos < lim:
            sz = min(taker_max, lim - pos, -d.sell_orders[ba])
            if sz > 0:
                orders.append(Order(VFE, ba, sz))
                pos += sz
        if (not risk_off) and bb >= fair + self.VFE_TAKER_EDGE and pos > -lim:
            sz = min(taker_max, lim + pos, d.buy_orders[bb])
            if sz > 0:
                orders.append(Order(VFE, bb, -sz))
                pos -= sz

        edge = self.VFE_MAKER_EDGE + (0.8 if risk_off else 0.0)
        orders.extend(self._guarded_maker(VFE, d, pos, fair, lim, edge, maker_max, one_sided_flatten=protect_mode))
        return orders, mid

    def _vev_logic(self, state: TradingState, vfe_mid: float, scale: float, risk_off: bool, protect_mode: bool) -> List[Order]:
        out: List[Order] = []
        maker_max = max(2, int(11 * scale))
        for k in VEV_STRIKES:
            sym = f"VEV_{k}"
            d = state.order_depths.get(sym)
            if d is None:
                continue
            bb, ba = self._top(d)
            if bb is None or ba is None:
                continue
            obs_mid = (bb + ba) / 2.0
            intrinsic = max(vfe_mid - k, 0.0)
            obs_prem = obs_mid - intrinsic
            key = str(k)
            prev_prem = float(self.history["prem"][key])
            prem = (1 - self.PREM_ALPHA) * prev_prem + self.PREM_ALPHA * obs_prem
            lo, hi = PREM_BOUNDS[k]
            prem = max(lo, min(hi, prem))
            self.history["prem"][key] = prem
            fair = intrinsic + prem
            pos = state.position.get(sym, 0)
            lim = max(8, int(STRIKE_CAP[k] * (0.70 if protect_mode else (0.80 if risk_off else 1.0))))
            edge = self.VEV_MAKER_EDGE + (0.9 if risk_off else 0.0)
            out.extend(self._guarded_maker(sym, d, pos, fair, lim, edge, maker_max, one_sided_flatten=protect_mode))
        return out

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        protect_mode = self._update_drawdown_guard(state)
        vfe_mid_risk = self._mid(state, VFE)
        scale, risk_off = self._risk_state(state, vfe_mid_risk, protect_mode)

        if self.ENABLE_HYDROGEL:
            for o in self._hydrogel_logic(state, scale, risk_off, protect_mode):
                result.setdefault(o.symbol, []).append(o)

        vfe_mid = None
        if self.ENABLE_VFE:
            vfe_orders, vfe_mid = self._vfe_logic(state, scale, risk_off, protect_mode)
            for o in vfe_orders:
                result.setdefault(o.symbol, []).append(o)
        else:
            vfe_mid = self._mid(state, VFE)

        if self.ENABLE_VEV and vfe_mid is not None:
            for o in self._vev_logic(state, vfe_mid, scale, risk_off, protect_mode):
                result.setdefault(o.symbol, []).append(o)

        if vfe_mid is not None:
            self.history["last_vfe_mid"] = vfe_mid
        self._refresh_snapshot(state)
        return result, 0, self._save_state()