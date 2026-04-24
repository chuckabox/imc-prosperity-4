"""trader_ken_v22.py — v18 with floor-protection risk governor.

Built on v18's alpha stack, with one major addition:
- Portfolio risk governor that throttles sizing and de-leverages inventory
  when exposure gets too high or when price moves against current exposure.

Goal: keep v18 upside but reduce deep intraday floor hits.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]

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

# Coarse empirical deltas for exposure control
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
    HP_MAKER_EDGE = 1.5
    HP_TAKER_MAX = 20

    # VFE
    VFE_LIMIT = 80
    VFE_EWMA_ALPHA = 0.20
    VFE_MAKER_EDGE = 2.5
    VFE_TAKER_EDGE = 4.0
    VFE_TAKER_MAX = 15

    # VEV
    PREM_ALPHA = 0.05
    VEV_MAKER_EDGE = 2.0

    # Risk governor
    RISK_NET_DELTA_TRIGGER = 50.0
    RISK_HP_POS_TRIGGER = 58
    RISK_ADVERSE_MOVE = 2.5
    RISK_MIN_SCALE = 0.4
    RISK_UNWIND_MAX = 6

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
        self.history.setdefault("last_hp_mid", None)
        self.history.setdefault("last_vfe_mid", None)
        for k in VEV_STRIKES:
            self.history["prem"].setdefault(str(k), PREM_INIT[k])

    def _save_state(self) -> str:
        return json.dumps(self.history)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    def _guarded_maker(
        self,
        symbol: str,
        depth: OrderDepth,
        pos: int,
        fair: float,
        limit: int,
        edge: float,
        max_qty: Optional[int] = None,
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

        room_long = limit - pos
        room_short = limit + pos
        if max_qty is not None:
            room_long = min(room_long, max_qty)
            room_short = min(room_short, max_qty)

        if room_long > 0:
            orders.append(Order(symbol, qbid, room_long))
        if room_short > 0:
            orders.append(Order(symbol, qask, -room_short))
        return orders

    def _portfolio_net_delta(self, state: TradingState) -> float:
        net = float(state.position.get(VFE, 0))
        for k in VEV_STRIKES:
            net += state.position.get(f"VEV_{k}", 0) * VEV_DELTA_APPROX[k]
        return net

    def _risk_state(
        self, state: TradingState, hp_mid: Optional[float], vfe_mid: Optional[float]
    ) -> Tuple[float, bool]:
        hp_pos = abs(state.position.get(HYDROGEL, 0))
        net_delta = abs(self._portfolio_net_delta(state))
        score = 0.0

        score += 0.45 * min(1.0, hp_pos / float(self.HP_LIMIT))
        score += 0.55 * min(1.0, net_delta / float(self.VFE_LIMIT))

        last_vfe = self.history.get("last_vfe_mid")
        if vfe_mid is not None and last_vfe is not None:
            dv = float(vfe_mid) - float(last_vfe)
            signed = self._portfolio_net_delta(state)
            # If move is against net exposure, raise risk score.
            if (signed > 0 and dv < -self.RISK_ADVERSE_MOVE) or (
                signed < 0 and dv > self.RISK_ADVERSE_MOVE
            ):
                score += 0.25

        risk_off = hp_pos >= self.RISK_HP_POS_TRIGGER or net_delta >= self.RISK_NET_DELTA_TRIGGER or score >= 0.95
        scale = max(self.RISK_MIN_SCALE, 1.0 - min(1.0, score))
        return scale, risk_off

    def _hydrogel_logic(self, state: TradingState, scale: float, risk_off: bool) -> Tuple[List[Order], Optional[float]]:
        depth = state.order_depths.get(HYDROGEL)
        if depth is None:
            return [], None
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return [], None

        mid = (bb + ba) / 2.0
        prev = self.history.get("hp_ewma")
        ewma = mid if prev is None else (1 - self.HP_EWMA_ALPHA) * prev + self.HP_EWMA_ALPHA * mid
        self.history["hp_ewma"] = ewma
        fair = 0.6 * ewma + 0.4 * self.HP_ANCHOR

        pos = state.position.get(HYDROGEL, 0)
        lim = self.HP_LIMIT
        orders: List[Order] = []
        taker_max = max(4, int(self.HP_TAKER_MAX * scale))
        maker_max = max(6, int(28 * scale))
        taker_enabled = not risk_off

        if taker_enabled and ba <= fair - self.HP_TAKER_EDGE and pos < lim:
            sz = min(taker_max, lim - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(HYDROGEL, ba, sz))
                pos += sz
        if taker_enabled and bb >= fair + self.HP_TAKER_EDGE and pos > -lim:
            sz = min(taker_max, lim + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(HYDROGEL, bb, -sz))
                pos -= sz

        maker_edge = self.HP_MAKER_EDGE + (1.0 if risk_off else 0.0)
        orders.extend(self._guarded_maker(HYDROGEL, depth, pos, fair, lim, maker_edge, max_qty=maker_max))
        return orders, mid

    def _vfe_logic(self, state: TradingState, scale: float, risk_off: bool) -> Tuple[List[Order], Optional[float]]:
        depth = state.order_depths.get(VFE)
        if depth is None:
            return [], None
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return [], None

        mid = (bb + ba) / 2.0
        prev = self.history.get("vfe_ewma")
        ewma = mid if prev is None else (1 - self.VFE_EWMA_ALPHA) * prev + self.VFE_EWMA_ALPHA * mid
        self.history["vfe_ewma"] = ewma
        fair = ewma

        pos = state.position.get(VFE, 0)
        lim = self.VFE_LIMIT
        orders: List[Order] = []

        taker_max = max(3, int(self.VFE_TAKER_MAX * scale))
        maker_max = max(4, int(22 * scale))

        # In risk-off, disable aggressive taker to reduce churn.
        if (not risk_off) and ba <= fair - self.VFE_TAKER_EDGE and pos < lim:
            sz = min(taker_max, lim - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(VFE, ba, sz))
                pos += sz
        if (not risk_off) and bb >= fair + self.VFE_TAKER_EDGE and pos > -lim:
            sz = min(taker_max, lim + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(VFE, bb, -sz))
                pos -= sz

        maker_edge = self.VFE_MAKER_EDGE + (1.0 if risk_off else 0.0)
        orders.extend(self._guarded_maker(VFE, depth, pos, fair, lim, maker_edge, max_qty=maker_max))
        return orders, mid

    def _vev_logic(self, state: TradingState, vfe_mid: float, scale: float, risk_off: bool) -> List[Order]:
        orders: List[Order] = []
        maker_max = max(2, int(10 * scale))

        for strike in VEV_STRIKES:
            sym = f"VEV_{strike}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            bb, ba = self._top(depth)
            if bb is None or ba is None:
                continue

            obs_mid = (bb + ba) / 2.0
            intrinsic = max(vfe_mid - strike, 0.0)
            obs_prem = obs_mid - intrinsic
            prem_key = str(strike)
            prev_prem = float(self.history["prem"][prem_key])
            prem = (1 - self.PREM_ALPHA) * prev_prem + self.PREM_ALPHA * obs_prem
            lo, hi = PREM_BOUNDS[strike]
            prem = max(lo, min(hi, prem))
            self.history["prem"][prem_key] = prem

            fair = intrinsic + prem
            pos = state.position.get(sym, 0)
            lim_base = STRIKE_CAP[strike]
            lim = max(8, int(lim_base * (0.75 if risk_off else 1.0)))

            edge = self.VEV_MAKER_EDGE + (0.8 if risk_off else 0.0)
            orders.extend(
                self._guarded_maker(sym, depth, pos, fair, lim, edge, max_qty=maker_max)
            )

        return orders

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        # Mids for risk model
        hp_mid = None
        vfe_mid_for_risk = None
        if HYDROGEL in state.order_depths:
            bb, ba = self._top(state.order_depths[HYDROGEL])
            if bb is not None and ba is not None:
                hp_mid = (bb + ba) / 2.0
        if VFE in state.order_depths:
            bb, ba = self._top(state.order_depths[VFE])
            if bb is not None and ba is not None:
                vfe_mid_for_risk = (bb + ba) / 2.0

        scale, risk_off = self._risk_state(state, hp_mid, vfe_mid_for_risk)

        if self.ENABLE_HYDROGEL:
            hp_orders, hp_mid_exec = self._hydrogel_logic(state, scale, risk_off)
            for o in hp_orders:
                result.setdefault(o.symbol, []).append(o)
            if hp_mid_exec is not None:
                self.history["last_hp_mid"] = hp_mid_exec

        vfe_orders, vfe_mid = self._vfe_logic(state, scale, risk_off)
        if self.ENABLE_VFE:
            for o in vfe_orders:
                result.setdefault(o.symbol, []).append(o)
        if vfe_mid is not None:
            self.history["last_vfe_mid"] = vfe_mid

        if self.ENABLE_VEV and vfe_mid is not None:
            for o in self._vev_logic(state, vfe_mid, scale, risk_off):
                result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save_state()

