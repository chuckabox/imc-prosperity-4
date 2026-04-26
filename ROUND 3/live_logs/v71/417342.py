"""trader_ken_v71_crossstrike_blend.py

Cross-strike relative-value variant.
- Keeps v41 hydrogel/vfe backbone.
- Options alpha uses smile dislocations across multiple strikes.
- Prefers paired trades (buy cheap strike + sell rich strike) to reduce delta bleed.
- Adds light microprice/imbalance overlays for extra edge.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100, 5200, 5300, 5400]

PREM_INIT: Dict[int, float] = {5000: 5.81, 5100: 19.09, 5200: 48.85, 5300: 47.0, 5400: 18.0}

PREM_BOUNDS: Dict[int, Tuple[float, float]] = {
    5000: (2.0, 14.0),
    5100: (10.0, 30.0),
    5200: (28.0, 76.0),
    5300: (20.0, 72.0),
    5400: (7.0, 36.0),
}

STRIKE_CAP: Dict[int, int] = {5000: 24, 5100: 28, 5200: 34, 5300: 34, 5400: 24}

VEV_DELTA_APPROX: Dict[int, float] = {5000: 0.82, 5100: 0.70, 5200: 0.57, 5300: 0.44, 5400: 0.31}


class Trader:
    ENABLE_HYDROGEL = True
    ENABLE_VFE = True
    ENABLE_VEV = True

    # HYDROGEL (near-v30)
    HP_LIMIT = 80
    HP_ANCHOR = 9993.0
    HP_EWMA_ALPHA = 0.20
    HP_TAKER_EDGE = 2.5
    HP_MAKER_EDGE = 2.3
    HP_TAKER_MAX = 20
    HP_OBI_ENTRY = 0.40
    HP_OBI_TAKER_MAX = 4

    # VFE
    VFE_LIMIT = 80
    VFE_EWMA_ALPHA = 0.20
    VFE_MAKER_EDGE = 2.2
    VFE_TAKER_EDGE = 4.5
    VFE_TAKER_MAX = 12
    VFE_MICRO_TILT = 0.12

    # VEV sparse taker
    PREM_ALPHA = 0.06
    PREM_VAR_ALPHA = 0.08
    VEV_Z_ENTRY = 1.45
    VEV_SPREAD_MAX_BY_STRIKE: Dict[int, int] = {5000: 8, 5100: 8, 5200: 8, 5300: 8, 5400: 8}
    VEV_TAKER_MAX_BY_STRIKE: Dict[int, int] = {5000: 4, 5100: 5, 5200: 7, 5300: 7, 5400: 4}
    VEV_REL_Z_ENTRY = 1.00

    # Risk governor
    RISK_NET_DELTA_TRIGGER = 55.0
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
        fair = 0.6 * ewma + 0.4 * self.HP_ANCHOR

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
        maker_max = max(6, int(28 * local_scale))
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

        # Light OBI burst signal (rare-only).
        bvol = float(depth.buy_orders.get(bb, 0))
        avol = float(-depth.sell_orders.get(ba, 0))
        if (not risk_off) and (bvol + avol) > 0:
            obi = (bvol - avol) / (bvol + avol)
            obi_mx = max(1, int(self.HP_OBI_TAKER_MAX * local_scale))
            if obi >= self.HP_OBI_ENTRY and pos < lim:
                sz = min(obi_mx, lim - pos, -depth.sell_orders[ba])
                if sz > 0:
                    orders.append(Order(HYDROGEL, ba, sz))
                    pos += sz
            elif obi <= -self.HP_OBI_ENTRY and pos > -lim:
                sz = min(obi_mx, lim + pos, depth.buy_orders[bb])
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
        bid_vol = float(depth.buy_orders.get(bb, 0))
        ask_vol = float(-depth.sell_orders.get(ba, 0))
        if (bid_vol + ask_vol) > 0:
            micro = (bb * ask_vol + ba * bid_vol) / (bid_vol + ask_vol)
        else:
            micro = mid
        fair = (1.0 - self.VFE_MICRO_TILT) * ewma + self.VFE_MICRO_TILT * micro

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

        taker_max = max(3, int(self.VFE_TAKER_MAX * local_scale))
        maker_max = max(4, int(18 * local_scale))

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
        if risk_off:
            return []
        cands: List[Tuple[float, int, int, int, float, float]] = []
        for strike in VEV_STRIKES:
            sym = f"VEV_{strike}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            bb, ba = self._top(depth)
            if bb is None or ba is None:
                continue
            spread = ba - bb
            if spread <= 0 or spread > self.VEV_SPREAD_MAX_BY_STRIKE[strike]:
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
            # score: strong z and near-ATM preference.
            mny_penalty = abs(strike - vfe_mid) / 200.0
            cands.append((abs(z) - 0.08 * mny_penalty, strike, bb, ba, z, fair))

        if not cands:
            return []

        # Build sorted by signed z for relative-value pairing.
        raw = []
        for _, strike, bb, ba, z, fair in cands:
            raw.append((strike, bb, ba, z, fair))

        rich = [x for x in raw if x[3] >= self.VEV_REL_Z_ENTRY]   # overpriced -> sell
        cheap = [x for x in raw if x[3] <= -self.VEV_REL_Z_ENTRY]  # underpriced -> buy
        rich.sort(key=lambda x: x[3], reverse=True)
        cheap.sort(key=lambda x: x[3])

        orders: List[Order] = []
        # Prefer cross-strike pair first.
        if rich and cheap:
            sell_k, sell_bb, _, _, _ = rich[0]
            buy_k, _, buy_ba, _, _ = cheap[0]
            if sell_k != buy_k:
                sell_sym = f"VEV_{sell_k}"
                buy_sym = f"VEV_{buy_k}"
                sell_d = state.order_depths[sell_sym]
                buy_d = state.order_depths[buy_sym]
                sell_pos = state.position.get(sell_sym, 0)
                buy_pos = state.position.get(buy_sym, 0)
                sell_lim = STRIKE_CAP[sell_k]
                buy_lim = STRIKE_CAP[buy_k]
                sell_mx = max(1, int(self.VEV_TAKER_MAX_BY_STRIKE[sell_k] * scale))
                buy_mx = max(1, int(self.VEV_TAKER_MAX_BY_STRIKE[buy_k] * scale))
                q_sell = min(sell_mx, sell_lim + sell_pos, sell_d.buy_orders.get(sell_bb, 0))
                q_buy = min(buy_mx, buy_lim - buy_pos, -buy_d.sell_orders.get(buy_ba, 0))
                q = min(q_sell, q_buy)
                if q > 0:
                    orders.append(Order(sell_sym, sell_bb, -q))
                    orders.append(Order(buy_sym, buy_ba, q))
                    return orders

        # Fallback single-leg strongest absolute signal.
        cands.sort(reverse=True, key=lambda x: x[0])
        _, strike, bb, ba, z, fair = cands[0]
        if abs(z) < self.VEV_Z_ENTRY:
            return []
        sym = f"VEV_{strike}"
        depth = state.order_depths[sym]
        pos = state.position.get(sym, 0)
        lim = STRIKE_CAP[strike]
        taker_max = max(1, int(self.VEV_TAKER_MAX_BY_STRIKE[strike] * scale))
        if z <= -self.VEV_Z_ENTRY and ba <= fair and pos < lim:
            sz = min(taker_max, lim - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(sym, ba, sz))
        elif z >= self.VEV_Z_ENTRY and bb >= fair and pos > -lim:
            sz = min(taker_max, lim + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(sym, bb, -sz))
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