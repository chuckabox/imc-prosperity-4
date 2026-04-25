"""trader30.py - Optimized R3 trader.
Improves upon trader20 and DISCORD patterns.
- HP: Anchor-blend MM (0.6*EWMA + 0.4*9991) - STABLE.
- VFE: OBI MM + Trend Bias - WORKHORSE.
- VEV: Enhanced Smile-Fair MM.
  - Solves for IV per strike (trader20 style).
  - Parabolic leave-one-out fit for pricing (trader20 style).
  - Incorporates K=4000/4500 ITM MM (DISCORD style).
  - Quoting + Aggressing for all active strikes (5000-5500).
  - No delta hedge (avoids spread tax).
"""
from __future__ import annotations
import json
import math
from typing import Dict, List, Optional, Tuple
from datamodel import Order, OrderDepth, TradingState

# ---------------- Math Helpers ----------------
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
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if bs_call(S, K, T, mid) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-5:
            break
    return 0.5 * (lo + hi)

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

# ---------------- Constants ----------------
HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]
TS_PER_DAY = 1_000_000

class Trader:
    LIMITS = {HYDROGEL: 100, VFE: 100, **{s: 100 for s in VEV_SYMBOLS}}

    # HP Parameters
    HP_ANCHOR = 9991.0
    HP_EWMA_ALPHA = 0.20
    HP_BLEND = 0.6
    HP_TAKE_EDGE = 2
    HP_QUOTE_FRONT = 30
    HP_QUOTE_SECOND = 15
    HP_SKEW_SOFT = 30
    HP_SKEW_HARD = 60

    # VFE Parameters
    VFE_EWMA_ALPHA = 0.35
    VFE_TAKE_EDGE = 1
    VFE_OBI_THRESHOLD = 0.15
    VFE_TREND_WIN = 200
    VFE_TREND_THRESHOLD = 0.05
    VFE_TREND_BIAS = 10

    # VEV Parameters
    VEV_TTE_AT_START = 7.0
    VEV_FIT_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
    VEV_SMILE_BIAS = {5400: -0.0006, 5500: 0.0003}
    VEV_TAKE_EDGE = 1.5
    VEV_PER_STRIKE_CAP = 60
    VEV_QUOTE_SIZE = 25

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

    # ---------- HP Module ----------
    def _hp(self, state: TradingState) -> List[Order]:
        if HYDROGEL not in state.order_depths: return []
        od = state.order_depths[HYDROGEL]
        m = self._mid(od)
        if m is None: return []
        prev = self.history.get("hp_ewma")
        ewma = m if prev is None else self.HP_EWMA_ALPHA * m + (1 - self.HP_EWMA_ALPHA) * prev
        self.history["hp_ewma"] = ewma
        fair = self.HP_BLEND * ewma + (1 - self.HP_BLEND) * self.HP_ANCHOR
        pos = state.position.get(HYDROGEL, 0)
        lim = self.LIMITS[HYDROGEL]
        
        orders: List[Order] = []
        bb, ba, _, _ = self._top(od)
        
        # Take
        if ba is not None and ba <= fair - self.HP_TAKE_EDGE:
            qty = min(-od.sell_orders[ba], lim - pos)
            if qty > 0: orders.append(Order(HYDROGEL, ba, qty)); pos += qty
        if bb is not None and bb >= fair + self.HP_TAKE_EDGE:
            qty = min(od.buy_orders[bb], lim + pos)
            if qty > 0: orders.append(Order(HYDROGEL, bb, -qty)); pos -= qty

        # Quote
        skew = 0
        if pos > self.HP_SKEW_HARD: skew = -2
        elif pos > self.HP_SKEW_SOFT: skew = -1
        elif pos < -self.HP_SKEW_HARD: skew = 2
        elif pos < -self.HP_SKEW_SOFT: skew = 1
        
        bid_px = int(round(fair - 1 + skew))
        ask_px = int(round(fair + 1 + skew))
        
        if lim - pos > 0: orders.append(Order(HYDROGEL, bid_px, min(self.HP_QUOTE_FRONT, lim - pos)))
        if lim + pos > 0: orders.append(Order(HYDROGEL, ask_px, -min(self.HP_QUOTE_FRONT, lim + pos)))
        return orders

    # ---------- VFE Module ----------
    def _vfe(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths: return []
        od = state.order_depths[VFE]
        bb, ba, bv, av = self._top(od)
        if bb is None or ba is None: return []
        pos = state.position.get(VFE, 0)
        lim = self.LIMITS[VFE]
        mid = (bb + ba) / 2.0
        prev = self.history.get("vfe_ewma")
        ewma = mid if prev is None else (1 - self.VFE_EWMA_ALPHA) * prev + self.VFE_EWMA_ALPHA * mid
        self.history["vfe_ewma"] = ewma
        
        # Trend
        mids = self.history.setdefault("vfe_mids", [])
        mids.append(mid)
        bias = 0
        if len(mids) >= self.VFE_TREND_WIN:
            slope = (mids[-1] - mids[-self.VFE_TREND_WIN]) / self.VFE_TREND_WIN
            if slope > self.VFE_TREND_THRESHOLD: bias = self.VFE_TREND_BIAS
            elif slope < -self.VFE_TREND_THRESHOLD: bias = -self.VFE_TREND_BIAS

        obi = (bv - av) / (bv + av) if (bv + av) > 0 else 0
        obi_bias = 5 if obi > self.VFE_OBI_THRESHOLD else (-5 if obi < -self.VFE_OBI_THRESHOLD else 0)

        fair = ewma
        orders: List[Order] = []
        # Take
        if ba <= fair - self.VFE_TAKE_EDGE:
            sz = min(lim - pos, -od.sell_orders[ba])
            if sz > 0: orders.append(Order(VFE, ba, sz)); pos += sz
        if bb >= fair + self.VFE_TAKE_EDGE:
            sz = min(lim + pos, od.buy_orders[bb])
            if sz > 0: orders.append(Order(VFE, bb, -sz)); pos -= sz

        # Quote
        q_bid = bb + 1 if bias + obi_bias > 0 else (bb if bias + obi_bias == 0 else bb - 1)
        q_ask = ba - 1 if bias + obi_bias < 0 else (ba if bias + obi_bias == 0 else ba + 1)
        
        if pos > 30: q_bid -= 1; q_ask -= 1
        elif pos < -30: q_bid += 1; q_ask += 1
        
        if q_bid >= q_ask: q_bid = q_ask - 1
        
        if lim - pos > 0: orders.append(Order(VFE, q_bid, min(30, lim - pos)))
        if lim + pos > 0: orders.append(Order(VFE, q_ask, -min(30, lim + pos)))
        return orders

    # ---------- VEV Module ----------
    def _vouchers(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths: return []
        S = self._mid(state.order_depths[VFE])
        if S is None: return []
        T = max(0.5, self.VEV_TTE_AT_START - state.timestamp / TS_PER_DAY)

        # 1. IV Cross-section
        all_iv = {}
        for K in self.VEV_FIT_STRIKES:
            sym = f"VEV_{K}"
            if sym not in state.order_depths: continue
            mid = self._mid(state.order_depths[sym])
            if mid is None or mid <= 0: continue
            iv = iv_solve(mid, S, K, T)
            if iv is not None: all_iv[K] = iv

        orders: List[Order] = []
        # 2. ITM strikes
        for K in [4000, 4500]:
            sym = f"VEV_{K}"
            if sym not in state.order_depths: continue
            od = state.order_depths[sym]
            fair = max(S - K, 0)
            pos = state.position.get(sym, 0)
            lim = self.VEV_PER_STRIKE_CAP
            bb, ba, _, _ = self._top(od)
            if ba is not None and ba < fair:
                qty = min(lim - pos, -od.sell_orders[ba])
                if qty > 0: orders.append(Order(sym, ba, qty)); pos += qty
            if bb is not None and bb > fair + 1:
                qty = min(lim + pos, od.buy_orders[bb])
                if qty > 0: orders.append(Order(sym, bb, -qty)); pos -= qty
            
            if lim - pos > 0: orders.append(Order(sym, int(fair), min(15, lim - pos)))
            if lim + pos > 0: orders.append(Order(sym, int(fair + 2), -min(15, lim + pos)))

        # 3. Smile-fair trading
        for K in self.VEV_FIT_STRIKES:
            sym = f"VEV_{K}"
            if sym not in state.order_depths: continue
            
            fit_strikes = [k for k in self.VEV_FIT_STRIKES if k != K and k in all_iv]
            if len(fit_strikes) < 4: continue
            iv_pts = [(math.log(k / S), all_iv[k]) for k in fit_strikes]
            
            xs = [p[0] for p in iv_pts]; ys = [p[1] for p in iv_pts]; n = len(xs)
            sx = sum(xs); sx2 = sum(x*x for x in xs); sx3 = sum(x**3 for x in xs); sx4 = sum(x**4 for x in xs)
            sy = sum(ys); sxy = sum(x*y for x, y in zip(xs, ys)); sx2y = sum(x*x*y for x, y in zip(xs, ys))
            coefs = _solve_3x3([[sx4, sx3, sx2], [sx3, sx2, sx], [sx2, sx, n]], [sx2y, sxy, sy])
            if coefs is None: continue
            
            mny = math.log(K / S)
            fit_iv = coefs[0] * mny * mny + coefs[1] * mny + coefs[2]
            fair = bs_call(S, K, T, fit_iv)
            
            pos = state.position.get(sym, 0)
            cap = self.VEV_PER_STRIKE_CAP
            od = state.order_depths[sym]
            bb, ba, _, _ = self._top(od)
            
            # Take
            if ba is not None and ba <= fair - self.VEV_TAKE_EDGE:
                qty = min(self.VEV_QUOTE_SIZE, cap - pos, -od.sell_orders[ba])
                if qty > 0: orders.append(Order(sym, ba, qty)); pos += qty
            if bb is not None and bb >= fair + self.VEV_TAKE_EDGE:
                qty = min(self.VEV_QUOTE_SIZE, cap + pos, od.buy_orders[bb])
                if qty > 0: orders.append(Order(sym, bb, -qty)); pos -= qty
            
            # Quote
            q_bid = int(round(fair - 1.0))
            q_ask = int(round(fair + 1.0))
            if bb is not None: q_bid = min(q_bid, bb + 1)
            if ba is not None: q_ask = max(q_ask, ba - 1)
            if q_bid >= q_ask: q_bid = q_ask - 1
            
            if cap - pos > 0: orders.append(Order(sym, q_bid, min(self.VEV_QUOTE_SIZE, cap - pos)))
            if cap + pos > 0: orders.append(Order(sym, q_ask, -min(self.VEV_QUOTE_SIZE, cap + pos)))
            
        return orders

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._load(state)
        result: Dict[str, List[Order]] = {}
        
        hp_orders = self._hp(state)
        if hp_orders: result[HYDROGEL] = hp_orders
        
        vfe_orders = self._vfe(state)
        if vfe_orders: result[VFE] = vfe_orders
        
        vev_orders = self._vouchers(state)
        for vo in vev_orders:
            result.setdefault(vo.symbol, []).append(vo)
            
        return result, 0, self._save()
