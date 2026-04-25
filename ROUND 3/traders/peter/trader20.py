"""trader20.py - Final R3 trader: HP anchor-blend MM + VFE OBI MM + light voucher.

All three asset classes traded. HP+VFE robust (delta-1 MM core), voucher
module is intentionally minimal — only the K=5400 structural cheap edge.

Why minimal voucher: per-strike IV anchors are stable but signal
amplitude per tick is small (~0.0005 IV → ~2-3 price ticks max), and
delta hedging churns VFE spread cost faster than alpha. Trade only the
strongest, persistent cross-day pattern: K=5400 trades below the smile
fit by ~0.0006 IV every day. Buy on edge, exit on reversion.

Modules (validated D0/D1/D2):
  1. HP   : anchor-blend MM (trader2 style, fair = 0.6*ewma + 0.4*9991)
  2. VFE  : OBI MM with rolling-slope trend bias (trader1/10 style)
  3. VEV  : 5400 buy-only (and 5500 sell-only) at parabolic-fit edge
            with very small per-strike cap. No hedge — vega tiny vs limits.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState


# ---------------- BS helpers ----------------
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
    for _ in range(48):
        mid = 0.5 * (lo + hi)
        if bs_call(S, K, T, mid) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-5:
            break
    return 0.5 * (lo + hi)


# ---------------- constants ----------------
HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]
TS_PER_DAY = 1_000_000


class Trader:
    LIMITS = {HYDROGEL: 80, VFE: 80, **{s: 60 for s in VEV_SYMBOLS}}

    # ---- HP anchor-blend MM ----
    HP_ANCHOR = 9991.0
    HP_EWMA_ALPHA = 0.20
    HP_BLEND = 0.6                # fair = HP_BLEND*ewma + (1-HP_BLEND)*anchor
    HP_TAKE_EDGE = 2
    HP_QUOTE_FRONT = 20
    HP_QUOTE_SECOND = 12
    HP_SKEW_SOFT = 25
    HP_SKEW_HARD = 50
    HP_FLATTEN = 70

    # ---- VFE OBI MM ----
    VFE_EWMA_ALPHA = 0.35
    VFE_TAKE_EDGE = 1
    VFE_OBI_THRESHOLD = 0.15
    VFE_NEUTRAL_FRONT = 8
    VFE_NEUTRAL_SECOND = 8
    VFE_LEAN_AGG = 25
    VFE_LEAN_DEF = 5
    VFE_LEAN_OFFSET = 3
    VFE_SKEW_SOFT = 25
    VFE_SKEW_HARD = 50
    VFE_FLATTEN_HARD = 70
    VFE_TREND_WIN = 200
    VFE_TREND_THRESHOLD = 0.05
    VFE_TREND_BIAS = 8

    # ---- Voucher: light structural alpha ----
    # Smile pattern (stable across D0/D1/D2): K=5400 trades ~0.0006 IV
    # below the parabolic fit, K=5500 trades ~0.0003 above. The other
    # ATM strikes are noise. We trade only these two with strict caps.
    VEV_TTE_AT_START = 7.0
    VEV_FIT_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]   # for parabola
    VEV_TARGET_STRIKES: Dict[int, int] = {                   # K -> sign
        5400: +1,   # buy: structurally cheap
        5500: -1,   # sell: structurally rich
    }
    VEV_ENABLED = True
    VEV_PRICE_EDGE_TAKE = 1.5     # take when |fair - market| >= this
    VEV_EXIT_EDGE = -1.0          # exit when reversion flips beyond this
    VEV_TAKE_SIZE = 15
    VEV_PER_STRIKE_CAP = 50

    @classmethod
    def apply_params(cls, params: dict) -> None:
        for k, v in params.items():
            if hasattr(cls, k):
                setattr(cls, k, v)

    def __init__(self) -> None:
        self.history: Dict = {}

    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("vfe_mids", [])

    def _save(self) -> str:
        h = dict(self.history)
        if "vfe_mids" in h and len(h["vfe_mids"]) > 600:
            h["vfe_mids"] = h["vfe_mids"][-600:]
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
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0

    # ---------- HP anchor-blend MM ----------
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
        fair = self.HP_BLEND * ewma + (1 - self.HP_BLEND) * self.HP_ANCHOR
        pos = state.position.get(HYDROGEL, 0)
        lim = self.LIMITS[HYDROGEL]

        orders: List[Order] = []
        bb, ba, _, _ = self._top(od)

        if ba is not None and ba <= fair - self.HP_TAKE_EDGE:
            qty = min(-od.sell_orders[ba], lim - pos)
            if qty > 0:
                orders.append(Order(HYDROGEL, ba, qty)); pos += qty
        if bb is not None and bb >= fair + self.HP_TAKE_EDGE:
            qty = min(od.buy_orders[bb], lim + pos)
            if qty > 0:
                orders.append(Order(HYDROGEL, bb, -qty)); pos -= qty

        if abs(pos) > self.HP_SKEW_HARD:
            skew = -2 if pos > 0 else 2
        elif abs(pos) > self.HP_SKEW_SOFT:
            skew = -1 if pos > 0 else 1
        else:
            skew = 0

        bid_px = int(round(fair - 1 + skew))
        ask_px = int(round(fair + 1 + skew))
        front = self.HP_QUOTE_FRONT
        second = self.HP_QUOTE_SECOND
        if abs(pos) >= self.HP_FLATTEN:
            front = front // 3
            second = 0

        max_buy = lim - pos
        max_sell = lim + pos
        if max_buy > 0:
            orders.append(Order(HYDROGEL, bid_px, min(front, max_buy)))
            if second > 0 and max_buy - front > 0:
                orders.append(Order(HYDROGEL, bid_px - 2, min(second, max_buy - front)))
        if max_sell > 0:
            orders.append(Order(HYDROGEL, ask_px, -min(front, max_sell)))
            if second > 0 and max_sell - front > 0:
                orders.append(Order(HYDROGEL, ask_px + 2, -min(second, max_sell - front)))
        return orders

    # ---------- VFE OBI MM ----------
    def _vfe_trend_bias(self, mid: float) -> Tuple[int, int]:
        mids = self.history.setdefault("vfe_mids", [])
        mids.append(mid)
        if len(mids) > self.VFE_TREND_WIN + 5:
            del mids[: len(mids) - (self.VFE_TREND_WIN + 5)]
        if len(mids) < self.VFE_TREND_WIN:
            return 0, 0
        slope = (mids[-1] - mids[-self.VFE_TREND_WIN]) / self.VFE_TREND_WIN
        if slope > self.VFE_TREND_THRESHOLD:
            return self.VFE_TREND_BIAS, 0
        if slope < -self.VFE_TREND_THRESHOLD:
            return 0, self.VFE_TREND_BIAS
        return 0, 0

    def _vfe(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        depth = state.order_depths[VFE]
        bb, ba, bv, av = self._top(depth)
        if bb is None or ba is None:
            return []
        pos = state.position.get(VFE, 0)
        lim = self.LIMITS[VFE]
        mid = (bb + ba) / 2.0
        prev = self.history.get("vfe_ewma")
        ewma = mid if prev is None else (1 - self.VFE_EWMA_ALPHA) * prev + self.VFE_EWMA_ALPHA * mid
        self.history["vfe_ewma"] = ewma
        fair = ewma
        obi = (bv - av) / (bv + av) if (bv + av) > 0 else 0.0
        bias_buy, bias_sell = self._vfe_trend_bias(mid)

        orders: List[Order] = []
        if ba <= fair - self.VFE_TAKE_EDGE and pos < lim:
            sz = min(lim - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(VFE, ba, sz)); pos += sz
        if bb >= fair + self.VFE_TAKE_EDGE and pos > -lim:
            sz = min(lim + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(VFE, bb, -sz)); pos -= sz

        bullish = obi > self.VFE_OBI_THRESHOLD
        bearish = obi < -self.VFE_OBI_THRESHOLD
        room_long = max(0, lim - pos)
        room_short = max(0, lim + pos)

        if pos >= self.VFE_FLATTEN_HARD:
            buy_front = buy_second = 0
        else:
            base = self.VFE_LEAN_AGG if bullish else (self.VFE_LEAN_DEF if bearish else self.VFE_NEUTRAL_FRONT)
            buy_front = min(base + bias_buy, room_long)
            buy_second = min(self.VFE_NEUTRAL_SECOND, max(0, room_long - buy_front))
        if pos <= -self.VFE_FLATTEN_HARD:
            sell_front = sell_second = 0
        else:
            base = self.VFE_LEAN_AGG if bearish else (self.VFE_LEAN_DEF if bullish else self.VFE_NEUTRAL_FRONT)
            sell_front = min(base + bias_sell, room_short)
            sell_second = min(self.VFE_NEUTRAL_SECOND, max(0, room_short - sell_front))

        if pos >= self.VFE_SKEW_HARD: skew = -2
        elif pos >= self.VFE_SKEW_SOFT: skew = -1
        elif pos <= -self.VFE_SKEW_HARD: skew = 2
        elif pos <= -self.VFE_SKEW_SOFT: skew = 1
        else: skew = 0

        if bullish:
            qbid, qask = bb + 1 + skew, ba + self.VFE_LEAN_OFFSET + skew
        elif bearish:
            qbid, qask = bb - self.VFE_LEAN_OFFSET + skew, ba - 1 + skew
        else:
            qbid, qask = bb + 1 + skew, ba - 1 + skew
        if qbid >= qask:
            qbid = qask - 1

        if buy_front > 0: orders.append(Order(VFE, qbid, buy_front))
        if sell_front > 0: orders.append(Order(VFE, qask, -sell_front))
        if buy_second > 0: orders.append(Order(VFE, qbid - 2, buy_second))
        if sell_second > 0: orders.append(Order(VFE, qask + 2, -sell_second))
        return orders

    # ---------- Voucher light alpha ----------
    @staticmethod
    def _solve_3x3(A, b):
        a11, a12, a13 = A[0]; a21, a22, a23 = A[1]; a31, a32, a33 = A[2]
        det = (a11*(a22*a33 - a23*a32) - a12*(a21*a33 - a23*a31) + a13*(a21*a32 - a22*a31))
        if abs(det) < 1e-12:
            return None
        inv = 1.0 / det
        x1 = (b[0]*(a22*a33 - a23*a32) - a12*(b[1]*a33 - a23*b[2]) + a13*(b[1]*a32 - a22*b[2])) * inv
        x2 = (a11*(b[1]*a33 - a23*b[2]) - b[0]*(a21*a33 - a23*a31) + a13*(a21*b[2] - b[1]*a31)) * inv
        x3 = (a11*(a22*b[2] - b[1]*a32) - a12*(a21*b[2] - b[1]*a31) + b[0]*(a21*a32 - a22*a31)) * inv
        return (x1, x2, x3)

    def _fit_smile(self, iv_pts):
        """Fit parabola y=a*x^2+b*x+c on (mny, iv). Returns (a,b,c) or None."""
        if len(iv_pts) < 4:
            return None
        xs = [p[0] for p in iv_pts]; ys = [p[1] for p in iv_pts]
        n = len(xs)
        sx = sum(xs); sx2 = sum(x*x for x in xs); sx3 = sum(x**3 for x in xs); sx4 = sum(x**4 for x in xs)
        sy = sum(ys); sxy = sum(x*y for x, y in zip(xs, ys)); sx2y = sum(x*x*y for x, y in zip(xs, ys))
        return self._solve_3x3([[sx4, sx3, sx2], [sx3, sx2, sx], [sx2, sx, n]],
                               [sx2y, sxy, sy])

    def _vouchers(self, state: TradingState) -> List[Order]:
        if not self.VEV_ENABLED:
            return []
        if VFE not in state.order_depths:
            return []
        S = self._mid(state.order_depths[VFE])
        if S is None:
            return []
        T = max(0.5, self.VEV_TTE_AT_START - state.timestamp / TS_PER_DAY)

        # Build IV cross-section for ALL fit strikes
        all_iv = {}
        for K in self.VEV_FIT_STRIKES:
            sym = f"VEV_{K}"
            if sym not in state.order_depths:
                continue
            mid = self._mid(state.order_depths[sym])
            if mid is None or mid <= 0:
                continue
            iv = iv_solve(mid, S, K, T)
            if iv is not None:
                all_iv[K] = iv

        orders: List[Order] = []
        # Leave-one-out fit per target strike — exposes the structural bias
        for K, sign in self.VEV_TARGET_STRIKES.items():
            sym = f"VEV_{K}"
            if sym not in state.order_depths:
                continue
            od = state.order_depths[sym]
            bb, ba, _, _ = self._top(od)
            if bb is None or ba is None:
                continue

            fit_strikes = [k for k in self.VEV_FIT_STRIKES if k != K and k in all_iv]
            if len(fit_strikes) < 4:
                continue
            iv_pts = [(math.log(k / S), all_iv[k]) for k in fit_strikes]
            coefs = self._fit_smile(iv_pts)
            if coefs is None:
                continue
            a_q, b_q, c_q = coefs
            mny = math.log(K / S)
            fit_iv = a_q * mny * mny + b_q * mny + c_q
            fair = bs_call(S, K, T, fit_iv)
            pos = state.position.get(sym, 0)
            cap = self.VEV_PER_STRIKE_CAP

            if sign > 0:
                if ba <= fair - self.VEV_PRICE_EDGE_TAKE and pos < cap:
                    qty = min(self.VEV_TAKE_SIZE, cap - pos, -od.sell_orders[ba])
                    if qty > 0:
                        orders.append(Order(sym, ba, qty))
                if pos > 0 and bb >= fair + self.VEV_EXIT_EDGE:
                    qty = min(self.VEV_TAKE_SIZE, pos, od.buy_orders[bb])
                    if qty > 0:
                        orders.append(Order(sym, bb, -qty))
            else:
                if bb >= fair + self.VEV_PRICE_EDGE_TAKE and pos > -cap:
                    qty = min(self.VEV_TAKE_SIZE, cap + pos, od.buy_orders[bb])
                    if qty > 0:
                        orders.append(Order(sym, bb, -qty))
                if pos < 0 and ba <= fair - self.VEV_EXIT_EDGE:
                    qty = min(self.VEV_TAKE_SIZE, -pos, -od.sell_orders[ba])
                    if qty > 0:
                        orders.append(Order(sym, ba, qty))
        return orders

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._load(state)
        result: Dict[str, List[Order]] = {}
        o = self._hp(state)
        if o: result[HYDROGEL] = o
        o = self._vfe(state)
        if o: result[VFE] = o
        for vo in self._vouchers(state):
            result.setdefault(vo.symbol, []).append(vo)
        return result, 0, self._save()
