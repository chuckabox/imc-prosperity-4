"""trader2.py - Hybrid R3 trader: IV scalping + gamma scalping + MM + EMA reversion.

Modules (priority order):
  1. VEV gamma scalping  : buy options when realised vol > implied (BS_fair > market_ask)
  2. IV scalping (parabolic): trade strikes with NEGATIVE IV-deviation autocorr only
  3. HYDROGEL_PACK MM    : mean-revert around stationary mean
  4. VFE EMA reversion   : small fixed-threshold position
  5. Delta hedging       : net VEV delta hedged via VFE
  6. Cross-strike No-Arb : enforce C(K1) - C(K2) <= K2 - K1

Plug-in: override class attributes via Trader.apply_params(dict) before instantiation.

Train: days 0+1. Day 2 = LOCKED validation only.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState


# ---------------- Black-Scholes ----------------
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1)


def implied_vol(price: float, S: float, K: float, T: float,
                lo: float = 1e-4, hi: float = 2.0, n: int = 60) -> float | None:
    intrinsic = max(0.0, S - K)
    if price <= intrinsic + 1e-6 or price >= S:
        return None
    for _ in range(n):
        mid = 0.5 * (lo + hi)
        if bs_call(S, K, T, mid) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-5:
            break
    return 0.5 * (lo + hi)


# ---------------- Constants ----------------
HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]
TS_PER_DAY = 1_000_000
TOTAL_DAYS = 8


def _best_bid_ask(od: OrderDepth) -> Tuple[int | None, int | None]:
    bid = max(od.buy_orders.keys()) if od.buy_orders else None
    ask = min(od.sell_orders.keys()) if od.sell_orders else None
    return bid, ask


def _mid(od: OrderDepth) -> float | None:
    b, a = _best_bid_ask(od)
    if b is None or a is None:
        return None
    return 0.5 * (b + a)


class Trader:
    # ---- module enables (defaults from ablation: VFE rev hurts) ----
    ENABLE_HYDROGEL = True
    ENABLE_VFE_REVERSION = False  # weak signal (-30k in ablation)
    ENABLE_VEV_GAMMA = True
    ENABLE_IV_SCALP = False       # overfits / positive AC
    ENABLE_HEDGE = True
    ENABLE_CROSS_ARBITRAGE = True

    # ---- limits ----
    LIMITS = {HYDROGEL: 80, VFE: 80, **{s: 60 for s in VEV_SYMBOLS}}

    # ---- HYDROGEL MM ----
    HP_ANCHOR = 9991.0
    HP_EWMA_ALPHA = 0.20
    HP_TAKE_EDGE = 2
    HP_QUOTE_FRONT = 20
    HP_QUOTE_SECOND = 12
    HP_SKEW_SOFT = 25
    HP_SKEW_HARD = 50
    HP_FLATTEN = 70

    # ---- VFE EMA mean reversion ----
    VFE_EMA_SPAN = 200
    VFE_DEV_THRESHOLD = 5         # log-price diff vs ema (in price units)
    VFE_REV_SIZE = 20             # max position from reversion alone

    # ---- VEV gamma + IV scalping ----
    VEV_SIGMA_MODEL = 0.014       # optimized (stage 1)
    VEV_PRIMARY_STRIKES = [5100, 5200, 5300, 5400]  # ATM band
    VEV_SECONDARY_STRIKES = [5000, 5500]
    VEV_GAMMA_EDGE_REQ = 1.5      # optimized
    VEV_GAMMA_SELL_EDGE = 1.5
    VEV_PER_STRIKE_CAP = 40
    VEV_TAKE_SIZE = 30            # optimized

    # IV scalp: only fire on strikes confirmed mean-reverting in IV-dev
    # (from analysis: K=4000 had AC=-0.275; rest positive). Use price-edge sign rule instead.
    IV_PRICE_EDGE_TRIGGER = 2.0   # |market - parabolic_fair| in XIRECs
    IV_SCALP_SIZE = 5

    # ---- delta hedge ----
    HEDGE_DEAD_BAND = 8
    HEDGE_MAX_PER_TICK = 20
    HEDGE_EVERY_N = 2

    # ---------- plug-in API ----------
    @classmethod
    def apply_params(cls, params: Dict) -> None:
        for k, v in params.items():
            if hasattr(cls, k):
                setattr(cls, k, v)

    @classmethod
    def get_params(cls) -> Dict:
        out = {}
        for k in dir(cls):
            if k.startswith("_") or k.isupper() is False:
                continue
            v = getattr(cls, k)
            if isinstance(v, (int, float, bool, str, list, dict)):
                out[k] = v
        return out

    # ---------- state ----------
    def __init__(self) -> None:
        self.tick = 0
        self.hp_ewma: float | None = None
        self.vfe_ema: float | None = None
        self.vfe_history: List[float] = []  # for parabolic IV fit context

    # ---------- helpers ----------
    def _serialise(self) -> str:
        return json.dumps({
            "tick": self.tick,
            "hp_ewma": self.hp_ewma,
            "vfe_ema": self.vfe_ema,
        })

    def _restore(self, td: str) -> None:
        if not td:
            return
        try:
            d = json.loads(td)
            self.tick = int(d.get("tick", 0))
            self.hp_ewma = d.get("hp_ewma")
            self.vfe_ema = d.get("vfe_ema")
        except Exception:
            pass

    # ---------- module 1: HYDROGEL MM ----------
    def _hydrogel(self, state: TradingState) -> List[Order]:
        sym = HYDROGEL
        if sym not in state.order_depths:
            return []
        od = state.order_depths[sym]
        m = _mid(od)
        if m is None:
            return []
        if self.hp_ewma is None:
            self.hp_ewma = m
        self.hp_ewma = self.HP_EWMA_ALPHA * m + (1 - self.HP_EWMA_ALPHA) * self.hp_ewma
        fair = 0.6 * self.hp_ewma + 0.4 * self.HP_ANCHOR
        pos = state.position.get(sym, 0)
        lim = self.LIMITS[sym]

        orders: List[Order] = []

        # 1) take aggressive edges
        b, a = _best_bid_ask(od)
        if a is not None and a <= fair - self.HP_TAKE_EDGE:
            qty = min(-od.sell_orders[a], lim - pos)
            if qty > 0:
                orders.append(Order(sym, a, qty))
                pos += qty
        if b is not None and b >= fair + self.HP_TAKE_EDGE:
            qty = min(od.buy_orders[b], lim + pos)
            if qty > 0:
                orders.append(Order(sym, b, -qty))
                pos -= qty

        # 2) skew quotes by inventory
        skew = 0
        if abs(pos) > self.HP_SKEW_HARD:
            skew = -2 if pos > 0 else 2
        elif abs(pos) > self.HP_SKEW_SOFT:
            skew = -1 if pos > 0 else 1

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
            orders.append(Order(sym, bid_px, min(front, max_buy)))
            if second > 0 and max_buy - front > 0:
                orders.append(Order(sym, bid_px - 2, min(second, max_buy - front)))
        if max_sell > 0:
            orders.append(Order(sym, ask_px, -min(front, max_sell)))
            if second > 0 and max_sell - front > 0:
                orders.append(Order(sym, ask_px + 2, -min(second, max_sell - front)))

        return orders

    # ---------- module 2: VFE EMA mean reversion ----------
    def _vfe_reversion(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        od = state.order_depths[VFE]
        m = _mid(od)
        if m is None:
            return []
        if self.vfe_ema is None:
            self.vfe_ema = m
        alpha = 2.0 / (self.VFE_EMA_SPAN + 1)
        self.vfe_ema = alpha * m + (1 - alpha) * self.vfe_ema
        dev = m - self.vfe_ema
        pos = state.position.get(VFE, 0)
        target = 0
        if dev > self.VFE_DEV_THRESHOLD:
            target = -self.VFE_REV_SIZE
        elif dev < -self.VFE_DEV_THRESHOLD:
            target = self.VFE_REV_SIZE
        delta = target - pos
        if abs(delta) < 3:
            return []
        b, a = _best_bid_ask(od)
        orders: List[Order] = []
        if delta > 0 and a is not None:
            orders.append(Order(VFE, a, min(delta, 10)))
        elif delta < 0 and b is not None:
            orders.append(Order(VFE, b, max(delta, -10)))
        return orders

    # ---------- module 3+4: VEV gamma + IV scalp ----------
    def _vev_logic(self, state: TradingState) -> Tuple[List[Order], float]:
        if VFE not in state.order_depths:
            return [], 0.0
        S = _mid(state.order_depths[VFE])
        if S is None:
            return [], 0.0
        # TTE in days
        # day index inferred from timestamp (roundtrip)
        day = int(state.timestamp // TS_PER_DAY)
        ts_in_day = state.timestamp % TS_PER_DAY
        TTE = (TOTAL_DAYS - day) - ts_in_day / TS_PER_DAY
        if TTE <= 0:
            return [], 0.0

        orders: List[Order] = []
        portfolio_delta = 0.0

        # snapshot fair IVs for parabolic fit (IV scalping)
        iv_points: List[Tuple[float, float, int, float]] = []  # (mny, iv, K, mid)
        if self.ENABLE_IV_SCALP:
            for K in self.VEV_PRIMARY_STRIKES + self.VEV_SECONDARY_STRIKES:
                sym = f"VEV_{K}"
                if sym not in state.order_depths:
                    continue
                m = _mid(state.order_depths[sym])
                if m is None or m <= 0:
                    continue
                iv = implied_vol(m, S, K, TTE)
                if iv is None:
                    continue
                iv_points.append((math.log(K / S), iv, K, m))

        # parabolic fit fair IV (need >= 4 points)
        fair_iv_by_K: Dict[int, float] = {}
        if self.ENABLE_IV_SCALP and len(iv_points) >= 4:
            xs = [p[0] for p in iv_points]
            ys = [p[1] for p in iv_points]
            try:
                # solve normal equations for y = a*x^2 + b*x + c
                n = len(xs)
                sx = sum(xs); sx2 = sum(x*x for x in xs); sx3 = sum(x**3 for x in xs); sx4 = sum(x**4 for x in xs)
                sy = sum(ys); sxy = sum(x*y for x, y in zip(xs, ys)); sx2y = sum(x*x*y for x, y in zip(xs, ys))
                A = [[sx4, sx3, sx2], [sx3, sx2, sx], [sx2, sx, n]]
                b_v = [sx2y, sxy, sy]
                coefs = _solve_3x3(A, b_v)
                if coefs is not None:
                    a, b, c = coefs
                    for mny, _, K, _ in iv_points:
                        fair_iv_by_K[K] = a*mny*mny + b*mny + c
            except Exception:
                pass

        active = self.VEV_PRIMARY_STRIKES + self.VEV_SECONDARY_STRIKES
        for K in active:
            sym = f"VEV_{K}"
            if sym not in state.order_depths:
                continue
            od = state.order_depths[sym]
            best_bid, best_ask = _best_bid_ask(od)
            pos = state.position.get(sym, 0)
            cap = self.VEV_PER_STRIKE_CAP
            lim = self.LIMITS[sym]

            # Gamma fair (flat sigma model)
            fair_gamma = bs_call(S, K, TTE, self.VEV_SIGMA_MODEL)
            delta = bs_delta(S, K, TTE, self.VEV_SIGMA_MODEL)

            # IV-scalp fair (parabolic)
            fair_iv = None
            if K in fair_iv_by_K:
                fair_iv = bs_call(S, K, TTE, fair_iv_by_K[K])

            # buy logic
            if self.ENABLE_VEV_GAMMA and best_ask is not None:
                edge = fair_gamma - best_ask
                if edge >= self.VEV_GAMMA_EDGE_REQ and pos < cap:
                    qty = min(self.VEV_TAKE_SIZE, cap - pos, lim - pos, -od.sell_orders[best_ask])
                    if qty > 0:
                        orders.append(Order(sym, best_ask, qty))
                        pos += qty

            if self.ENABLE_IV_SCALP and fair_iv is not None and best_ask is not None:
                iv_edge = fair_iv - best_ask
                if iv_edge >= self.IV_PRICE_EDGE_TRIGGER and pos < cap:
                    qty = min(self.IV_SCALP_SIZE, cap - pos, lim - pos, -od.sell_orders[best_ask])
                    if qty > 0:
                        orders.append(Order(sym, best_ask, qty))
                        pos += qty

            # sell logic
            if self.ENABLE_VEV_GAMMA and best_bid is not None:
                edge = best_bid - fair_gamma
                if edge >= self.VEV_GAMMA_SELL_EDGE and pos > -cap:
                    qty = min(self.VEV_TAKE_SIZE, cap + pos, lim + pos, od.buy_orders[best_bid])
                    if qty > 0:
                        orders.append(Order(sym, best_bid, -qty))
                        pos -= qty

            if self.ENABLE_IV_SCALP and fair_iv is not None and best_bid is not None:
                iv_edge = best_bid - fair_iv
                if iv_edge >= self.IV_PRICE_EDGE_TRIGGER and pos > -cap:
                    qty = min(self.IV_SCALP_SIZE, cap + pos, lim + pos, od.buy_orders[best_bid])
                    if qty > 0:
                        orders.append(Order(sym, best_bid, -qty))
                        pos -= qty

            portfolio_delta += pos * delta

        return orders, portfolio_delta

    # ---------- module 5: delta hedge VFE ----------
    def _hedge(self, state: TradingState, portfolio_delta: float, prior_orders: List[Order]) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        od = state.order_depths[VFE]
        b, a = _best_bid_ask(od)
        pos = state.position.get(VFE, 0)
        # account for VFE orders already queued (reversion)
        net_pending = sum(o.quantity for o in prior_orders if o.symbol == VFE)
        target = -int(round(portfolio_delta))
        delta = target - pos - net_pending
        if abs(delta) < self.HEDGE_DEAD_BAND:
            return []
        delta = max(min(delta, self.HEDGE_MAX_PER_TICK), -self.HEDGE_MAX_PER_TICK)
        lim = self.LIMITS[VFE]
        max_buy = lim - pos - net_pending
        max_sell = lim + pos + net_pending
        orders: List[Order] = []
        if delta > 0 and a is not None:
            qty = min(delta, max_buy)
            if qty > 0:
                orders.append(Order(VFE, a, qty))
        elif delta < 0 and b is not None:
            qty = min(-delta, max_sell)
            if qty > 0:
                orders.append(Order(VFE, b, -qty))
        return orders

    # ---------- module 6: Cross-strike No-Arb ----------
    def _cross_arbitrage(self, state: TradingState, prior_orders: List[Order]) -> List[Order]:
        strikes = sorted(VEV_STRIKES)
        orders: List[Order] = []
        # local copy of positions to track across pairs in one tick
        temp_pos = {s: state.position.get(s, 0) for s in VEV_SYMBOLS}
        # account for VEV orders already placed in this tick
        for o in prior_orders:
            if o.symbol in temp_pos:
                temp_pos[o.symbol] += o.quantity
        
        for i in range(len(strikes)):
            for j in range(i + 1, len(strikes)):
                K1, K2 = strikes[i], strikes[j]
                sym1, sym2 = f"VEV_{K1}", f"VEV_{K2}"
                if sym1 not in state.order_depths or sym2 not in state.order_depths:
                    continue
                od1, od2 = state.order_depths[sym1], state.order_depths[sym2]
                b1, a1 = _best_bid_ask(od1)
                b2, a2 = _best_bid_ask(od2)
                if b1 is None or a1 is None or b2 is None or a2 is None:
                    continue

                # Case 1: Ask(K1) < Bid(K2) -> Buy K1, Sell K2 (Vertical Spread for credit/zero cost)
                if a1 < b2:
                    qty = min(-od1.sell_orders[a1], od2.buy_orders[b2])
                    qty = min(qty, self.LIMITS[sym1] - temp_pos[sym1], self.LIMITS[sym2] + temp_pos[sym2])
                    if qty > 0:
                        orders.extend([Order(sym1, a1, qty), Order(sym2, b2, -qty)])
                        temp_pos[sym1] += qty
                        temp_pos[sym2] -= qty

                # Case 2: Bid(K1) - Ask(K2) > K2 - K1 -> Sell K1, Buy K2 (Risk-free profit > max loss)
                if b1 - a2 > (K2 - K1):
                    qty = min(od1.buy_orders[b1], -od2.sell_orders[a2])
                    qty = min(qty, self.LIMITS[sym1] + temp_pos[sym1], self.LIMITS[sym2] - temp_pos[sym2])
                    if qty > 0:
                        orders.extend([Order(sym1, b1, -qty), Order(sym2, a2, qty)])
                        temp_pos[sym1] -= qty
                        temp_pos[sym2] += qty
        return orders

    # ---------- main entry ----------
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._restore(state.traderData)
        self.tick += 1

        result: Dict[str, List[Order]] = {}
        all_orders: List[Order] = []

        if self.ENABLE_HYDROGEL:
            o = self._hydrogel(state)
            if o:
                result[HYDROGEL] = o
                all_orders.extend(o)

        if self.ENABLE_VFE_REVERSION:
            o = self._vfe_reversion(state)
            if o:
                result.setdefault(VFE, []).extend(o)
                all_orders.extend(o)

        portfolio_delta = 0.0
        if self.ENABLE_VEV_GAMMA or self.ENABLE_IV_SCALP:
            vev_orders, portfolio_delta = self._vev_logic(state)
            for o in vev_orders:
                result.setdefault(o.symbol, []).append(o)
            all_orders.extend(vev_orders)

        if self.ENABLE_HEDGE and (self.tick % self.HEDGE_EVERY_N == 0):
            o = self._hedge(state, portfolio_delta, all_orders)
            if o:
                result.setdefault(VFE, []).extend(o)

        if self.ENABLE_CROSS_ARBITRAGE:
            o = self._cross_arbitrage(state, all_orders)
            if o:
                for ord in o:
                    result.setdefault(ord.symbol, []).append(ord)
                all_orders.extend(o)

        return result, 0, self._serialise()


def _solve_3x3(A, b):
    """Solve 3x3 linear system. Return None if singular."""
    a11, a12, a13 = A[0]
    a21, a22, a23 = A[1]
    a31, a32, a33 = A[2]
    det = (a11 * (a22 * a33 - a23 * a32)
           - a12 * (a21 * a33 - a23 * a31)
           + a13 * (a21 * a32 - a22 * a31))
    if abs(det) < 1e-12:
        return None
    inv_det = 1.0 / det
    x1 = (b[0] * (a22 * a33 - a23 * a32) - a12 * (b[1] * a33 - a23 * b[2]) + a13 * (b[1] * a32 - a22 * b[2])) * inv_det
    x2 = (a11 * (b[1] * a33 - a23 * b[2]) - b[0] * (a21 * a33 - a23 * a31) + a13 * (a21 * b[2] - b[1] * a31)) * inv_det
    x3 = (a11 * (a22 * b[2] - b[1] * a32) - a12 * (a21 * b[2] - b[1] * a31) + b[0] * (a21 * a32 - a22 * a31)) * inv_det
    return (x1, x2, x3)
