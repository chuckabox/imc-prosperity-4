"""trader_ken_v81_hybrid_symbol_mix.py

Requested hybrid mapping (standalone, no local imports):
- HYDROGEL: Peter v100 logic
- VELVETFRUIT_EXTRACT: v79b-style logic
- VEV_4000/4500/5000/5100/5300: Peter v100 logic
- VEV_5200: Peter v200 flavor (wider take edge)
- VEV_5400/5500/6000/6500: Peter baseline "as-is"
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def iv_solve(price: float, S: float, K: float, T: float) -> Optional[float]:
    intr = max(0.0, S - K)
    if price <= intr + 1e-6 or price >= S:
        return None
    lo, hi = 1e-4, 2.0
    for _ in range(32):
        mid = 0.5 * (lo + hi)
        if bs_call(S, K, T, mid) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def _solve_3x3(A, b):
    a11, a12, a13 = A[0]
    a21, a22, a23 = A[1]
    a31, a32, a33 = A[2]
    det = (
        a11 * (a22 * a33 - a23 * a32)
        - a12 * (a21 * a33 - a23 * a31)
        + a13 * (a21 * a32 - a22 * a31)
    )
    if abs(det) < 1e-12:
        return None
    inv = 1.0 / det
    x1 = (b[0] * (a22 * a33 - a23 * a32) - a12 * (b[1] * a33 - a23 * b[2]) + a13 * (b[1] * a32 - a22 * b[2])) * inv
    x2 = (a11 * (b[1] * a33 - a23 * b[2]) - b[0] * (a21 * a33 - a23 * a31) + a13 * (a21 * b[2] - b[1] * a31)) * inv
    x3 = (a11 * (a22 * b[2] - b[1] * a32) - a12 * (a21 * b[2] - b[1] * a31) + b[0] * (a21 * a32 - a22 * a31)) * inv
    return (x1, x2, x3)


HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]
TS_PER_DAY = 1_000_000


class Trader:
    LIMITS = {HYDROGEL: 200, VFE: 200, **{s: 100 for s in VEV_SYMBOLS}}

    # HYDROGEL from Peter v100
    HP_ANCHOR = 9991.0
    HP_BLEND = 0.65
    HP_EWMA_ALPHA = 0.20
    HP_VOL_ALPHA = 0.10
    HP_TAKE_EDGE = 2
    HP_QUOTE_SIZE = 45

    # VFE from v79b flavor
    VFE_EWMA_ALPHA = 0.22
    VFE_MAKER_EDGE = 1.0
    VFE_TAKER_EDGE = 1.8
    VFE_TAKER_MAX = 42
    VFE_MICRO_TILT = 0.24
    VFE_HEDGE_BAND = 14
    VFE_HEDGE_AGGRO_BAND = 52
    VFE_HEDGE_MAX = 38
    OPEN_PHASE_TS = 120_000
    VFE_SPEED_TRIGGER = 54
    SPEED_COOLDOWN_TS = 40_000
    OPEN_SCALE_MULT = 0.97
    SPEED_SCALE_MULT = 0.90

    # VEV from Peter baseline with selective 5200 override
    VEV_TTE_START = 8.0
    VEV_FIT_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
    VEV_TAKE_EDGE_DEFAULT = 1.0   # Peter v100
    VEV_TAKE_EDGE_5200 = 1.5      # Peter v200 for 5200 only
    VEV_CAP = 60

    # For v79b-style VFE hedge target
    DELTA_APPROX: Dict[int, float] = {
        4000: 1.00,
        4500: 0.98,
        5000: 0.82,
        5100: 0.70,
        5200: 0.57,
        5300: 0.44,
        5400: 0.31,
        5500: 0.21,
        6000: 0.10,
        6500: 0.05,
    }

    def __init__(self) -> None:
        self.history: Dict = {}

    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("hp_vol", 0.0)
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("vfe_mids", [])
        self.history.setdefault("last_vfe_pos", 0)
        self.history.setdefault("vfe_speed_cooldown_until", -1)

    def _save(self) -> str:
        h = dict(self.history)
        if "vfe_mids" in h and len(h["vfe_mids"]) > 500:
            h["vfe_mids"] = h["vfe_mids"][-500:]
        return json.dumps(h)

    @staticmethod
    def _top(d: OrderDepth) -> Tuple[Optional[int], Optional[int], int, int]:
        bb = max(d.buy_orders) if d.buy_orders else None
        ba = min(d.sell_orders) if d.sell_orders else None
        bv = d.buy_orders[bb] if bb is not None else 0
        av = -d.sell_orders[ba] if ba is not None else 0
        return bb, ba, bv, av

    @staticmethod
    def _mid(d: OrderDepth) -> Optional[float]:
        bb = max(d.buy_orders) if d.buy_orders else None
        ba = min(d.sell_orders) if d.sell_orders else None
        return (bb + ba) / 2.0 if bb is not None and ba is not None else None

    # Peter-style HP module (as requested)
    def _hp(self, state: TradingState) -> List[Order]:
        if HYDROGEL not in state.order_depths:
            return []
        od = state.order_depths[HYDROGEL]
        m = self._mid(od)
        if m is None:
            return []

        prev = self.history.get("hp_ewma")
        ewma = m if prev is None else self.HP_EWMA_ALPHA * m + (1 - self.HP_EWMA_ALPHA) * prev
        self.history["hp_ewma"] = ewma

        diff = abs(m - (prev or m))
        vol = (1 - self.HP_VOL_ALPHA) * self.history["hp_vol"] + self.HP_VOL_ALPHA * diff
        self.history["hp_vol"] = vol

        fair = self.HP_BLEND * ewma + (1 - self.HP_BLEND) * self.HP_ANCHOR
        pos = state.position.get(HYDROGEL, 0)
        lim = self.LIMITS[HYDROGEL]
        bb, ba, _, _ = self._top(od)
        orders: List[Order] = []

        if ba is not None and ba <= fair - self.HP_TAKE_EDGE:
            qty = min(-od.sell_orders[ba], lim - pos)
            if qty > 0:
                orders.append(Order(HYDROGEL, ba, qty))
                pos += qty
        if bb is not None and bb >= fair + self.HP_TAKE_EDGE:
            qty = min(od.buy_orders[bb], lim + pos)
            if qty > 0:
                orders.append(Order(HYDROGEL, bb, -qty))
                pos -= qty

        spread = 1 + int(vol * 2)
        skew = int(round(3 * (pos / lim)))
        bid_px = int(round(fair - spread - skew))
        ask_px = int(round(fair + spread - skew))
        if bb is not None:
            bid_px = max(bid_px, bb + (1 if pos < lim * 0.3 else 0))
        if ba is not None:
            ask_px = min(ask_px, ba - (1 if pos > -lim * 0.3 else 0))
        if bid_px >= ask_px:
            bid_px = ask_px - 1

        if lim - pos > 0:
            orders.append(Order(HYDROGEL, bid_px, min(self.HP_QUOTE_SIZE, lim - pos)))
        if lim + pos > 0:
            orders.append(Order(HYDROGEL, ask_px, -min(self.HP_QUOTE_SIZE, lim + pos)))
        return orders

    # Helpers for v79b-style VFE execution
    def _in_open_phase(self, state: TradingState) -> bool:
        return int(state.timestamp) <= self.OPEN_PHASE_TS

    def _speed_limited_vfe(self, state: TradingState) -> bool:
        now = int(state.timestamp)
        pos = int(state.position.get(VFE, 0))
        last_pos = int(self.history.get("last_vfe_pos", 0))
        if abs(pos - last_pos) >= self.VFE_SPEED_TRIGGER:
            self.history["vfe_speed_cooldown_until"] = now + self.SPEED_COOLDOWN_TS
        self.history["last_vfe_pos"] = pos
        return now < int(self.history.get("vfe_speed_cooldown_until", -1))

    def _guarded_maker_vfe(self, od: OrderDepth, pos: int, fair: float, limit: int, edge: float, max_qty: int) -> List[Order]:
        orders: List[Order] = []
        bb, ba, _, _ = self._top(od)
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
        if room_long > 0:
            orders.append(Order(VFE, qbid, room_long))
        if room_short > 0:
            orders.append(Order(VFE, qask, -room_short))
        return orders

    def _deep_take_vfe(self, od: OrderDepth, fair: float, pos: int, limit: int, edge: float, max_qty: int) -> Tuple[List[Order], int]:
        orders: List[Order] = []
        curr = pos
        rem_buy = max_qty
        for ask in sorted(od.sell_orders.keys()):
            if ask > fair - edge or curr >= limit or rem_buy <= 0:
                break
            avail = -od.sell_orders[ask]
            qty = min(avail, limit - curr, rem_buy)
            if qty > 0:
                orders.append(Order(VFE, ask, qty))
                curr += qty
                rem_buy -= qty
        rem_sell = max_qty
        for bid in sorted(od.buy_orders.keys(), reverse=True):
            if bid < fair + edge or curr <= -limit or rem_sell <= 0:
                break
            avail = od.buy_orders[bid]
            qty = min(avail, limit + curr, rem_sell)
            if qty > 0:
                orders.append(Order(VFE, bid, -qty))
                curr -= qty
                rem_sell -= qty
        return orders, curr

    # VFE from v79b spirit (microprice + deep take + maker + hedge target)
    def _vfe_v79b(self, state: TradingState, target_pos: int) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        od = state.order_depths[VFE]
        bb, ba, bv, av = self._top(od)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0

        prev = self.history.get("vfe_ewma")
        ewma = mid if prev is None else (1 - self.VFE_EWMA_ALPHA) * prev + self.VFE_EWMA_ALPHA * mid
        self.history["vfe_ewma"] = ewma
        micro = (bb * av + ba * bv) / (bv + av) if (bv + av) > 0 else mid
        fair = (1.0 - self.VFE_MICRO_TILT) * ewma + self.VFE_MICRO_TILT * micro

        local_scale = 1.0
        if self._in_open_phase(state):
            local_scale *= self.OPEN_SCALE_MULT
        if self._speed_limited_vfe(state):
            local_scale *= self.SPEED_SCALE_MULT

        pos = state.position.get(VFE, 0)
        lim = self.LIMITS[VFE]
        orders: List[Order] = []

        residual = target_pos - pos
        if abs(residual) >= self.VFE_HEDGE_BAND:
            hmx = max(8, int(self.VFE_HEDGE_MAX * local_scale))
            if residual > 0 and pos < lim:
                hq = min(hmx, residual, lim - pos, -od.sell_orders[ba])
                if hq > 0:
                    orders.append(Order(VFE, ba, hq))
                    pos += hq
            elif residual < 0 and pos > -lim:
                hq = min(hmx, -residual, lim + pos, od.buy_orders[bb])
                if hq > 0:
                    orders.append(Order(VFE, bb, -hq))
                    pos -= hq

        taker_max = max(10, int(self.VFE_TAKER_MAX * local_scale))
        maker_max = max(30, int(128 * local_scale))
        if abs(target_pos - pos) <= self.VFE_HEDGE_AGGRO_BAND:
            tk, pos = self._deep_take_vfe(od, fair, pos, lim, self.VFE_TAKER_EDGE, taker_max)
            orders.extend(tk)
        orders.extend(self._guarded_maker_vfe(od, pos, fair, lim, self.VFE_MAKER_EDGE, maker_max))
        return orders

    # Peter baseline options engine with per-strike source override for 5200
    def _vouchers_hybrid(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        S = self._mid(state.order_depths[VFE])
        if S is None:
            return []
        T = max(0.5, self.VEV_TTE_START - state.timestamp / TS_PER_DAY)

        all_iv: Dict[int, float] = {}
        for K in self.VEV_FIT_STRIKES:
            sym = f"VEV_{K}"
            if sym not in state.order_depths:
                continue
            m = self._mid(state.order_depths[sym])
            if m and m > 0:
                iv = iv_solve(m, S, K, T)
                if iv:
                    all_iv[K] = iv

        orders: List[Order] = []

        # 4000/4500 from Peter baseline
        for K in [4000, 4500]:
            sym = f"VEV_{K}"
            od = state.order_depths.get(sym)
            if not od:
                continue
            fair = max(S - K, 0.0)
            pos = state.position.get(sym, 0)
            lim = self.VEV_CAP
            bb, ba, _, _ = self._top(od)
            if ba and ba < fair:
                orders.append(Order(sym, ba, min(lim - pos, -od.sell_orders[ba])))
            if bb and bb > fair + 1:
                orders.append(Order(sym, bb, -min(lim + pos, od.buy_orders[bb])))
            if lim - pos > 0:
                orders.append(Order(sym, int(fair), min(20, lim - pos)))
            if lim + pos > 0:
                orders.append(Order(sym, int(fair + 2), -min(20, lim + pos)))

        # Smile module for 5000..5500 from Peter, with 5200 using v200 take edge
        for K in self.VEV_FIT_STRIKES:
            sym = f"VEV_{K}"
            od = state.order_depths.get(sym)
            if not od:
                continue
            fit_strikes = [k for k in self.VEV_FIT_STRIKES if k != K and k in all_iv]
            if len(fit_strikes) < 4:
                continue
            iv_pts = [(math.log(k / S), all_iv[k]) for k in fit_strikes]
            xs = [p[0] for p in iv_pts]
            ys = [p[1] for p in iv_pts]
            n = len(xs)
            sx = sum(xs)
            sx2 = sum(x * x for x in xs)
            sx3 = sum(x**3 for x in xs)
            sx4 = sum(x**4 for x in xs)
            sy = sum(ys)
            sxy = sum(x * y for x, y in zip(xs, ys))
            sx2y = sum(x * x * y for x, y in zip(xs, ys))
            coefs = _solve_3x3([[sx4, sx3, sx2], [sx3, sx2, sx], [sx2, sx, n]], [sx2y, sxy, sy])
            if not coefs:
                continue
            mny = math.log(K / S)
            fit_iv = coefs[0] * mny * mny + coefs[1] * mny + coefs[2]
            fair = bs_call(S, K, T, fit_iv)
            pos = state.position.get(sym, 0)
            lim = self.VEV_CAP
            bb, ba, _, _ = self._top(od)

            take_edge = self.VEV_TAKE_EDGE_5200 if K == 5200 else self.VEV_TAKE_EDGE_DEFAULT
            if ba and ba <= fair - take_edge:
                orders.append(Order(sym, ba, min(30, lim - pos, -od.sell_orders[ba])))
            if bb and bb >= fair + take_edge:
                orders.append(Order(sym, bb, -min(30, lim + pos, od.buy_orders[bb])))

            q_bid, q_ask = int(round(fair - 1)), int(round(fair + 1))
            if bb:
                q_bid = min(q_bid, bb + 1)
            if ba:
                q_ask = max(q_ask, ba - 1)
            if q_bid >= q_ask:
                q_bid = q_ask - 1
            if lim - pos > 0:
                orders.append(Order(sym, q_bid, min(20, lim - pos)))
            if lim + pos > 0:
                orders.append(Order(sym, q_ask, -min(20, lim + pos)))

        # 6000/6500 remain "as-is" (Peter baseline has no active logic here)
        return orders

    def _target_vfe_from_delta(self, state: TradingState) -> int:
        net_delta = 0.0
        for K, d in self.DELTA_APPROX.items():
            net_delta += state.position.get(f"VEV_{K}", 0) * d
        target = int(round(-net_delta))
        lim = self.LIMITS[VFE]
        return max(-lim, min(lim, target))

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._load(state)
        result: Dict[str, List[Order]] = {}

        h = self._hp(state)
        if h:
            result[HYDROGEL] = h

        o = self._vouchers_hybrid(state)
        for vo in o:
            result.setdefault(vo.symbol, []).append(vo)

        target_vfe = self._target_vfe_from_delta(state)
        v = self._vfe_v79b(state, target_vfe)
        if v:
            result[VFE] = v

        return result, 0, self._save()