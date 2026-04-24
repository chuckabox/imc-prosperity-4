"""trader_ken_v27.py — reliability-first upgrade over v22.

Changes versus v22:
- Stronger risk governor using trend-stress memory (not just one-tick adverse move)
- Inventory-aware fair-value skew to reduce "stuck on one side" accumulation
- Active de-risking in risk-off mode with controlled inventory unwind
- Asymmetric VEV quoting: tighter when adding hedge-friendly inventory, wider otherwise

Primary objective: improve consistency and reduce floor hits, even if it sacrifices
some peak upside.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]

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
    HP_MAKER_EDGE = 2.0
    HP_TAKER_MAX = 20
    HP_INV_SKEW = 1.2

    # VFE
    VFE_LIMIT = 80
    VFE_EWMA_ALPHA = 0.20
    VFE_MAKER_EDGE = 2.0
    VFE_TAKER_EDGE = 4.0
    VFE_TAKER_MAX = 15
    VFE_INV_SKEW = 1.4

    # VEV
    PREM_ALPHA = 0.05
    VEV_MAKER_EDGE = 2.0
    VEV_TAKE_EDGE = 1.8
    VEV_BASE_QTY = 9

    # Risk governor
    RISK_NET_DELTA_TRIGGER = 55.0
    RISK_HP_POS_TRIGGER = 62
    RISK_MIN_SCALE = 0.35
    RISK_UNWIND_MAX = 6
    STRESS_DECAY = 0.85
    STRESS_ADVERSE_STEP = 1.0
    STRESS_THRESHOLD = 2.6
    VFE_RET_EMA_ALPHA = 0.25

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
        self.history.setdefault("risk_stress", 0.0)
        self.history.setdefault("vfe_ret_ema", 0.0)
        for k in VEV_STRIKES:
            self.history["prem"].setdefault(str(k), PREM_INIT[k])

    def _save_state(self) -> str:
        return json.dumps(self.history)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    @staticmethod
    def _clamp_int(x: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, x))

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

    def _inventory_skewed_fair(self, fair: float, pos: int, limit: int, skew_coeff: float) -> float:
        # Positive position should lower fair (bias to sell), negative should raise fair.
        frac = max(-1.0, min(1.0, pos / float(limit)))
        return fair - skew_coeff * frac

    def _risk_state(
        self, state: TradingState, hp_mid: Optional[float], vfe_mid: Optional[float]
    ) -> Tuple[float, bool, float]:
        del hp_mid  # retained for signature symmetry and future use

        hp_pos = abs(state.position.get(HYDROGEL, 0))
        net_delta_signed = self._portfolio_net_delta(state)
        net_delta_abs = abs(net_delta_signed)

        score = 0.0
        score += 0.42 * min(1.0, hp_pos / float(self.HP_LIMIT))
        score += 0.58 * min(1.0, net_delta_abs / float(self.VFE_LIMIT))

        stress = float(self.history.get("risk_stress", 0.0))
        last_vfe = self.history.get("last_vfe_mid")
        if vfe_mid is not None and last_vfe is not None:
            dv = float(vfe_mid) - float(last_vfe)
            ret_ema_prev = float(self.history.get("vfe_ret_ema", 0.0))
            ret_ema = (1.0 - self.VFE_RET_EMA_ALPHA) * ret_ema_prev + self.VFE_RET_EMA_ALPHA * dv
            self.history["vfe_ret_ema"] = ret_ema

            adverse = (net_delta_signed > 0 and dv < -1.5) or (net_delta_signed < 0 and dv > 1.5)
            if adverse:
                stress = stress * self.STRESS_DECAY + self.STRESS_ADVERSE_STEP
            else:
                stress = stress * self.STRESS_DECAY
        else:
            stress = stress * self.STRESS_DECAY

        self.history["risk_stress"] = stress

        score += 0.12 * min(1.0, stress / 3.0)

        trend_risk = 0.0
        ret_ema_now = float(self.history.get("vfe_ret_ema", 0.0))
        if (net_delta_signed > 0 and ret_ema_now < -1.2) or (net_delta_signed < 0 and ret_ema_now > 1.2):
            trend_risk = 0.06
            score += trend_risk

        risk_off = (
            hp_pos >= self.RISK_HP_POS_TRIGGER
            or net_delta_abs >= self.RISK_NET_DELTA_TRIGGER
            or stress >= self.STRESS_THRESHOLD
            or score >= 0.96
        )
        scale = max(self.RISK_MIN_SCALE, 1.0 - min(1.0, score))
        return scale, risk_off, net_delta_signed

    def _unwind_inventory(
        self,
        symbol: str,
        depth: OrderDepth,
        pos: int,
        limit: int,
        scale: float,
        risk_off: bool,
    ) -> List[Order]:
        if not risk_off:
            return []
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []

        # Only force unwind at very high utilization to avoid churn.
        inv_trigger = int(0.85 * limit)
        if abs(pos) < inv_trigger:
            return []

        cap = max(1, int(self.RISK_UNWIND_MAX * (0.6 + 0.4 * scale)))
        qty = min(cap, abs(pos) - inv_trigger + 1)
        if qty <= 0:
            return []

        if pos > 0:
            return [Order(symbol, bb, -qty)]
        return [Order(symbol, ba, qty)]

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
        base_fair = 0.6 * ewma + 0.4 * self.HP_ANCHOR

        pos = state.position.get(HYDROGEL, 0)
        lim = self.HP_LIMIT
        fair = self._inventory_skewed_fair(base_fair, pos, lim, self.HP_INV_SKEW)
        orders: List[Order] = []

        taker_max = max(4, int(self.HP_TAKER_MAX * scale))
        maker_max = max(6, int((20 if risk_off else 28) * scale))
        taker_enabled = not risk_off

        if taker_enabled and ba <= fair - self.HP_TAKER_EDGE and pos < lim:
            sz = min(taker_max, lim - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(HYDROGEL, ba, sz))
                pos += sz
                fair = self._inventory_skewed_fair(base_fair, pos, lim, self.HP_INV_SKEW)
        if taker_enabled and bb >= fair + self.HP_TAKER_EDGE and pos > -lim:
            sz = min(taker_max, lim + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(HYDROGEL, bb, -sz))
                pos -= sz
                fair = self._inventory_skewed_fair(base_fair, pos, lim, self.HP_INV_SKEW)

        maker_edge = self.HP_MAKER_EDGE + (1.2 if risk_off else 0.0)
        orders.extend(self._guarded_maker(HYDROGEL, depth, pos, fair, lim, maker_edge, max_qty=maker_max))
        # Keep unwind tiny; maker skew already does most de-risking.
        orders.extend(self._unwind_inventory(HYDROGEL, depth, pos, lim, scale, risk_off))
        return orders, mid

    def _vfe_logic(
        self, state: TradingState, scale: float, risk_off: bool, net_delta_signed: float
    ) -> Tuple[List[Order], Optional[float]]:
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
        base_fair = ewma

        pos = state.position.get(VFE, 0)
        lim = self.VFE_LIMIT
        fair = self._inventory_skewed_fair(base_fair, pos, lim, self.VFE_INV_SKEW)
        orders: List[Order] = []

        taker_max = max(3, int(self.VFE_TAKER_MAX * scale))
        maker_max = max(4, int((16 if risk_off else 22) * scale))

        # In risk-off, disable aggressive takers to cut churn and slippage.
        taker_enabled = not risk_off
        if taker_enabled and ba <= fair - self.VFE_TAKER_EDGE and pos < lim:
            sz = min(taker_max, lim - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(VFE, ba, sz))
                pos += sz
                fair = self._inventory_skewed_fair(base_fair, pos, lim, self.VFE_INV_SKEW)
        if taker_enabled and bb >= fair + self.VFE_TAKER_EDGE and pos > -lim:
            sz = min(taker_max, lim + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(VFE, bb, -sz))
                pos -= sz
                fair = self._inventory_skewed_fair(base_fair, pos, lim, self.VFE_INV_SKEW)

        # If option book makes us strongly net-long delta, bias VFE toward selling (and vice versa).
        hedge_shift = 0.0
        if net_delta_signed > 22.0:
            hedge_shift = -0.9
        elif net_delta_signed < -22.0:
            hedge_shift = 0.9

        maker_edge = self.VFE_MAKER_EDGE + (1.0 if risk_off else 0.0)
        orders.extend(
            self._guarded_maker(
                VFE,
                depth,
                pos,
                fair + hedge_shift,
                lim,
                maker_edge,
                max_qty=maker_max,
            )
        )
        orders.extend(self._unwind_inventory(VFE, depth, pos, lim, scale, risk_off))
        return orders, mid

    def _vev_logic(self, state: TradingState, vfe_mid: float, scale: float, risk_off: bool) -> List[Order]:
        orders: List[Order] = []
        maker_max = max(2, int(self.VEV_BASE_QTY * scale))
        ret_ema = float(self.history.get("vfe_ret_ema", 0.0))

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
            lim = max(8, int(lim_base * (0.70 if risk_off else 1.0)))

            # Trend-aware asymmetry:
            # - Falling VFE: avoid aggressively adding long call risk.
            # - Rising VFE: avoid aggressively adding short call risk.
            buy_edge_extra = 0.0
            sell_edge_extra = 0.0
            if ret_ema < -0.6:
                buy_edge_extra += 0.9
            elif ret_ema > 0.6:
                sell_edge_extra += 0.9

            # Inventory skew within each strike.
            pos_frac = max(-1.0, min(1.0, pos / float(max(1, lim))))
            fair_skewed = fair - 1.5 * pos_frac

            qbid = int(round(fair_skewed - (self.VEV_MAKER_EDGE + buy_edge_extra + (0.8 if risk_off else 0.0))))
            qask = int(round(fair_skewed + (self.VEV_MAKER_EDGE + sell_edge_extra + (0.8 if risk_off else 0.0))))
            if qbid >= ba:
                qbid = ba - 1
            if qask <= bb:
                qask = bb + 1
            if qbid >= qask:
                qbid = qask - 1

            room_long = min(lim - pos, maker_max)
            room_short = min(lim + pos, maker_max)
            if room_long > 0:
                orders.append(Order(sym, qbid, room_long))
            if room_short > 0:
                orders.append(Order(sym, qask, -room_short))

            if risk_off and abs(pos) > int(0.65 * lim):
                unwind = min(2, abs(pos) - int(0.65 * lim) + 1)
                if pos > 0:
                    orders.append(Order(sym, bb, -unwind))
                else:
                    orders.append(Order(sym, ba, unwind))

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

        scale, risk_off, net_delta_signed = self._risk_state(state, hp_mid, vfe_mid_for_risk)

        if self.ENABLE_HYDROGEL:
            hp_orders, hp_mid_exec = self._hydrogel_logic(state, scale, risk_off)
            for o in hp_orders:
                result.setdefault(o.symbol, []).append(o)
            if hp_mid_exec is not None:
                self.history["last_hp_mid"] = hp_mid_exec

        vfe_orders, vfe_mid = self._vfe_logic(state, scale, risk_off, net_delta_signed)
        if self.ENABLE_VFE:
            for o in vfe_orders:
                result.setdefault(o.symbol, []).append(o)
        if vfe_mid is not None:
            self.history["last_vfe_mid"] = vfe_mid

        if self.ENABLE_VEV and vfe_mid is not None:
            for o in self._vev_logic(state, vfe_mid, scale, risk_off):
                result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save_state()
