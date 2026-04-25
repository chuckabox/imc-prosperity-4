"""trader_ken_v34.py

New architecture (not incremental tuning):
1) HYDROGEL_PACK: microprice-tilted market making for stable carry.
2) VEV chain: cross-strike relative-value trading using smile residuals.
3) VFE: primarily used as delta hedge for option inventory.

Single-file submission, no local imports beyond datamodel.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDRO = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]

VEV_DELTA_APPROX: Dict[int, float] = {
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
    # --- Core limits ---
    HYDRO_LIMIT = 80
    VFE_LIMIT = 80
    VEV_LIMIT_BY_STRIKE: Dict[int, int] = {
        4000: 8,
        4500: 10,
        5000: 28,
        5100: 26,
        5200: 24,
        5300: 20,
        5400: 16,
        5500: 12,
        6000: 6,
        6500: 4,
    }

    # --- Hydrogel maker ---
    H_ALPHA = 0.14
    H_EDGE = 2.0
    H_TAKER_EDGE = 3.0
    H_INV_SKEW = 0.06
    H_TAKER_MAX = 14
    H_MAKER_MAX = 34
    H_MICRO_BIAS = 1.0

    # --- VEV residual arb ---
    VEV_RESID_VAR_ALPHA = 0.10
    VEV_Z_ENTRY = 1.40
    VEV_SPREAD_MAX = 6
    VEV_TAKER_MAX = 7
    VEV_MAKER_MAX = 6
    VEV_MAKER_EDGE = 1.4

    # --- Hedge / risk ---
    NET_DELTA_SOFT = 45.0
    NET_DELTA_HARD = 65.0
    HEDGE_GAIN = 0.75
    VFE_HEDGE_TAKER_MAX = 22
    VFE_ALPHA = 0.16
    VFE_MAKER_EDGE = 2.8

    def __init__(self):
        self.h: Dict = {}

    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.h = json.loads(state.traderData)
            except Exception:
                self.h = {}
        self.h.setdefault("hydro_ewma", None)
        self.h.setdefault("vfe_ewma", None)
        self.h.setdefault("resid_var", {})
        for k in VEV_STRIKES:
            self.h["resid_var"].setdefault(str(k), 4.0)

    def _save(self) -> str:
        return json.dumps(self.h)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders) if depth.buy_orders else None
        ba = min(depth.sell_orders) if depth.sell_orders else None
        return bb, ba

    @staticmethod
    def _best_vols(depth: OrderDepth) -> Tuple[int, int]:
        bb = max(depth.buy_orders) if depth.buy_orders else None
        ba = min(depth.sell_orders) if depth.sell_orders else None
        bv = depth.buy_orders[bb] if bb is not None else 0
        av = -depth.sell_orders[ba] if ba is not None else 0
        return max(0, bv), max(0, av)

    def _net_delta(self, state: TradingState) -> float:
        out = float(state.position.get(VFE, 0))
        for k in VEV_STRIKES:
            out += state.position.get(f"VEV_{k}", 0) * VEV_DELTA_APPROX[k]
        return out

    def _hydro_logic(self, state: TradingState, risk_scale: float) -> List[Order]:
        depth = state.order_depths.get(HYDRO)
        if depth is None:
            return []
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        prev = self.h["hydro_ewma"]
        ewma = mid if prev is None else (1 - self.H_ALPHA) * prev + self.H_ALPHA * mid
        self.h["hydro_ewma"] = ewma

        bv, av = self._best_vols(depth)
        den = bv + av
        imbalance = (bv - av) / den if den > 0 else 0.0
        fair = ewma + self.H_MICRO_BIAS * imbalance

        pos = int(state.position.get(HYDRO, 0))
        inv_adj = self.H_INV_SKEW * pos

        q_bid = int(round(fair - self.H_EDGE - inv_adj))
        q_ask = int(round(fair + self.H_EDGE - inv_adj))
        if q_bid >= ba:
            q_bid = ba - 1
        if q_ask <= bb:
            q_ask = bb + 1
        if q_bid >= q_ask:
            q_bid = q_ask - 1

        orders: List[Order] = []
        taker_max = max(2, int(self.H_TAKER_MAX * risk_scale))
        maker_max = max(4, int(self.H_MAKER_MAX * risk_scale))

        if ba <= fair - self.H_TAKER_EDGE and pos < self.HYDRO_LIMIT:
            sz = min(taker_max, self.HYDRO_LIMIT - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(HYDRO, ba, sz))
                pos += sz
        if bb >= fair + self.H_TAKER_EDGE and pos > -self.HYDRO_LIMIT:
            sz = min(taker_max, self.HYDRO_LIMIT + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(HYDRO, bb, -sz))
                pos -= sz

        room_long = min(self.HYDRO_LIMIT - pos, maker_max)
        room_short = min(self.HYDRO_LIMIT + pos, maker_max)
        if room_long > 0:
            orders.append(Order(HYDRO, q_bid, room_long))
        if room_short > 0:
            orders.append(Order(HYDRO, q_ask, -room_short))
        return orders

    def _build_chain_snapshot(self, state: TradingState, vfe_mid: float) -> List[Tuple[int, int, int, float, float, float]]:
        rows: List[Tuple[int, int, int, float, float, float]] = []
        for k in VEV_STRIKES:
            sym = f"VEV_{k}"
            d = state.order_depths.get(sym)
            if d is None:
                continue
            bb, ba = self._top(d)
            if bb is None or ba is None or ba <= bb:
                continue
            mid = (bb + ba) / 2.0
            intrinsic = max(vfe_mid - k, 0.0)
            prem = mid - intrinsic
            rows.append((k, bb, ba, mid, intrinsic, prem))
        rows.sort(key=lambda x: x[0])
        return rows

    @staticmethod
    def _interp_fair_prem(rows: List[Tuple[int, int, int, float, float, float]], idx: int) -> Optional[float]:
        # Cross-sectional fair premium from adjacent strikes.
        k, _, _, _, _, prem = rows[idx]
        left = rows[idx - 1] if idx - 1 >= 0 else None
        right = rows[idx + 1] if idx + 1 < len(rows) else None
        if left is not None and right is not None:
            lk, *_lr, lp = left
            rk, *_rr, rp = right
            if rk == lk:
                return prem
            w = (k - lk) / float(rk - lk)
            return lp * (1 - w) + rp * w
        if left is not None:
            return left[-1]
        if right is not None:
            return right[-1]
        return None

    def _vev_logic(self, state: TradingState, vfe_mid: float, risk_scale: float, risk_off: bool) -> List[Order]:
        rows = self._build_chain_snapshot(state, vfe_mid)
        if len(rows) < 3:
            return []

        signals: List[Tuple[float, int, int, int, float]] = []
        # (score, strike, bb, ba, fair_prem)
        for i, row in enumerate(rows):
            k, bb, ba, _mid, _intr, prem = row
            spread = ba - bb
            if spread > self.VEV_SPREAD_MAX:
                continue
            fair_prem = self._interp_fair_prem(rows, i)
            if fair_prem is None:
                continue
            resid = prem - fair_prem
            key = str(k)
            prev_var = float(self.h["resid_var"][key])
            new_var = (1 - self.VEV_RESID_VAR_ALPHA) * prev_var + self.VEV_RESID_VAR_ALPHA * (resid * resid)
            new_var = max(1.0, new_var)
            self.h["resid_var"][key] = new_var
            z = resid / (new_var ** 0.5)
            signals.append((abs(z), k, bb, ba, z))

        signals.sort(reverse=True, key=lambda x: x[0])
        # Trade only top few strongest dislocations to avoid overtrading noise.
        top = signals[:3]
        orders: List[Order] = []
        for _score, k, bb, ba, z in top:
            sym = f"VEV_{k}"
            d = state.order_depths[sym]
            pos = int(state.position.get(sym, 0))
            lim = self.VEV_LIMIT_BY_STRIKE[k]

            taker_max = max(1, int(self.VEV_TAKER_MAX * risk_scale))
            maker_max = max(1, int(self.VEV_MAKER_MAX * risk_scale))
            if risk_off:
                maker_max = max(1, maker_max // 2)

            # Overpriced residual -> sell; underpriced -> buy.
            if (not risk_off) and z >= self.VEV_Z_ENTRY and pos > -lim:
                sz = min(taker_max, lim + pos, d.buy_orders.get(bb, 0))
                if sz > 0:
                    orders.append(Order(sym, bb, -sz))
                    pos -= sz
            if (not risk_off) and z <= -self.VEV_Z_ENTRY and pos < lim:
                sz = min(taker_max, lim - pos, -d.sell_orders.get(ba, 0))
                if sz > 0:
                    orders.append(Order(sym, ba, sz))
                    pos += sz

            # Provide around local mid with slight inventory lean.
            mid = (bb + ba) / 2.0
            inv_adj = 0.08 * pos
            q_bid = int(round(mid - self.VEV_MAKER_EDGE - inv_adj))
            q_ask = int(round(mid + self.VEV_MAKER_EDGE - inv_adj))
            if q_bid >= ba:
                q_bid = ba - 1
            if q_ask <= bb:
                q_ask = bb + 1
            if q_bid < q_ask:
                room_long = min(lim - pos, maker_max)
                room_short = min(lim + pos, maker_max)
                if room_long > 0:
                    orders.append(Order(sym, q_bid, room_long))
                if room_short > 0:
                    orders.append(Order(sym, q_ask, -room_short))
        return orders

    def _vfe_logic(self, state: TradingState, target_delta: float, risk_scale: float, risk_off: bool) -> List[Order]:
        d = state.order_depths.get(VFE)
        if d is None:
            return []
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        prev = self.h["vfe_ewma"]
        ewma = mid if prev is None else (1 - self.VFE_ALPHA) * prev + self.VFE_ALPHA * mid
        self.h["vfe_ewma"] = ewma

        pos = int(state.position.get(VFE, 0))
        lim = self.VFE_LIMIT
        orders: List[Order] = []

        # Hedge options delta toward target.
        gap = target_delta - pos
        if abs(gap) > 4 and not risk_off:
            max_hedge = max(1, int(self.VFE_HEDGE_TAKER_MAX * risk_scale))
            if gap > 0 and pos < lim:
                sz = min(max_hedge, lim - pos, int(gap * self.HEDGE_GAIN), -d.sell_orders[ba])
                if sz > 0:
                    orders.append(Order(VFE, ba, sz))
                    pos += sz
            elif gap < 0 and pos > -lim:
                sz = min(max_hedge, lim + pos, int((-gap) * self.HEDGE_GAIN), d.buy_orders[bb])
                if sz > 0:
                    orders.append(Order(VFE, bb, -sz))
                    pos -= sz

        # Light maker around EWMA.
        inv_adj = 0.06 * pos
        q_bid = int(round(ewma - self.VFE_MAKER_EDGE - inv_adj))
        q_ask = int(round(ewma + self.VFE_MAKER_EDGE - inv_adj))
        if q_bid >= ba:
            q_bid = ba - 1
        if q_ask <= bb:
            q_ask = bb + 1
        if q_bid < q_ask:
            maker_max = max(2, int(10 * risk_scale))
            room_long = min(lim - pos, maker_max)
            room_short = min(lim + pos, maker_max)
            if room_long > 0:
                orders.append(Order(VFE, q_bid, room_long))
            if room_short > 0:
                orders.append(Order(VFE, q_ask, -room_short))
        return orders

    def run(self, state: TradingState):
        self._load(state)
        result: Dict[str, List[Order]] = {}

        net_delta = self._net_delta(state)
        risk_off = abs(net_delta) >= self.NET_DELTA_HARD
        if abs(net_delta) >= self.NET_DELTA_HARD:
            risk_scale = 0.40
        elif abs(net_delta) >= self.NET_DELTA_SOFT:
            risk_scale = 0.65
        else:
            risk_scale = 1.0

        hydro_orders = self._hydro_logic(state, risk_scale)
        for o in hydro_orders:
            result.setdefault(o.symbol, []).append(o)

        # Need VFE mid for options intrinsic.
        vfe_depth = state.order_depths.get(VFE)
        vfe_mid = None
        if vfe_depth is not None:
            bb, ba = self._top(vfe_depth)
            if bb is not None and ba is not None:
                vfe_mid = (bb + ba) / 2.0

        if vfe_mid is not None:
            vev_orders = self._vev_logic(state, vfe_mid, risk_scale, risk_off)
            for o in vev_orders:
                result.setdefault(o.symbol, []).append(o)

        # Recompute desired VFE hedge from option inventory after option orders.
        desired_vfe = 0.0
        for k in VEV_STRIKES:
            desired_vfe += state.position.get(f"VEV_{k}", 0) * (-VEV_DELTA_APPROX[k])
        # keep hedge bounded; avoid turning VFE into a standalone directional bet.
        if desired_vfe > self.VFE_LIMIT:
            desired_vfe = float(self.VFE_LIMIT)
        if desired_vfe < -self.VFE_LIMIT:
            desired_vfe = float(-self.VFE_LIMIT)

        vfe_orders = self._vfe_logic(state, desired_vfe, risk_scale, risk_off)
        for o in vfe_orders:
            result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save()

