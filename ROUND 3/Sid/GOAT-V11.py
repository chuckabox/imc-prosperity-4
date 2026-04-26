"""
GOAT V11 - Built on trader100's proven $10k base

trader100 (peter's strategy) achieved $10-16k with:
  - HP: anchor (9991) + EWMA blend + volatility-aware spreads
  - VFE: OBI + trend slope + pennying
  - VEV: parabolic smile fit + ITM intrinsic capture

V11 keeps trader100's proven structure and makes 4 targeted improvements:

1. VEV position limit: 100 -> 300 (matches actual exchange limit per V8/V9/V10 evidence)
2. VEV_CAP: 60 -> 100 (1.67x more spread capture per strike)
3. VEV_TAKE_EDGE: 1.0 -> 0.5 (catch more mispricings)
4. Smile MM quote size: 20 -> 30 (more turnover)
5. Add deep OTM (6000, 6500) "sell at 1" strategy - free money if anyone bids

HP and VFE strategies kept IDENTICAL - they're the proven core.
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
    det = (a11 * (a22 * a33 - a23 * a32)
           - a12 * (a21 * a33 - a23 * a31)
           + a13 * (a21 * a32 - a22 * a31))
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
    # CHANGE 1: VEV limit 100 -> 300 (matches actual exchange limit)
    LIMITS = {HYDROGEL: 200, VFE: 200, **{s: 300 for s in VEV_SYMBOLS}}

    # HP Parameters - UNCHANGED from trader100 (proven)
    HP_ANCHOR = 9991.0
    HP_BLEND = 0.65
    HP_EWMA_ALPHA = 0.20
    HP_VOL_ALPHA = 0.10
    HP_TAKE_EDGE = 2
    HP_QUOTE_SIZE = 45

    # VFE Parameters - UNCHANGED from trader100 (proven)
    VFE_EWMA_ALPHA = 0.40
    VFE_OBI_THR = 0.10
    VFE_TREND_WIN = 150
    VFE_TREND_THR = 0.04
    VFE_TREND_BIAS = 15
    VFE_QUOTE_SIZE = 50

    # VEV Parameters - TUNED for more aggression
    VEV_TTE_START = 8.0
    VEV_FIT_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
    VEV_TAKE_EDGE = 0.5  # CHANGE 3: 1.0 -> 0.5 (catch more mispricings)
    VEV_CAP = 100  # CHANGE 2: 60 -> 100 (1.67x more capacity)
    VEV_QUOTE_SIZE = 30  # CHANGE 4: 20 -> 30 (more turnover)
    VEV_DEEP_OTM = [6000, 6500]  # CHANGE 5: free sell-at-1

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

    # ---------- HP Module - IDENTICAL to trader100 ----------
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

    # ---------- VFE Module - IDENTICAL to trader100 ----------
    def _vfe(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        od = state.order_depths[VFE]
        bb, ba, bv, av = self._top(od)
        if bb is None or ba is None:
            return []
        pos = state.position.get(VFE, 0)
        lim = self.LIMITS[VFE]
        mid = (bb + ba) / 2.0

        mids = self.history.setdefault("vfe_mids", [])
        mids.append(mid)
        bias = 0
        if len(mids) >= self.VFE_TREND_WIN:
            slope = (mids[-1] - mids[-self.VFE_TREND_WIN]) / self.VFE_TREND_WIN
            if slope > self.VFE_TREND_THR:
                bias = self.VFE_TREND_BIAS
            elif slope < -self.VFE_TREND_THR:
                bias = -self.VFE_TREND_BIAS

        obi = (bv - av) / (bv + av) if (bv + av) > 0 else 0
        obi_bias = 4 if obi > self.VFE_OBI_THR else (-4 if obi < -self.VFE_OBI_THR else 0)

        fair = mid + (bias + obi_bias) * 0.1
        orders: List[Order] = []

        for p in sorted(od.sell_orders):
            if p > fair:
                break
            sz = min(-od.sell_orders[p], lim - pos)
            if sz > 0:
                orders.append(Order(VFE, p, sz))
                pos += sz
        for p in sorted(od.buy_orders, reverse=True):
            if p < fair:
                break
            sz = min(od.buy_orders[p], lim + pos)
            if sz > 0:
                orders.append(Order(VFE, p, -sz))
                pos -= sz

        q_bid = bb + (1 if bias + obi_bias >= 0 else 0)
        q_ask = ba - (1 if bias + obi_bias <= 0 else 0)

        if pos > 40:
            q_bid -= 1
            q_ask -= 1
        elif pos < -40:
            q_bid += 1
            q_ask += 1

        if q_bid >= q_ask:
            q_bid = q_ask - 1

        if lim - pos > 0:
            orders.append(Order(VFE, q_bid, min(self.VFE_QUOTE_SIZE, lim - pos)))
        if lim + pos > 0:
            orders.append(Order(VFE, q_ask, -min(self.VFE_QUOTE_SIZE, lim + pos)))
        return orders

    # ---------- VEV Module - SCALED UP (limit 300, cap 100, edge 0.5, size 30) ----------
    def _vouchers(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        S = self._mid(state.order_depths[VFE])
        if S is None:
            return []
        T = max(0.5, self.VEV_TTE_START - state.timestamp / TS_PER_DAY)

        all_iv = {}
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

        # ITM intrinsic capture for 4000, 4500 (scaled to cap 100)
        for K in [4000, 4500]:
            sym = f"VEV_{K}"
            od = state.order_depths.get(sym)
            if not od:
                continue
            fair = max(S - K, 0)
            pos = state.position.get(sym, 0)
            lim = self.VEV_CAP
            bb, ba, _, _ = self._top(od)
            if ba and ba < fair:
                qty = min(lim - pos, -od.sell_orders[ba])
                if qty > 0:
                    orders.append(Order(sym, ba, qty))
            if bb and bb > fair + 1:
                qty = min(lim + pos, od.buy_orders[bb])
                if qty > 0:
                    orders.append(Order(sym, bb, -qty))
            if lim - pos > 0:
                orders.append(Order(sym, int(fair), min(self.VEV_QUOTE_SIZE, lim - pos)))
            if lim + pos > 0:
                orders.append(Order(sym, int(fair + 2), -min(self.VEV_QUOTE_SIZE, lim + pos)))

        # Smile MM for 5000-5500 (scaled to cap 100, edge 0.5, size 30)
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
            sx3 = sum(x ** 3 for x in xs)
            sx4 = sum(x ** 4 for x in xs)
            sy = sum(ys)
            sxy = sum(x * y for x, y in zip(xs, ys))
            sx2y = sum(x * x * y for x, y in zip(xs, ys))
            coefs = _solve_3x3([[sx4, sx3, sx2], [sx3, sx2, sx], [sx2, sx, n]],
                               [sx2y, sxy, sy])
            if not coefs:
                continue
            mny = math.log(K / S)
            fit_iv = coefs[0] * mny * mny + coefs[1] * mny + coefs[2]
            fair = bs_call(S, K, T, fit_iv)
            pos = state.position.get(sym, 0)
            lim = self.VEV_CAP
            bb, ba, _, _ = self._top(od)
            if ba and ba <= fair - self.VEV_TAKE_EDGE:
                qty = min(self.VEV_QUOTE_SIZE + 10, lim - pos, -od.sell_orders[ba])
                if qty > 0:
                    orders.append(Order(sym, ba, qty))
            if bb and bb >= fair + self.VEV_TAKE_EDGE:
                qty = min(self.VEV_QUOTE_SIZE + 10, lim + pos, od.buy_orders[bb])
                if qty > 0:
                    orders.append(Order(sym, bb, -qty))
            q_bid = int(round(fair - 1))
            q_ask = int(round(fair + 1))
            if bb:
                q_bid = min(q_bid, bb + 1)
            if ba:
                q_ask = max(q_ask, ba - 1)
            if q_bid >= q_ask:
                q_bid = q_ask - 1
            if lim - pos > 0:
                orders.append(Order(sym, q_bid, min(self.VEV_QUOTE_SIZE, lim - pos)))
            if lim + pos > 0:
                orders.append(Order(sym, q_ask, -min(self.VEV_QUOTE_SIZE, lim + pos)))

        # Deep OTM (6000, 6500) - free sell at 1
        for K in self.VEV_DEEP_OTM:
            sym = f"VEV_{K}"
            od = state.order_depths.get(sym)
            if not od:
                continue
            pos = state.position.get(sym, 0)
            cap_sell = self.LIMITS[sym] + pos
            bb, _, _, _ = self._top(od)
            if bb is not None and bb >= 1 and cap_sell > 0:
                qty = min(od.buy_orders[bb], cap_sell, 60)
                if qty > 0:
                    orders.append(Order(sym, bb, -qty))
                    cap_sell -= qty
            if cap_sell > 0:
                orders.append(Order(sym, 1, -min(cap_sell, 80)))

        return orders

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._load(state)
        result: Dict[str, List[Order]] = {}
        h = self._hp(state)
        v = self._vfe(state)
        o = self._vouchers(state)
        if h:
            result[HYDROGEL] = h
        if v:
            result[VFE] = v
        for vo in o:
            result.setdefault(vo.symbol, []).append(vo)
        return result, 0, self._save()
