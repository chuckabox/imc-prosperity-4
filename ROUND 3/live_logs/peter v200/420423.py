"""trader200.py - Optimized "Flipped" Strategy.
- HYDROGEL (Aggressive PnL): Lead-Lag Alpha + Pennying Dominance + High Volume.
- VELVETFRUIT (Stable MM): Volatility-adjusted spreads + Defensive skew + Trend protection.
- VEV (Options): Parabolic Smile-Fair MM + ITM intrinsic capture.
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
    if T <= 1e-10 or sigma <= 1e-10: return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)

def iv_solve(price: float, S: float, K: float, T: float) -> Optional[float]:
    intr = max(0.0, S - K)
    if price <= intr + 1e-6 or price >= S: return None
    lo, hi = 1e-4, 2.0
    for _ in range(32):
        mid = 0.5 * (lo + hi)
        if bs_call(S, K, T, mid) > price: hi = mid
        else: lo = mid
    return 0.5 * (lo + hi)

def _solve_3x3(A, b):
    a11, a12, a13 = A[0]; a21, a22, a23 = A[1]; a31, a32, a33 = A[2]
    det = (a11*(a22*a33 - a23*a32) - a12*(a21*a33 - a23*a31) + a13*(a21*a32 - a22*a31))
    if abs(det) < 1e-12: return None
    inv = 1.0 / det
    x1 = (b[0]*(a22*a33 - a23*a32) - a12*(b[1]*a33 - a23*b[2]) + a13*(b[1]*a32 - a22*b[2])) * inv
    x2 = (a11*(b[1]*a33 - a23*b[2]) - b[0]*(a21*a33 - a23*a31) + a13*(a21*b[2] - b[1]*a31)) * inv
    x3 = (a11*(a22*b[2] - b[1]*a32) - a12*(a21*b[2] - b[1]*a31) + b[0]*(a21*a32 - a22*b[2])) * inv
    return (x1, x2, x3)

# ---------------- Constants ----------------
HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]
TS_PER_DAY = 1_000_000

class Trader:
    LIMITS = {HYDROGEL: 200, VFE: 200, **{s: 100 for s in VEV_SYMBOLS}}

    # HP Parameters (MAX AGGRESSION)
    HP_ANCHOR = 9991.0
    HP_BLEND = 0.55                # More sensitive to market mid
    HP_EWMA_ALPHA = 0.25
    HP_TAKE_EDGE = 1               # Highly aggressive taking
    HP_QUOTE_SIZE = 80             # Maximize spread capture volume
    HP_LEAD_BETA = 1.9             # VFE Correlation Lead

    # VFE Parameters (MAX STABILITY)
    VFE_EWMA_ALPHA = 0.20          # Stable EMA
    VFE_TAKE_EDGE = 3              # Defensive taking (avoid toxic flow)
    VFE_VOL_ALPHA = 0.15           # Measure price volatility
    VFE_OBI_THR = 0.15
    VFE_QUOTE_SIZE = 25            # Smaller, safer chunks

    # VEV Parameters
    VEV_TTE_START = 8.0
    VEV_FIT_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
    VEV_TAKE_EDGE = 1.5
    VEV_CAP = 60

    def __init__(self) -> None:
        self.history: Dict = {}

    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try: self.history = json.loads(state.traderData)
            except: self.history = {}
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("vfe_vol", 0.0)
        self.history.setdefault("vfe_mids", [])

    def _save(self) -> str:
        h = dict(self.history)
        if "vfe_mids" in h and len(h["vfe_mids"]) > 500: h["vfe_mids"] = h["vfe_mids"][-500:]
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

    # ---------- HP Module (AGGRESSIVE PNL) ----------
    def _hp(self, state: TradingState, vfe_lead: float) -> List[Order]:
        if HYDROGEL not in state.order_depths: return []
        od = state.order_depths[HYDROGEL]
        m = self._mid(od); bb, ba, _, _ = self._top(od)
        if m is None: return []
        
        prev = self.history.get("hp_ewma")
        ewma = m if prev is None else self.HP_EWMA_ALPHA * m + (1 - self.HP_EWMA_ALPHA) * prev
        self.history["hp_ewma"] = ewma
        
        # Lead-Lag adjusted fair
        fair = self.HP_BLEND * ewma + (1 - self.HP_BLEND) * self.HP_ANCHOR
        fair += vfe_lead * self.HP_LEAD_BETA
        
        pos = state.position.get(HYDROGEL, 0); lim = self.LIMITS[HYDROGEL]
        orders: List[Order] = []
        
        # Aggressive Pennying MM
        q_bid = int(round(fair - 1.0)); q_ask = int(round(fair + 1.0))
        if bb is not None: q_bid = max(q_bid, bb + 1)
        if ba is not None: q_ask = min(q_ask, ba - 1)
        
        # Inventory skew only at extremes
        if pos > lim * 0.7: q_bid -= 1; q_ask -= 1
        elif pos < -lim * 0.7: q_bid += 1; q_ask += 1
        if q_bid >= q_ask: q_bid = q_ask - 1

        # Multi-level Aggression
        if lim - pos > 0:
            sz = min(self.HP_QUOTE_SIZE, lim - pos)
            orders.append(Order(HYDROGEL, q_bid, sz))
            if lim - pos > sz: orders.append(Order(HYDROGEL, q_bid - 1, min(20, lim - pos - sz)))
        if lim + pos > 0:
            sz = min(self.HP_QUOTE_SIZE, lim + pos)
            orders.append(Order(HYDROGEL, q_ask, -sz))
            if lim + pos > sz: orders.append(Order(HYDROGEL, q_ask + 1, -min(20, lim + pos - sz)))
            
        # Take orders
        if ba and ba <= fair - self.HP_TAKE_EDGE: orders.append(Order(HYDROGEL, ba, min(lim-pos, -od.sell_orders[ba])))
        if bb and bb >= fair + self.HP_TAKE_EDGE: orders.append(Order(HYDROGEL, bb, -min(lim+pos, od.buy_orders[bb])))
        
        return orders

    # ---------- VFE Module (STABLE/DEFENSIVE) ----------
    def _vfe(self, state: TradingState) -> Tuple[List[Order], float]:
        if VFE not in state.order_depths: return [], 0.0
        od = state.order_depths[VFE]
        m = self._mid(od); bb, ba, bv, av = self._top(od)
        if m is None: return [], 0.0
        
        prev = self.history.get("vfe_ewma")
        vfe_lead = m - (prev or m)
        ewma = m if prev is None else self.VFE_EWMA_ALPHA * m + (1 - self.VFE_EWMA_ALPHA) * prev
        self.history["vfe_ewma"] = ewma
        
        # Price Speed (Vol) Protection
        diff = abs(m - (prev or m))
        vol = (1-self.VFE_VOL_ALPHA)*self.history["vfe_vol"] + self.VFE_VOL_ALPHA*diff
        self.history["vfe_vol"] = vol
        
        pos = state.position.get(VFE, 0); lim = self.LIMITS[VFE]
        fair = ewma
        orders: List[Order] = []
        
        # Defensive Taking
        if ba and ba <= fair - self.VFE_TAKE_EDGE and pos < lim:
            orders.append(Order(VFE, ba, min(lim-pos, -od.sell_orders[ba])))
        if bb and bb >= fair + self.VFE_TAKE_EDGE and pos > -lim:
            orders.append(Order(VFE, bb, -min(lim+pos, od.buy_orders[bb])))

        # Volatility-Adjusted Spreads
        spread = 2 + int(vol * 3) # Widen if VFE is jumping
        skew = int(round(4 * (pos / lim)))
        
        q_bid = int(round(fair - spread - skew))
        q_ask = int(round(fair + spread - skew))
        if q_bid >= q_ask: q_bid = q_ask - 1
        
        if lim - pos > 0: orders.append(Order(VFE, q_bid, min(self.VFE_QUOTE_SIZE, lim - pos)))
        if lim + pos > 0: orders.append(Order(VFE, q_ask, -min(self.VFE_QUOTE_SIZE, lim + pos)))
        return orders, vfe_lead

    # ---------- VEV Module ----------
    def _vouchers(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths: return []
        S = self._mid(state.order_depths[VFE])
        if S is None: return []
        T = max(0.5, self.VEV_TTE_START - state.timestamp / TS_PER_DAY)

        all_iv = {}
        for K in self.VEV_FIT_STRIKES:
            sym = f"VEV_{K}"
            if sym not in state.order_depths: continue
            m = self._mid(state.order_depths[sym])
            if m and m > 0:
                iv = iv_solve(m, S, K, T)
                if iv: all_iv[K] = iv

        orders: List[Order] = []
        # ITM MM
        for K in [4000, 4500]:
            sym = f"VEV_{K}"; od = state.order_depths.get(sym)
            if not od: continue
            fair = max(S - K, 0); pos = state.position.get(sym, 0); lim = self.VEV_CAP
            bb, ba, _, _ = self._top(od)
            if ba and ba < fair: orders.append(Order(sym, ba, min(lim - pos, -od.sell_orders[ba])))
            if bb and bb > fair + 1: orders.append(Order(sym, bb, -min(lim + pos, od.buy_orders[bb])))
            if lim-pos > 0: orders.append(Order(sym, int(fair), min(20, lim-pos)))
            if lim+pos > 0: orders.append(Order(sym, int(fair+2), -min(20, lim+pos)))

        # Smile MM
        for K in self.VEV_FIT_STRIKES:
            sym = f"VEV_{K}"; od = state.order_depths.get(sym)
            if not od: continue
            fit_strikes = [k for k in self.VEV_FIT_STRIKES if k != K and k in all_iv]
            if len(fit_strikes) < 4: continue
            iv_pts = [(math.log(k/S), all_iv[k]) for k in fit_strikes]
            xs=[p[0] for p in iv_pts]; ys=[p[1] for p in iv_pts]; n=len(xs)
            sx=sum(xs); sx2=sum(x*x for x in xs); sx3=sum(x**3 for x in xs); sx4=sum(x**4 for x in xs)
            sy=sum(ys); sxy=sum(x*y for x,y in zip(xs,ys)); sx2y=sum(x*x*y for x,y in zip(xs,ys))
            coefs = _solve_3x3([[sx4, sx3, sx2], [sx3, sx2, sx], [sx2, sx, n]], [sx2y, sxy, sy])
            if not coefs: continue
            mny = math.log(K/S); fit_iv = coefs[0]*mny*mny + coefs[1]*mny + coefs[2]
            fair = bs_call(S, K, T, fit_iv); pos = state.position.get(sym, 0); lim = self.VEV_CAP
            bb, ba, _, _ = self._top(od)
            if ba and ba <= fair - self.VEV_TAKE_EDGE: orders.append(Order(sym, ba, min(30, lim-pos, -od.sell_orders[ba])))
            if bb and bb >= fair + self.VEV_TAKE_EDGE: orders.append(Order(sym, bb, -min(30, lim+pos, od.buy_orders[bb])))
            q_bid, q_ask = int(round(fair-1)), int(round(fair+1))
            if bb: q_bid = min(q_bid, bb+1)
            if ba: q_ask = max(q_ask, ba-1)
            if q_bid >= q_ask: q_bid = q_ask - 1
            if lim-pos > 0: orders.append(Order(sym, q_bid, min(20, lim-pos)))
            if lim+pos > 0: orders.append(Order(sym, q_ask, -min(20, lim+pos)))
        return orders

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._load(state)
        result: Dict[str, List[Order]] = {}
        v, v_lead = self._vfe(state)
        h = self._hp(state, v_lead)
        o = self._vouchers(state)
        if h: result[HYDROGEL] = h
        if v: result[VFE] = v
        for vo in o: result.setdefault(vo.symbol, []).append(vo)
        return result, 0, self._save()