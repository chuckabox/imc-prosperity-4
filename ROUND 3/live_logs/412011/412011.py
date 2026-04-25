"""trader_ken_v33.py

Stable-first Round 3 profile:
- Hydrogel-focused market making (primary PnL engine)
- Lighter VFE module (secondary / hedge support)
- Selective VEV exposure only on stronger strikes with spread-aware guards

Single-file submission, no local imports beyond datamodel.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"

# Concentrate risk on higher-quality strikes instead of quoting the whole chain.
VEV_STRIKES = [5000, 5100, 5200]

PREM_INIT: Dict[int, float] = {
    5000: 5.8,
    5100: 19.1,
    5200: 48.8,
}

PREM_BOUNDS: Dict[int, Tuple[float, float]] = {
    5000: (2.0, 14.0),
    5100: (10.0, 30.0),
    5200: (30.0, 72.0),
}

STRIKE_CAP: Dict[int, int] = {
    5000: 38,
    5100: 26,
    5200: 16,
}

VEV_DELTA_APPROX: Dict[int, float] = {
    5000: 0.82,
    5100: 0.70,
    5200: 0.57,
}


class Trader:
    ENABLE_HYDROGEL = True
    ENABLE_VFE = True
    ENABLE_VEV = True

    # HYDROGEL: primary stable module
    HP_LIMIT = 80
    HP_ANCHOR = 9995.0
    HP_EWMA_ALPHA = 0.22
    HP_TAKER_EDGE = 2.0
    HP_MAKER_EDGE = 2.0
    HP_TAKER_MAX = 22
    HP_MAKER_MAX = 36

    # VFE: lighter supporting module
    VFE_LIMIT = 60
    VFE_EWMA_ALPHA = 0.18
    VFE_MAKER_EDGE = 2.5
    VFE_TAKER_EDGE = 5.0
    VFE_TAKER_MAX = 10
    VFE_MAKER_MAX = 14

    # VEV
    PREM_ALPHA = 0.06
    PREM_VAR_ALPHA = 0.08
    VEV_TAKER_Z = 1.30
    VEV_MAKER_EDGE_BY_STRIKE: Dict[int, float] = {5000: 1.2, 5100: 1.6, 5200: 2.0}
    VEV_MAX_SPREAD_BY_STRIKE: Dict[int, int] = {5000: 9, 5100: 7, 5200: 5}
    VEV_TAKER_MAX_BY_STRIKE: Dict[int, int] = {5000: 8, 5100: 5, 5200: 3}
    VEV_MAKER_MAX_BY_STRIKE: Dict[int, int] = {5000: 14, 5100: 8, 5200: 5}

    # Risk governor
    RISK_NET_DELTA_TRIGGER = 45.0
    RISK_HP_POS_TRIGGER = 66
    RISK_ADVERSE_MOVE = 2.5
    RISK_MIN_SCALE = 0.35

    # Soft safety
    OPEN_PHASE_TS = 120_000
    HP_SPEED_TRIGGER = 18
    VFE_SPEED_TRIGGER = 16
    SPEED_COOLDOWN_TS = 40_000
    OPEN_SCALE_MULT = 0.80
    SPEED_SCALE_MULT = 0.70

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
        self.history.setdefault("prem_var", {})
        self.history.setdefault("last_hp_mid", None)
        self.history.setdefault("last_vfe_mid", None)
        self.history.setdefault("last_hp_pos", 0)
        self.history.setdefault("last_vfe_pos", 0)
        self.history.setdefault("hp_speed_cooldown_until", -1)
        self.history.setdefault("vfe_speed_cooldown_until", -1)
        for k in VEV_STRIKES:
            self.history["prem"].setdefault(str(k), PREM_INIT[k])
            self.history["prem_var"].setdefault(str(k), 9.0)

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

        orders: List[Order] = []
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
            if (signed > 0 and dv < -self.RISK_ADVERSE_MOVE) or (
                signed < 0 and dv > self.RISK_ADVERSE_MOVE
            ):
                score += 0.25

        risk_off = (
            hp_pos >= self.RISK_HP_POS_TRIGGER
            or net_delta >= self.RISK_NET_DELTA_TRIGGER
            or score >= 0.95
        )
        scale = max(self.RISK_MIN_SCALE, 1.0 - min(1.0, score))
        return scale, risk_off

    def _in_open_phase(self, state: TradingState) -> bool:
        return int(state.timestamp) <= self.OPEN_PHASE_TS

    def _speed_limited(self, state: TradingState, symbol: str, trigger: int, cd_key: str, last_pos_key: str) -> bool:
        now = int(state.timestamp)
        pos = int(state.position.get(symbol, 0))
        last_pos = int(self.history.get(last_pos_key, 0))
        if abs(pos - last_pos) >= trigger:
            self.history[cd_key] = now + self.SPEED_COOLDOWN_TS
        self.history[last_pos_key] = pos
        return now < int(self.history.get(cd_key, -1))

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
        fair = 0.70 * ewma + 0.30 * self.HP_ANCHOR

        speed_limited = self._speed_limited(
            state, HYDROGEL, self.HP_SPEED_TRIGGER, "hp_speed_cooldown_until", "last_hp_pos"
        )
        local_scale = scale
        if self._in_open_phase(state):
            local_scale *= self.OPEN_SCALE_MULT
        if speed_limited:
            local_scale *= self.SPEED_SCALE_MULT

        pos = state.position.get(HYDROGEL, 0)
        lim = self.HP_LIMIT
        orders: List[Order] = []
        taker_max = max(4, int(self.HP_TAKER_MAX * local_scale))
        maker_max = max(8, int(self.HP_MAKER_MAX * local_scale))
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

        maker_edge = self.HP_MAKER_EDGE + (0.8 if risk_off else 0.0)
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

        speed_limited = self._speed_limited(
            state, VFE, self.VFE_SPEED_TRIGGER, "vfe_speed_cooldown_until", "last_vfe_pos"
        )
        local_scale = scale
        if self._in_open_phase(state):
            local_scale *= self.OPEN_SCALE_MULT
        if speed_limited:
            local_scale *= self.SPEED_SCALE_MULT

        pos = state.position.get(VFE, 0)
        lim = self.VFE_LIMIT
        orders: List[Order] = []
        taker_max = max(2, int(self.VFE_TAKER_MAX * local_scale))
        maker_max = max(3, int(self.VFE_MAKER_MAX * local_scale))

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

        maker_edge = self.VFE_MAKER_EDGE + (0.8 if risk_off else 0.0)
        orders.extend(self._guarded_maker(VFE, depth, pos, fair, lim, maker_edge, max_qty=maker_max))
        return orders, mid

    def _vev_logic(self, state: TradingState, vfe_mid: float, scale: float, risk_off: bool) -> List[Order]:
        orders: List[Order] = []

        for strike in VEV_STRIKES:
            sym = f"VEV_{strike}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            bb, ba = self._top(depth)
            if bb is None or ba is None:
                continue

            spread = int(ba - bb)
            if spread <= 0:
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

            dev = obs_prem - prem
            prev_var = float(self.history["prem_var"][prem_key])
            var = (1 - self.PREM_VAR_ALPHA) * prev_var + self.PREM_VAR_ALPHA * (dev * dev)
            var = max(1.0, var)
            self.history["prem_var"][prem_key] = var
            sigma = var ** 0.5
            z = dev / sigma

            fair = intrinsic + prem
            pos = state.position.get(sym, 0)
            lim_base = STRIKE_CAP[strike]
            lim = max(6, int(lim_base * (0.75 if risk_off else 1.0)))
            max_spread = self.VEV_MAX_SPREAD_BY_STRIKE[strike]

            # Taker only when dislocation is strong and spread is not too wide.
            if (not risk_off) and spread <= max_spread:
                taker_max = max(1, int(self.VEV_TAKER_MAX_BY_STRIKE[strike] * scale))
                if z <= -self.VEV_TAKER_Z and ba <= fair and pos < lim:
                    sz = min(taker_max, lim - pos, -depth.sell_orders[ba])
                    if sz > 0:
                        orders.append(Order(sym, ba, sz))
                        pos += sz
                if z >= self.VEV_TAKER_Z and bb >= fair and pos > -lim:
                    sz = min(taker_max, lim + pos, depth.buy_orders[bb])
                    if sz > 0:
                        orders.append(Order(sym, bb, -sz))
                        pos -= sz

            # Maker for carry, but only when quoting conditions are sane.
            if spread <= max_spread + 1:
                edge = self.VEV_MAKER_EDGE_BY_STRIKE[strike] + (0.7 if risk_off else 0.0)
                maker_max = max(1, int(self.VEV_MAKER_MAX_BY_STRIKE[strike] * scale))
                orders.extend(self._guarded_maker(sym, depth, pos, fair, lim, edge, max_qty=maker_max))

        return orders

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

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

        if self.ENABLE_VFE:
            vfe_orders, vfe_mid = self._vfe_logic(state, scale, risk_off)
            for o in vfe_orders:
                result.setdefault(o.symbol, []).append(o)
            if vfe_mid is not None:
                self.history["last_vfe_mid"] = vfe_mid
        else:
            vfe_mid = None

        if self.ENABLE_VEV and vfe_mid is not None:
            for o in self._vev_logic(state, vfe_mid, scale, risk_off):
                result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save_state()