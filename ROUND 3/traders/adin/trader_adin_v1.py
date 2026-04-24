"""trader_adin_v1.py — Frankfurt-Hedgehogs-inspired hybrid for Round 3.

Built on top of trader_ken_v18 (HYDROGEL_PACK guarded maker still wins),
upgraded with Frankfurt-style options machinery:

  1. Black-Scholes fair values for the VEV chain (replaces v18's static
     premium EMA).
  2. Volatility-smile fit (parabola in log-moneyness / sqrt(T)) every tick.
     Smoothed IV per strike is used to drive an IV-scalping signal — if
     market mid deviates from BS(smoothed IV), take it.
  3. Hard fair-value floor of sigma_model = 1.75%/day (between market IV
     ~1.26%/day and realised RV ~2.15%/day from the data capsule).  Even
     if the smile fit fails, options are still treated as systematically
     under-priced, so we lean long the chain.
  4. Mean-reversion overlay on VFE (the underlying) and on VEV_5000 (the
     deepest liquid ITM call, delta ~ 0.8) — Frankfurt's "hedge against
     bad luck" against a strong mean-reverting regime.
  5. VFE delta-hedge: target -portfolio_delta from the VEV book with a
     ±10-unit dead-band to avoid churn.

Calibration anchors come from ROUND 3/data_capsule day 0 + day 1
(prices_round_3_day_0.csv, prices_round_3_day_1.csv) — see ROUND_3_ANALYSIS.md.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]


# ---------------------------------------------------------------------------
# Black-Scholes helpers (zero rates, European call). Time in days.
# ---------------------------------------------------------------------------
_SQRT_2PI_INV = 1.0 / math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return _SQRT_2PI_INV * math.exp(-0.5 * x * x)


def _bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def _bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0:
        return 1.0 if S > K else 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    return _norm_cdf(d1)


def _bs_vega(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0:
        return 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    return S * _norm_pdf(d1) * sqrt_T


def _implied_vol(S: float, K: float, T: float, price: float,
                 init: float = 0.018, max_iter: int = 25) -> Optional[float]:
    """Newton-Raphson IV solver. sigma is per-day. Returns None on failure."""
    if T <= 0.0 or price <= 0.0:
        return None
    intrinsic = max(S - K, 0.0)
    if price <= intrinsic + 1e-3:
        return 0.001
    sigma = init
    for _ in range(max_iter):
        bs = _bs_call(S, K, T, sigma)
        diff = bs - price
        if abs(diff) < 1e-3:
            return sigma
        vega = _bs_vega(S, K, T, sigma)
        if vega < 1e-6:
            return None
        step = diff / vega
        # damp big steps
        if step > 0.05:
            step = 0.05
        elif step < -0.05:
            step = -0.05
        sigma = max(0.001, min(0.10, sigma - step))
    return sigma


def _fit_parabola(xs: List[float], ys: List[float]) -> Optional[Tuple[float, float, float]]:
    """Least-squares y = a*x^2 + b*x + c.  Needs >= 3 distinct x's."""
    n = len(xs)
    if n < 3:
        return None
    sx = sx2 = sx3 = sx4 = sy = sxy = sx2y = 0.0
    for x, y in zip(xs, ys):
        x2 = x * x
        sx += x
        sx2 += x2
        sx3 += x2 * x
        sx4 += x2 * x2
        sy += y
        sxy += x * y
        sx2y += x2 * y
    M = [
        [sx4, sx3, sx2],
        [sx3, sx2, sx],
        [sx2, sx,  float(n)],
    ]
    B = [sx2y, sxy, sy]
    det = (M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1])
           - M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0])
           + M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0]))
    if abs(det) < 1e-12:
        return None
    out = []
    for col in range(3):
        Mc = [row[:] for row in M]
        for i in range(3):
            Mc[i][col] = B[i]
        sub = (Mc[0][0] * (Mc[1][1] * Mc[2][2] - Mc[1][2] * Mc[2][1])
               - Mc[0][1] * (Mc[1][0] * Mc[2][2] - Mc[1][2] * Mc[2][0])
               + Mc[0][2] * (Mc[1][0] * Mc[2][1] - Mc[1][1] * Mc[2][0]))
        out.append(sub / det)
    return out[0], out[1], out[2]


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------
class Trader:
    # Module switches
    ENABLE_HYDROGEL = True
    ENABLE_VFE = True
    ENABLE_VEV = True
    ENABLE_SMILE = True
    ENABLE_VFE_MEANREV = True
    ENABLE_VEV5000_MEANREV = True
    ENABLE_DELTA_HEDGE = True

    # Time-to-expiry. Data day 0 starts with TTE = 8.0 (Round 3 capsule).
    # Adjust INITIAL_DAY for the live competition day this trader is run on.
    INITIAL_DAY = 0
    TTE_AT_DAY_0_START = 8.0
    DAY_LENGTH_TS = 1_000_000  # one Solvenarian day = 1M timestamp units

    # ---- HYDROGEL_PACK -----------------------------------------------------
    HP_LIMIT = 80
    HP_ANCHOR = 9993.0
    HP_EWMA_ALPHA = 0.20
    HP_TAKER_EDGE = 2.0
    HP_MAKER_EDGE = 2.0
    HP_TAKER_MAX = 20

    # ---- VELVETFRUIT_EXTRACT (underlying) ----------------------------------
    VFE_LIMIT = 80
    VFE_EWMA_ALPHA = 0.20             # fast EMA — fair-value tracker
    VFE_REV_EMA_ALPHA = 0.03          # slow EMA — mean-reversion baseline
    VFE_REV_THRESHOLD = 6.0           # ~0.4 stdev (stdev=15.6 from capsule)
    VFE_REV_MAX_POS = 25              # cap mean-rev exposure (leaves headroom for hedge)
    VFE_REV_SIZE = 12                 # size per mean-rev signal
    VFE_MAKER_EDGE = 2.0
    VFE_HEDGE_BAND = 10               # delta-hedge dead-band

    # ---- VEV options chain --------------------------------------------------
    SIGMA_MODEL = 0.0175              # baseline true vol/day; between 1.26% IV and 2.15% RV
    SIGMA_FLOOR = 0.013
    SIGMA_CEIL = 0.030
    VEV_TAKER_EDGE = 4.0              # take when |fair - market| > 4
    VEV_TAKER_MAX = 8
    VEV_MAKER_EDGE = 3.0
    VEV_MAX_POSITION: Dict[int, int] = {
        5000: 35,
        5100: 50,
        5200: 60,
        5300: 60,
        5400: 50,
        5500: 35,
    }
    VEV5000_REV_SIZE = 8              # extra mean-rev sleeve in deepest ITM call

    # ---------------------------------------------------------------------------
    def __init__(self) -> None:
        self.history: Dict = {}

    # ---- state persistence -------------------------------------------------
    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("vfe_rev_ema", None)
        self.history.setdefault("day_count", 0)
        self.history.setdefault("last_ts", -1)

    def _save_state(self) -> str:
        return json.dumps(self.history)

    # ---- utilities ---------------------------------------------------------
    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    def _tte(self, state: TradingState) -> float:
        last_ts = int(self.history.get("last_ts", -1))
        ts = int(state.timestamp)
        if last_ts >= 0 and ts < last_ts:
            self.history["day_count"] = int(self.history.get("day_count", 0)) + 1
        self.history["last_ts"] = ts

        day_idx = self.INITIAL_DAY + int(self.history["day_count"])
        elapsed_days = day_idx + ts / float(self.DAY_LENGTH_TS)
        tte = self.TTE_AT_DAY_0_START - elapsed_days
        return max(tte, 0.05)

    def _guarded_maker(
        self,
        symbol: str,
        depth: OrderDepth,
        pos: int,
        fair: float,
        limit: int,
        edge: float,
    ) -> List[Order]:
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []

        qbid = int(round(fair - edge))
        qask = int(round(fair + edge))

        # Never cross the book.
        if qbid >= ba:
            qbid = ba - 1
        if qask <= bb:
            qask = bb + 1
        if qbid >= qask:
            qbid = qask - 1

        out: List[Order] = []
        room_long = limit - pos
        room_short = limit + pos
        if room_long > 0 and qbid > 0:
            out.append(Order(symbol, qbid, room_long))
        if room_short > 0 and qask > 0:
            out.append(Order(symbol, qask, -room_short))
        return out

    # ---- HYDROGEL_PACK -----------------------------------------------------
    def _hydrogel_logic(self, state: TradingState) -> List[Order]:
        depth = state.order_depths.get(HYDROGEL)
        if depth is None:
            return []
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        prev = self.history.get("hp_ewma")
        ewma = mid if prev is None else (1 - self.HP_EWMA_ALPHA) * prev + self.HP_EWMA_ALPHA * mid
        self.history["hp_ewma"] = ewma
        fair = 0.6 * ewma + 0.4 * self.HP_ANCHOR

        pos = state.position.get(HYDROGEL, 0)
        lim = self.HP_LIMIT
        orders: List[Order] = []

        if ba <= fair - self.HP_TAKER_EDGE and pos < lim:
            sz = min(self.HP_TAKER_MAX, lim - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(HYDROGEL, ba, sz))
                pos += sz
        if bb >= fair + self.HP_TAKER_EDGE and pos > -lim:
            sz = min(self.HP_TAKER_MAX, lim + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(HYDROGEL, bb, -sz))
                pos -= sz

        orders.extend(self._guarded_maker(HYDROGEL, depth, pos, fair, lim, self.HP_MAKER_EDGE))
        return orders

    # ---- volatility smile --------------------------------------------------
    def _build_smile(
        self,
        S: float,
        T: float,
        depths: Dict[str, OrderDepth],
    ) -> Tuple[Dict[int, float], Optional[Tuple[float, float, float]]]:
        """Return (per-strike smoothed sigma, parabola coefs).
        Falls back to SIGMA_MODEL for any strike missing from the fit.
        """
        pts_x: List[float] = []
        pts_y: List[float] = []
        per_strike_iv: Dict[int, float] = {}

        for k in VEV_STRIKES:
            d = depths.get(f"VEV_{k}")
            if d is None:
                continue
            bb, ba = self._top(d)
            if bb is None or ba is None:
                continue
            mid = (bb + ba) / 2.0
            iv = _implied_vol(S, k, T, mid)
            if iv is None:
                continue
            if not (self.SIGMA_FLOOR * 0.5 < iv < self.SIGMA_CEIL * 1.5):
                continue
            per_strike_iv[k] = iv
            pts_x.append(math.log(k / S) / math.sqrt(T))
            pts_y.append(iv)

        coeffs = _fit_parabola(pts_x, pts_y) if self.ENABLE_SMILE else None

        smoothed: Dict[int, float] = {}
        for k in VEV_STRIKES:
            sigma_k: float
            if coeffs is not None:
                m = math.log(k / S) / math.sqrt(T)
                a, b, c = coeffs
                sigma_k = a * m * m + b * m + c
            elif k in per_strike_iv:
                sigma_k = per_strike_iv[k]
            else:
                sigma_k = self.SIGMA_MODEL
            smoothed[k] = max(self.SIGMA_FLOOR, min(self.SIGMA_CEIL, sigma_k))
        return smoothed, coeffs

    # ---- VFE underlying ----------------------------------------------------
    def _vfe_logic(
        self,
        state: TradingState,
        target_hedge: int,
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

        prev_rev = self.history.get("vfe_rev_ema")
        rev_ema = mid if prev_rev is None else (1 - self.VFE_REV_EMA_ALPHA) * prev_rev + self.VFE_REV_EMA_ALPHA * mid
        self.history["vfe_rev_ema"] = rev_ema

        fair = ewma
        pos = state.position.get(VFE, 0)
        lim = self.VFE_LIMIT
        orders: List[Order] = []

        # 1. Mean-reversion overlay around the slow EMA (Frankfurt's lightweight
        #    fixed-threshold model — no rolling-vol scaling).
        if self.ENABLE_VFE_MEANREV:
            dev = mid - rev_ema
            if dev <= -self.VFE_REV_THRESHOLD and pos < self.VFE_REV_MAX_POS:
                sz = min(self.VFE_REV_SIZE, self.VFE_REV_MAX_POS - pos, -depth.sell_orders[ba])
                if sz > 0:
                    orders.append(Order(VFE, ba, sz))
                    pos += sz
            elif dev >= self.VFE_REV_THRESHOLD and pos > -self.VFE_REV_MAX_POS:
                sz = min(self.VFE_REV_SIZE, self.VFE_REV_MAX_POS + pos, depth.buy_orders[bb])
                if sz > 0:
                    orders.append(Order(VFE, bb, -sz))
                    pos -= sz

        # 2. Delta-hedge against the VEV portfolio. Only nudge if outside the
        #    dead-band, and only with passive limit orders to avoid eating
        #    the spread.
        if self.ENABLE_DELTA_HEDGE:
            residual = target_hedge - pos
            if residual > self.VFE_HEDGE_BAND and pos < lim:
                sz = min(residual, lim - pos, -depth.sell_orders[ba])
                if sz > 0:
                    orders.append(Order(VFE, ba, sz))
                    pos += sz
            elif residual < -self.VFE_HEDGE_BAND and pos > -lim:
                sz = min(-residual, lim + pos, depth.buy_orders[bb])
                if sz > 0:
                    orders.append(Order(VFE, bb, -sz))
                    pos -= sz

        # 3. Passive market-make on remaining capacity.
        orders.extend(self._guarded_maker(VFE, depth, pos, fair, lim, self.VFE_MAKER_EDGE))
        return orders, mid

    # ---- VEV chain ---------------------------------------------------------
    def _vev_logic(
        self,
        state: TradingState,
        S: float,
        T: float,
    ) -> Tuple[List[Order], float]:
        """Returns (orders, target_hedge_for_VFE)."""
        smoothed_iv, _coeffs = self._build_smile(S, T, state.order_depths)
        orders: List[Order] = []
        portfolio_delta = 0.0

        for strike in VEV_STRIKES:
            sym = f"VEV_{strike}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            bb, ba = self._top(depth)
            if bb is None or ba is None:
                continue

            sigma_smile = smoothed_iv[strike]
            # Two-track fair: a smile-fitted "what the chain thinks" and a
            # model-vol "what the data tells us is true".  Use the higher of
            # the two on the long side and the lower on the short side, so we
            # only trade when both signals agree the option is mispriced
            # (margin of safety: the IV/RV mismatch is huge per the capsule).
            fair_smile = _bs_call(S, strike, T, sigma_smile)
            fair_model = _bs_call(S, strike, T, self.SIGMA_MODEL)
            fair_long = max(fair_smile, fair_model)   # buy threshold
            fair_short = min(fair_smile, fair_model)  # sell threshold
            mid_fair = 0.5 * (fair_long + fair_short)

            pos = state.position.get(sym, 0)
            cap = self.VEV_MAX_POSITION[strike]

            # Taker leg — only when both fairs say it's mispriced.
            if ba <= fair_long - self.VEV_TAKER_EDGE and pos < cap:
                sz = min(self.VEV_TAKER_MAX, cap - pos, -depth.sell_orders[ba])
                if sz > 0:
                    orders.append(Order(sym, ba, sz))
                    pos += sz
            if bb >= fair_short + self.VEV_TAKER_EDGE and pos > -cap:
                sz = min(self.VEV_TAKER_MAX, cap + pos, depth.buy_orders[bb])
                if sz > 0:
                    orders.append(Order(sym, bb, -sz))
                    pos -= sz

            # Mean-reversion sleeve in the deepest ITM call (delta ~ 0.8) —
            # acts as a "hedge against bad luck" if Volcanic-Rock-style mean
            # reversion materialises in the live days. Same signal as VFE.
            if (self.ENABLE_VEV5000_MEANREV
                    and strike == VEV_STRIKES[0]
                    and self.history.get("vfe_rev_ema") is not None):
                dev = S - float(self.history["vfe_rev_ema"])
                extra = self.VEV5000_REV_SIZE
                if dev <= -self.VFE_REV_THRESHOLD and pos < cap:
                    sz = min(extra, cap - pos, -depth.sell_orders[ba])
                    if sz > 0:
                        orders.append(Order(sym, ba, sz))
                        pos += sz
                elif dev >= self.VFE_REV_THRESHOLD and pos > -cap:
                    sz = min(extra, cap + pos, depth.buy_orders[bb])
                    if sz > 0:
                        orders.append(Order(sym, bb, -sz))
                        pos -= sz

            orders.extend(
                self._guarded_maker(sym, depth, pos, mid_fair, cap, self.VEV_MAKER_EDGE)
            )

            # Delta contribution from the (post-trade) position.
            delta = _bs_delta(S, strike, T, sigma_smile)
            portfolio_delta += pos * delta

        target_hedge = int(round(-portfolio_delta))
        return orders, float(target_hedge)

    # ---- main entrypoint ---------------------------------------------------
    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        if self.ENABLE_HYDROGEL:
            for o in self._hydrogel_logic(state):
                result.setdefault(o.symbol, []).append(o)

        # VEV must run first (uses VFE mid + sets target hedge).
        target_hedge = 0
        vfe_depth = state.order_depths.get(VFE)
        S: Optional[float] = None
        if vfe_depth is not None:
            bb, ba = self._top(vfe_depth)
            if bb is not None and ba is not None:
                S = (bb + ba) / 2.0

        if self.ENABLE_VEV and S is not None:
            T = self._tte(state)
            vev_orders, target_hedge = self._vev_logic(state, S, T)
            for o in vev_orders:
                result.setdefault(o.symbol, []).append(o)
        else:
            # still need to advance the day-count clock
            self._tte(state)

        if self.ENABLE_VFE:
            vfe_orders, _ = self._vfe_logic(state, int(round(target_hedge)))
            for o in vfe_orders:
                result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save_state()
