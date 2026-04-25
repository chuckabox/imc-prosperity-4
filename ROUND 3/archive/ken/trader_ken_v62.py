"""trader_ken_v62.py

Portal-oriented Round 3 trader:
- Stable Hydrogel maker-first base engine
- Options alpha focused on 5200/5300 mispricing
- Explicit VFE delta-hedge rebalancing for option inventory
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDRO = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100, 5200, 5300, 5400]

PREM_INIT: Dict[int, float] = {
    5000: 6.0,
    5100: 19.0,
    5200: 49.0,
    5300: 47.0,
    5400: 16.0,
}
PREM_BOUNDS: Dict[int, Tuple[float, float]] = {
    5000: (2.0, 15.0),
    5100: (9.0, 32.0),
    5200: (28.0, 78.0),
    5300: (20.0, 76.0),
    5400: (6.0, 38.0),
}
VEV_DELTA_APPROX: Dict[int, float] = {
    5000: 0.82,
    5100: 0.70,
    5200: 0.57,
    5300: 0.44,
    5400: 0.31,
}
STRIKE_CAP: Dict[int, int] = {
    5000: 24,
    5100: 28,
    5200: 36,
    5300: 36,
    5400: 28,
}


class Trader:
    ENABLE_HYDRO = True
    ENABLE_VFE = True
    ENABLE_VEV = True

    HP_LIMIT = 80
    VFE_LIMIT = 80
    HP_ANCHOR = 9992.0
    HP_EWMA_ALPHA = 0.20
    VFE_EWMA_ALPHA = 0.18

    # Hydrogel: maker-first, strict taker.
    HP_MAKER_EDGE = 2.2
    HP_MAKER_MAX = 32
    HP_TAKER_EDGE = 5.2
    HP_TAKER_MAX = 5
    HP_TAKER_SPREAD_MAX = 10
    HP_TAKER_COOLDOWN_TS = 1400

    # VFE: light directional MM + hedge utility.
    VFE_MAKER_EDGE = 2.7
    VFE_MAKER_MAX = 12
    VFE_TAKER_EDGE = 5.5
    VFE_TAKER_MAX = 8

    # Options mispricing model.
    PREM_ALPHA = 0.08
    PREM_VAR_ALPHA = 0.08
    VEV_Z_ENTRY = 1.45
    VEV_SPREAD_MAX: Dict[int, int] = {5000: 8, 5100: 8, 5200: 8, 5300: 8, 5400: 8}
    VEV_TAKER_MAX: Dict[int, int] = {5000: 3, 5100: 4, 5200: 7, 5300: 7, 5400: 4}
    VEV_SIGNALS_PER_TICK = 2

    # Delta hedge controls.
    HEDGE_BAND = 10.0
    HEDGE_HARD = 22.0
    HEDGE_TAKER_MAX = 16
    HEDGE_MAKER_MAX = 10

    # Risk controls.
    NET_DELTA_SOFT = 52.0
    NET_DELTA_HARD = 66.0
    RISK_MIN_SCALE = 0.35

    OPEN_PHASE_TS = 120_000
    OPEN_SCALE_MULT = 0.82

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
        self.h.setdefault("hp_taker_until", -1)
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

    @staticmethod
    def _book_mid(depth: Optional[OrderDepth]) -> Optional[float]:
        if depth is None:
            return None
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0

    def _in_open_phase(self, state: TradingState) -> bool:
        return int(state.timestamp) <= self.OPEN_PHASE_TS

    def _portfolio_net_delta(self, state: TradingState) -> float:
        nd = float(state.position.get(VFE, 0))
        for k in VEV_STRIKES:
            nd += state.position.get(f"VEV_{k}", 0) * VEV_DELTA_APPROX[k]
        return nd

    def _risk_scale(self, state: TradingState) -> Tuple[float, bool]:
        nd = abs(self._portfolio_net_delta(state))
        score = min(1.0, nd / float(self.NET_DELTA_HARD))
        scale = max(self.RISK_MIN_SCALE, 1.0 - 0.7 * score)
        risk_off = nd >= self.NET_DELTA_HARD
        if self._in_open_phase(state):
            scale *= self.OPEN_SCALE_MULT
        return scale, risk_off

    def _guarded_maker(
        self,
        symbol: str,
        depth: OrderDepth,
        pos: int,
        fair: float,
        limit: int,
        edge: float,
        max_qty: int,
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

        out: List[Order] = []
        room_long = min(limit - pos, max_qty)
        room_short = min(limit + pos, max_qty)
        if room_long > 0:
            out.append(Order(symbol, qbid, room_long))
        if room_short > 0:
            out.append(Order(symbol, qask, -room_short))
        return out

    def _hydro_logic(self, state: TradingState, scale: float, risk_off: bool) -> List[Order]:
        d = state.order_depths.get(HYDRO)
        if d is None:
            return []
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        prev = self.h["hp_ewma"]
        ewma = mid if prev is None else (1 - self.HP_EWMA_ALPHA) * prev + self.HP_EWMA_ALPHA * mid
        self.h["hp_ewma"] = ewma
        fair = 0.58 * ewma + 0.42 * self.HP_ANCHOR

        pos = int(state.position.get(HYDRO, 0))
        lim = self.HP_LIMIT
        now = int(state.timestamp)
        spread = ba - bb
        out: List[Order] = []

        taker_ok = (
            (not risk_off)
            and spread <= self.HP_TAKER_SPREAD_MAX
            and now >= int(self.h.get("hp_taker_until", -1))
        )
        taker_max = max(1, int(self.HP_TAKER_MAX * scale))
        if taker_ok and ba <= fair - self.HP_TAKER_EDGE and pos < lim and pos <= 28:
            q = min(taker_max, lim - pos, -d.sell_orders.get(ba, 0))
            if q > 0:
                out.append(Order(HYDRO, ba, q))
                pos += q
                self.h["hp_taker_until"] = now + self.HP_TAKER_COOLDOWN_TS
        if taker_ok and bb >= fair + self.HP_TAKER_EDGE and pos > -lim and pos >= -28:
            q = min(taker_max, lim + pos, d.buy_orders.get(bb, 0))
            if q > 0:
                out.append(Order(HYDRO, bb, -q))
                pos -= q
                self.h["hp_taker_until"] = now + self.HP_TAKER_COOLDOWN_TS

        maker_edge = self.HP_MAKER_EDGE + (0.8 if risk_off else 0.0)
        maker_max = max(6, int(self.HP_MAKER_MAX * scale))
        out.extend(self._guarded_maker(HYDRO, d, pos, fair, lim, maker_edge, maker_max))
        return out

    def _vfe_logic(self, state: TradingState, scale: float, risk_off: bool) -> Tuple[List[Order], Optional[float]]:
        d = state.order_depths.get(VFE)
        if d is None:
            return [], None
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return [], None

        mid = (bb + ba) / 2.0
        prev = self.h["vfe_ewma"]
        ewma = mid if prev is None else (1 - self.VFE_EWMA_ALPHA) * prev + self.VFE_EWMA_ALPHA * mid
        self.h["vfe_ewma"] = ewma
        fair = ewma

        pos = int(state.position.get(VFE, 0))
        lim = self.VFE_LIMIT
        out: List[Order] = []
        taker_max = max(2, int(self.VFE_TAKER_MAX * scale))
        maker_max = max(3, int(self.VFE_MAKER_MAX * scale))

        if (not risk_off) and ba <= fair - self.VFE_TAKER_EDGE and pos < lim:
            q = min(taker_max, lim - pos, -d.sell_orders.get(ba, 0))
            if q > 0:
                out.append(Order(VFE, ba, q))
                pos += q
        if (not risk_off) and bb >= fair + self.VFE_TAKER_EDGE and pos > -lim:
            q = min(taker_max, lim + pos, d.buy_orders.get(bb, 0))
            if q > 0:
                out.append(Order(VFE, bb, -q))
                pos -= q

        maker_edge = self.VFE_MAKER_EDGE + (0.9 if risk_off else 0.0)
        out.extend(self._guarded_maker(VFE, d, pos, fair, lim, maker_edge, maker_max))
        return out, mid

    def _vev_logic(self, state: TradingState, vfe_mid: float, scale: float, risk_off: bool) -> List[Order]:
        if risk_off:
            return []

        cands: List[Tuple[float, int, int, int, float, float]] = []
        for strike in VEV_STRIKES:
            sym = f"VEV_{strike}"
            d = state.order_depths.get(sym)
            if d is None:
                continue
            bb, ba = self._top(d)
            if bb is None or ba is None:
                continue
            spread = ba - bb
            if spread <= 0 or spread > self.VEV_SPREAD_MAX[strike]:
                continue

            obs_mid = (bb + ba) / 2.0
            intrinsic = max(vfe_mid - strike, 0.0)
            obs_prem = obs_mid - intrinsic

            key = str(strike)
            prev_prem = float(self.h["prem"][key])
            prem = (1 - self.PREM_ALPHA) * prev_prem + self.PREM_ALPHA * obs_prem
            lo, hi = PREM_BOUNDS[strike]
            prem = max(lo, min(hi, prem))
            self.h["prem"][key] = prem

            dev = obs_prem - prem
            prev_var = float(self.h["prem_var"][key])
            var = (1 - self.PREM_VAR_ALPHA) * prev_var + self.PREM_VAR_ALPHA * (dev * dev)
            var = max(1.0, var)
            self.h["prem_var"][key] = var

            z = dev / (var ** 0.5)
            fair = intrinsic + prem
            # 5200/5300 are preferred by adding a tiny score boost.
            bias = 0.15 if strike in (5200, 5300) else 0.0
            cands.append((abs(z) + bias, strike, bb, ba, z, fair))

        if not cands:
            return []

        cands.sort(reverse=True, key=lambda x: x[0])
        out: List[Order] = []
        used = 0
        for _, strike, bb, ba, z, fair in cands:
            if used >= self.VEV_SIGNALS_PER_TICK or abs(z) < self.VEV_Z_ENTRY:
                break
            sym = f"VEV_{strike}"
            d = state.order_depths[sym]
            pos = int(state.position.get(sym, 0))
            lim = STRIKE_CAP[strike]
            taker_max = max(1, int(self.VEV_TAKER_MAX[strike] * scale))
            if z <= -self.VEV_Z_ENTRY and ba <= fair and pos < lim:
                q = min(taker_max, lim - pos, -d.sell_orders.get(ba, 0))
                if q > 0:
                    out.append(Order(sym, ba, q))
                    used += 1
            elif z >= self.VEV_Z_ENTRY and bb >= fair and pos > -lim:
                q = min(taker_max, lim + pos, d.buy_orders.get(bb, 0))
                if q > 0:
                    out.append(Order(sym, bb, -q))
                    used += 1
        return out

    def _vfe_hedge_logic(self, state: TradingState, scale: float, risk_off: bool) -> List[Order]:
        d = state.order_depths.get(VFE)
        if d is None:
            return []
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return []

        options_delta = 0.0
        for k in VEV_STRIKES:
            options_delta += state.position.get(f"VEV_{k}", 0) * VEV_DELTA_APPROX[k]
        target_vfe = int(round(-options_delta))
        cur_vfe = int(state.position.get(VFE, 0))
        resid = cur_vfe - target_vfe
        abs_resid = abs(float(resid))
        if abs_resid <= self.HEDGE_BAND:
            return []

        out: List[Order] = []
        lim = self.VFE_LIMIT
        hard = abs_resid >= self.HEDGE_HARD
        taker_max = max(2, int(self.HEDGE_TAKER_MAX * scale))
        maker_max = max(2, int(self.HEDGE_MAKER_MAX * scale))

        # resid > 0 means too long VFE; need sell. resid < 0 means need buy.
        if resid > 0:
            q = min(resid, lim + cur_vfe)
            if q <= 0:
                return []
            if hard or risk_off:
                qx = min(q, taker_max, d.buy_orders.get(bb, 0))
                if qx > 0:
                    out.append(Order(VFE, bb, -qx))
            else:
                out.append(Order(VFE, max(bb, ba - 1), -min(q, maker_max)))
        else:
            q = min(-resid, lim - cur_vfe)
            if q <= 0:
                return []
            if hard or risk_off:
                qx = min(q, taker_max, -d.sell_orders.get(ba, 0))
                if qx > 0:
                    out.append(Order(VFE, ba, qx))
            else:
                out.append(Order(VFE, min(ba, bb + 1), min(q, maker_max)))
        return out

    def run(self, state: TradingState):
        self._load(state)
        out: Dict[str, List[Order]] = {}

        scale, risk_off = self._risk_scale(state)

        if self.ENABLE_HYDRO:
            for o in self._hydro_logic(state, scale, risk_off):
                out.setdefault(o.symbol, []).append(o)

        vfe_mid = None
        if self.ENABLE_VFE:
            vfe_orders, vfe_mid = self._vfe_logic(state, scale, risk_off)
            for o in vfe_orders:
                out.setdefault(o.symbol, []).append(o)

        if self.ENABLE_VEV and vfe_mid is not None:
            for o in self._vev_logic(state, vfe_mid, scale, risk_off):
                out.setdefault(o.symbol, []).append(o)

        # Hedge after options orders are generated (uses current book + current inventory).
        if self.ENABLE_VFE:
            for o in self._vfe_hedge_logic(state, scale, risk_off):
                out.setdefault(o.symbol, []).append(o)

        return out, 0, self._save()

