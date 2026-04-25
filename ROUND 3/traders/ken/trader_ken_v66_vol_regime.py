"""trader_ken_v66_vol_regime.py

Innovative round-3 design:
- Hydrogel remains stable spread-capture base.
- Options traded as a volatility regime book (not single-strike z-signal).
- Uses implied-vs-realized volatility spread proxy around 5200/5300.
- Delta-hedges option inventory with VFE using dead-band execution.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDRO = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
CORE_STRIKES = [5200, 5300]
ALL_STRIKES = [5000, 5100, 5200, 5300, 5400]
DELTA = {5000: 0.82, 5100: 0.70, 5200: 0.57, 5300: 0.44, 5400: 0.31}


class Trader:
    HP_LIMIT = 80
    VFE_LIMIT = 80
    STRIKE_LIMIT = {5000: 20, 5100: 24, 5200: 36, 5300: 36, 5400: 24}

    # Hydrogel baseline (close to v41).
    HP_ANCHOR = 9993.0
    HP_EWMA_ALPHA = 0.20
    HP_TAKER_EDGE = 2.5
    HP_MAKER_EDGE = 2.3
    HP_TAKER_MAX = 16

    # VFE baseline.
    VFE_EWMA_ALPHA = 0.20
    VFE_MAKER_EDGE = 2.4
    VFE_TAKER_EDGE = 4.8
    VFE_TAKER_MAX = 8

    # Vol regime model.
    RV_ALPHA = 0.06
    IV_ALPHA = 0.08
    VR_ALPHA = 0.10
    VR_ENTRY = 0.0060
    VR_EXIT = 0.0025
    CORE_SPREAD_MAX = 10
    CORE_TAKER_MAX = 8

    # Delta hedge.
    HEDGE_BAND = 10.0
    HEDGE_HARD = 22.0
    HEDGE_TAKER_MAX = 14
    HEDGE_MAKER_MAX = 8

    # Risk and safety.
    NET_DELTA_SOFT = 52.0
    NET_DELTA_HARD = 66.0
    RISK_MIN_SCALE = 0.35
    OPEN_PHASE_TS = 120_000
    OPEN_SCALE_MULT = 0.85

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
        self.h.setdefault("last_vfe_mid", None)
        self.h.setdefault("rv_day", 0.018)
        self.h.setdefault("iv_proxy", 0.013)
        self.h.setdefault("vol_regime", 0.0)
        self.h.setdefault("vol_state", 0)  # -1 short vol, 0 flat, +1 long vol

    def _save(self) -> str:
        return json.dumps(self.h)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    @staticmethod
    def _mid(depth: Optional[OrderDepth]) -> Optional[float]:
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
        net = float(state.position.get(VFE, 0))
        for k in ALL_STRIKES:
            net += state.position.get(f"VEV_{k}", 0) * DELTA[k]
        return net

    def _risk_scale(self, state: TradingState) -> Tuple[float, bool]:
        nd = abs(self._portfolio_net_delta(state))
        score = min(1.0, nd / float(self.NET_DELTA_HARD))
        scale = max(self.RISK_MIN_SCALE, 1.0 - 0.7 * score)
        if self._in_open_phase(state):
            scale *= self.OPEN_SCALE_MULT
        return scale, nd >= self.NET_DELTA_HARD

    def _guarded_maker(
        self, sym: str, d: OrderDepth, pos: int, fair: float, limit: int, edge: float, mx: int
    ) -> List[Order]:
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
        out: List[Order] = []
        rl = min(limit - pos, mx)
        rs = min(limit + pos, mx)
        if rl > 0:
            out.append(Order(sym, qbid, rl))
        if rs > 0:
            out.append(Order(sym, qask, -rs))
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
        fair = 0.6 * ewma + 0.4 * self.HP_ANCHOR

        pos = int(state.position.get(HYDRO, 0))
        lim = self.HP_LIMIT
        out: List[Order] = []
        taker_max = max(4, int(self.HP_TAKER_MAX * scale))
        if (not risk_off) and ba <= fair - self.HP_TAKER_EDGE and pos < lim:
            q = min(taker_max, lim - pos, -d.sell_orders.get(ba, 0))
            if q > 0:
                out.append(Order(HYDRO, ba, q))
                pos += q
        if (not risk_off) and bb >= fair + self.HP_TAKER_EDGE and pos > -lim:
            q = min(taker_max, lim + pos, d.buy_orders.get(bb, 0))
            if q > 0:
                out.append(Order(HYDRO, bb, -q))
                pos -= q
        out.extend(self._guarded_maker(HYDRO, d, pos, fair, lim, self.HP_MAKER_EDGE + (0.8 if risk_off else 0.0), max(6, int(28 * scale))))
        return out

    def _vfe_mm_logic(self, state: TradingState, scale: float, risk_off: bool) -> Tuple[List[Order], Optional[float]]:
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

        # Update realized vol proxy from vfe returns.
        last_mid = self.h.get("last_vfe_mid")
        if last_mid is not None and last_mid > 0:
            lr = math.log(max(1.0, mid) / float(last_mid))
            rv_day = float(self.h.get("rv_day", 0.018))
            rv_tick = rv_day / math.sqrt(10000.0)
            rv_tick = (1 - self.RV_ALPHA) * rv_tick + self.RV_ALPHA * abs(lr)
            self.h["rv_day"] = max(0.006, min(0.05, rv_tick * math.sqrt(10000.0)))
        self.h["last_vfe_mid"] = mid

        pos = int(state.position.get(VFE, 0))
        lim = self.VFE_LIMIT
        out: List[Order] = []
        taker_max = max(2, int(self.VFE_TAKER_MAX * scale))
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
        out.extend(self._guarded_maker(VFE, d, pos, fair, lim, self.VFE_MAKER_EDGE + (0.8 if risk_off else 0.0), max(4, int(16 * scale))))
        return out, mid

    def _update_vol_regime(self, state: TradingState, vfe_mid: float) -> float:
        mids = []
        for k in CORE_STRIKES:
            m = self._mid(state.order_depths.get(f"VEV_{k}"))
            if m is not None:
                intr = max(vfe_mid - k, 0.0)
                ext = max(0.0, m - intr)
                mids.append(ext)
        if mids:
            # Coarse IV proxy in "vol/day" units.
            iv_sample = max(0.0001, sum(mids) / len(mids) / max(12.0, vfe_mid))
            iv = float(self.h.get("iv_proxy", 0.013))
            iv = (1 - self.IV_ALPHA) * iv + self.IV_ALPHA * iv_sample * 9.5
            self.h["iv_proxy"] = max(0.005, min(0.04, iv))
        iv = float(self.h.get("iv_proxy", 0.013))
        rv = float(self.h.get("rv_day", 0.018))
        vr = float(self.h.get("vol_regime", 0.0))
        vr = (1 - self.VR_ALPHA) * vr + self.VR_ALPHA * (rv - iv)
        self.h["vol_regime"] = vr
        return vr

    def _vol_regime_signal_state(self) -> int:
        vr = float(self.h.get("vol_regime", 0.0))
        st = int(self.h.get("vol_state", 0))
        if st == 0:
            if vr >= self.VR_ENTRY:
                st = 1
            elif vr <= -self.VR_ENTRY:
                st = -1
        elif st == 1:
            if vr <= self.VR_EXIT:
                st = 0
        else:
            if vr >= -self.VR_EXIT:
                st = 0
        self.h["vol_state"] = st
        return st

    def _vev_vol_logic(self, state: TradingState, vfe_mid: float, scale: float, risk_off: bool) -> List[Order]:
        if risk_off:
            return []
        vol_state = self._vol_regime_signal_state()
        if vol_state == 0:
            return []

        orders: List[Order] = []
        for k in CORE_STRIKES:
            sym = f"VEV_{k}"
            d = state.order_depths.get(sym)
            if d is None:
                continue
            bb, ba = self._top(d)
            if bb is None or ba is None or (ba - bb) > self.CORE_SPREAD_MAX:
                continue
            pos = int(state.position.get(sym, 0))
            lim = int(self.STRIKE_LIMIT[k])
            mx = max(1, int(self.CORE_TAKER_MAX * scale))
            if vol_state > 0:
                # Long-vol: buy options when vol appears cheap.
                if pos < lim:
                    q = min(mx, lim - pos, -d.sell_orders.get(ba, 0))
                    if q > 0:
                        orders.append(Order(sym, ba, q))
            else:
                # Short-vol: sell options when vol appears rich.
                if pos > -lim:
                    q = min(mx, lim + pos, d.buy_orders.get(bb, 0))
                    if q > 0:
                        orders.append(Order(sym, bb, -q))
        return orders

    def _vfe_hedge_logic(self, state: TradingState, scale: float, risk_off: bool) -> List[Order]:
        d = state.order_depths.get(VFE)
        if d is None:
            return []
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return []
        opt_delta = 0.0
        for k in ALL_STRIKES:
            opt_delta += state.position.get(f"VEV_{k}", 0) * DELTA[k]
        target = int(round(-opt_delta))
        cur = int(state.position.get(VFE, 0))
        resid = cur - target
        if abs(float(resid)) <= self.HEDGE_BAND:
            return []

        out: List[Order] = []
        lim = self.VFE_LIMIT
        hard = abs(float(resid)) >= self.HEDGE_HARD
        tmx = max(2, int(self.HEDGE_TAKER_MAX * scale))
        mmx = max(2, int(self.HEDGE_MAKER_MAX * scale))
        if resid > 0:
            need = min(resid, lim + cur)
            if need > 0:
                if hard or risk_off:
                    q = min(need, tmx, d.buy_orders.get(bb, 0))
                    if q > 0:
                        out.append(Order(VFE, bb, -q))
                else:
                    out.append(Order(VFE, max(bb, ba - 1), -min(need, mmx)))
        else:
            need = min(-resid, lim - cur)
            if need > 0:
                if hard or risk_off:
                    q = min(need, tmx, -d.sell_orders.get(ba, 0))
                    if q > 0:
                        out.append(Order(VFE, ba, q))
                else:
                    out.append(Order(VFE, min(ba, bb + 1), min(need, mmx)))
        return out

    def run(self, state: TradingState):
        self._load(state)
        out: Dict[str, List[Order]] = {}

        scale, risk_off = self._risk_scale(state)

        for o in self._hydro_logic(state, scale, risk_off):
            out.setdefault(o.symbol, []).append(o)

        vfe_orders, vfe_mid = self._vfe_mm_logic(state, scale, risk_off)
        for o in vfe_orders:
            out.setdefault(o.symbol, []).append(o)

        if vfe_mid is not None:
            self._update_vol_regime(state, vfe_mid)
            for o in self._vev_vol_logic(state, vfe_mid, scale, risk_off):
                out.setdefault(o.symbol, []).append(o)

        for o in self._vfe_hedge_logic(state, scale, risk_off):
            out.setdefault(o.symbol, []).append(o)

        return out, 0, self._save()

