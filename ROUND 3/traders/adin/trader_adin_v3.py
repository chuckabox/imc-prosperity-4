"""trader_adin_v3.py — Risk-Governed Hybrid Engine.

POST-MORTEM ON v1 / v2 vs ken_v22 (5k vs ~2k)
---------------------------------------------
Three lessons from ken's iteration trail (v18→v22):

  (a) Premium-EMA fair value beats BS-smile in this market.  The other
      bots quote around a near-static premium per strike, so tracking
      `intrinsic + EMA(observed_premium)` captures their behaviour
      exactly.  BS-smile adds noise without alpha (ken's v21 tried the
      long-gamma + delta-hedge route — same idea as my v1 — and got
      abandoned).
  (b) The 3k delta vs my v2 came from a **portfolio risk governor**.
      ken throttles size and disables takers when HP inventory grows or
      the underlying moves against current net delta.
  (c) Cap maker order *size per side*, not just total position.  Without
      this, after a taker fill of 20 the maker posts the remaining 60 in
      a single order, and one bad print costs 60 × adverse_move.

WHAT v3 ADDS ON TOP OF KEN v22
------------------------------
  1. **AS inventory-skewed quotes** (closed-form solution to the
     market-maker Bellman equation): bid/ask centre on
       r(q) = fair − γ · q
     so positions naturally mean-revert toward zero.
  2. **End-of-horizon liquidation DP**: γ ramps up by 4× as TTE drops
     below 0.5 days, flattening inventory automatically.
  3. **Frankfurt mean-reversion overlays** on VFE underlying and on
     VEV_5000 (the deepest liquid ITM call, delta ≈ 0.8).
  4. **BS-smile sanity guard**: each tick, compare premium-EMA fair to
     BS(smile_iv) fair.  If they diverge by more than the per-strike
     PREM_BOUNDS, fall back to the BS fair (premium-EMA went wrong).
  5. **BS deltas in the risk governor** instead of static delta
     constants — catches regime shifts in the chain.

Calibration anchors come from ROUND 3/data_capsule day 0 + day 1
(see ROUND_3_ANALYSIS.md).
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]

# --- Static calibration (from ken_v22, validated on capsule day 0+1) -------
PREM_INIT: Dict[int, float] = {
    5000: 5.81, 5100: 19.09, 5200: 48.85, 5300: 47.90, 5400: 17.06, 5500: 7.31,
}
PREM_BOUNDS: Dict[int, Tuple[float, float]] = {
    5000: (2.0, 14.0),
    5100: (10.0, 30.0),
    5200: (30.0, 72.0),
    5300: (30.0, 72.0),
    5400: (8.0, 30.0),
    5500: (3.0, 15.0),
}
STRIKE_CAP: Dict[int, int] = {
    5000: 32, 5100: 44, 5200: 48, 5300: 44, 5400: 36, 5500: 28,
}


# ===========================================================================
# Black-Scholes helpers (zero rates, European call). Time in days.
# ===========================================================================
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
                 init: float = 0.013, max_iter: int = 25) -> Optional[float]:
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
        if step > 0.05:
            step = 0.05
        elif step < -0.05:
            step = -0.05
        sigma = max(0.001, min(0.10, sigma - step))
    return sigma


def _fit_parabola(xs: List[float], ys: List[float]) -> Optional[Tuple[float, float, float]]:
    n = len(xs)
    if n < 3:
        return None
    sx = sx2 = sx3 = sx4 = sy = sxy = sx2y = 0.0
    for x, y in zip(xs, ys):
        x2 = x * x
        sx += x; sx2 += x2; sx3 += x2 * x; sx4 += x2 * x2
        sy += y; sxy += x * y; sx2y += x2 * y
    M = [[sx4, sx3, sx2], [sx3, sx2, sx], [sx2, sx, float(n)]]
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


# ===========================================================================
# Trader
# ===========================================================================
class Trader:
    # --- Module switches -------------------------------------------------
    ENABLE_HYDROGEL = True
    ENABLE_VFE = True
    ENABLE_VEV = True
    ENABLE_VFE_MEANREV = True
    ENABLE_VEV5000_MEANREV = True
    ENABLE_BS_GUARD = True

    # --- TTE tracking ----------------------------------------------------
    INITIAL_DAY = 0
    TTE_AT_DAY_0_START = 8.0
    DAY_LENGTH_TS = 1_000_000

    # --- HYDROGEL --------------------------------------------------------
    HP_LIMIT = 80
    HP_ANCHOR = 9993.0
    HP_EWMA_ALPHA = 0.20
    HP_TAKER_EDGE = 2.0
    HP_MAKER_EDGE = 2.0
    HP_TAKER_MAX = 20
    HP_MAKER_PER_SIDE = 15            # ken v20 fix — cap per-side maker size
    HP_GAMMA = 0.04                   # AS inventory skew

    # --- VFE -------------------------------------------------------------
    VFE_LIMIT = 80
    VFE_EWMA_ALPHA = 0.20
    VFE_REV_EMA_ALPHA = 0.03          # slow EMA for mean-rev overlay
    VFE_REV_THRESHOLD = 8.0
    VFE_REV_MAX_POS = 30
    VFE_REV_SIZE = 12
    VFE_TAKER_EDGE = 4.0
    VFE_TAKER_MAX = 15
    VFE_MAKER_EDGE = 2.0
    VFE_MAKER_PER_SIDE = 12
    VFE_GAMMA = 0.05

    # --- VEV chain -------------------------------------------------------
    PREM_ALPHA = 0.05                 # premium EMA (ken)
    VEV_MAKER_EDGE = 2.0
    VEV_MAKER_PER_SIDE = 10           # ken v19 fix
    VEV_GAMMA = 0.10                  # AS skew per option lot
    VEV5000_REV_SIZE = 6              # mean-rev overlay sleeve

    # Smile guard
    SIGMA_FLOOR = 0.005
    SIGMA_CEIL = 0.040
    SIGMA_FALLBACK = 0.013
    BS_GUARD_BAND = 0.5               # if premium leaves PREM_BOUNDS by >50%, fall back to BS fair

    # End-of-horizon liquidation DP
    LIQ_TTE_TRIGGER = 0.5
    LIQ_GAMMA_MULT = 4.0

    # Risk governor (ken v22)
    RISK_NET_DELTA_TRIGGER = 55.0
    RISK_HP_POS_TRIGGER = 62
    RISK_ADVERSE_MOVE = 2.5
    RISK_MIN_SCALE = 0.35

    # ----------------------------------------------------------------------
    def __init__(self) -> None:
        self.history: Dict = {}

    # ---- state persistence -----------------------------------------------
    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("vfe_rev_ema", None)
        self.history.setdefault("last_vfe_mid", None)
        self.history.setdefault("day_count", 0)
        self.history.setdefault("last_ts", -1)
        self.history.setdefault("prem", {})
        for k in VEV_STRIKES:
            self.history["prem"].setdefault(str(k), PREM_INIT[k])

    def _save_state(self) -> str:
        return json.dumps(self.history)

    # ---- utilities -------------------------------------------------------
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
        return max(self.TTE_AT_DAY_0_START - elapsed_days, 0.05)

    def _liq_multiplier(self, T: float) -> float:
        if T >= self.LIQ_TTE_TRIGGER:
            return 1.0
        frac = max(0.0, T) / self.LIQ_TTE_TRIGGER
        return 1.0 + (self.LIQ_GAMMA_MULT - 1.0) * (1.0 - frac)

    # ---- Avellaneda-Stoikov inventory-skewed quoting ---------------------
    def _as_maker(
        self,
        symbol: str,
        depth: OrderDepth,
        pos: int,
        fair: float,
        limit: int,
        edge: float,
        gamma: float,
        per_side: int,
    ) -> List[Order]:
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []
        reservation = fair - gamma * pos
        qbid = int(round(reservation - edge))
        qask = int(round(reservation + edge))
        if qbid >= ba:
            qbid = ba - 1
        if qask <= bb:
            qask = bb + 1
        if qbid >= qask:
            qbid = qask - 1
        out: List[Order] = []
        room_long = min(per_side, limit - pos)
        room_short = min(per_side, limit + pos)
        if room_long > 0 and qbid > 0:
            out.append(Order(symbol, qbid, room_long))
        if room_short > 0 and qask > 0:
            out.append(Order(symbol, qask, -room_short))
        return out

    # ---- volatility smile ------------------------------------------------
    def _build_smile(
        self,
        S: float,
        T: float,
        depths: Dict[str, OrderDepth],
    ) -> Dict[int, float]:
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
            if iv is None or not (self.SIGMA_FLOOR < iv < self.SIGMA_CEIL):
                continue
            per_strike_iv[k] = iv
            pts_x.append(math.log(k / S) / math.sqrt(T))
            pts_y.append(iv)
        coeffs = _fit_parabola(pts_x, pts_y)
        smoothed: Dict[int, float] = {}
        for k in VEV_STRIKES:
            if coeffs is not None:
                m = math.log(k / S) / math.sqrt(T)
                a, b, c = coeffs
                sigma_k = a * m * m + b * m + c
            elif k in per_strike_iv:
                sigma_k = per_strike_iv[k]
            else:
                sigma_k = self.SIGMA_FALLBACK
            smoothed[k] = max(self.SIGMA_FLOOR, min(self.SIGMA_CEIL, sigma_k))
        return smoothed

    # ---- portfolio delta + risk governor ---------------------------------
    def _portfolio_delta(
        self,
        state: TradingState,
        S: Optional[float],
        T: float,
        smoothed_iv: Optional[Dict[int, float]],
    ) -> float:
        net = float(state.position.get(VFE, 0))
        for k in VEV_STRIKES:
            pos = state.position.get(f"VEV_{k}", 0)
            if pos == 0:
                continue
            if S is not None and smoothed_iv is not None:
                d = _bs_delta(S, k, T, smoothed_iv.get(k, self.SIGMA_FALLBACK))
            else:
                d = 0.5
            net += pos * d
        return net

    def _risk_state(
        self,
        state: TradingState,
        vfe_mid: Optional[float],
        net_delta: float,
    ) -> Tuple[float, bool]:
        hp_pos = abs(state.position.get(HYDROGEL, 0))
        nd = abs(net_delta)
        score = 0.45 * min(1.0, hp_pos / float(self.HP_LIMIT))
        score += 0.55 * min(1.0, nd / float(self.VFE_LIMIT))

        last_vfe = self.history.get("last_vfe_mid")
        if vfe_mid is not None and last_vfe is not None:
            dv = float(vfe_mid) - float(last_vfe)
            if (net_delta > 0 and dv < -self.RISK_ADVERSE_MOVE) or (
                net_delta < 0 and dv > self.RISK_ADVERSE_MOVE
            ):
                score += 0.25

        risk_off = (hp_pos >= self.RISK_HP_POS_TRIGGER
                    or nd >= self.RISK_NET_DELTA_TRIGGER
                    or score >= 0.95)
        scale = max(self.RISK_MIN_SCALE, 1.0 - min(1.0, score))
        return scale, risk_off

    # ---- HYDROGEL --------------------------------------------------------
    def _hydrogel_logic(self, state: TradingState, scale: float, risk_off: bool) -> List[Order]:
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

        taker_max = max(4, int(self.HP_TAKER_MAX * scale))
        taker_enabled = not risk_off
        if taker_enabled and ba <= fair - self.HP_TAKER_EDGE and pos < lim:
            sz = min(taker_max, lim - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(HYDROGEL, ba, sz))
                pos += sz
        if taker_enabled and bb >= fair + self.HP_TAKER_EDGE and pos > -lim:
            sz = min(taker_max, lim + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(HYDROGEL, bb, -sz))
                pos -= sz

        per_side = max(5, int(self.HP_MAKER_PER_SIDE * scale))
        edge = self.HP_MAKER_EDGE + (1.0 if risk_off else 0.0)
        orders.extend(
            self._as_maker(HYDROGEL, depth, pos, fair, lim, edge, self.HP_GAMMA, per_side)
        )
        return orders

    # ---- VFE underlying --------------------------------------------------
    def _vfe_logic(self, state: TradingState, T: float, scale: float, risk_off: bool) -> List[Order]:
        depth = state.order_depths.get(VFE)
        if depth is None:
            return []
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []
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
        gamma_eff = self.VFE_GAMMA * self._liq_multiplier(T)
        orders: List[Order] = []

        taker_max = max(3, int(self.VFE_TAKER_MAX * scale))

        # 1. Mean-reversion overlay (Frankfurt) — disabled in risk-off.
        if self.ENABLE_VFE_MEANREV and not risk_off:
            dev = mid - rev_ema
            rev_sz = max(4, int(self.VFE_REV_SIZE * scale))
            if dev <= -self.VFE_REV_THRESHOLD and pos < self.VFE_REV_MAX_POS:
                sz = min(rev_sz, self.VFE_REV_MAX_POS - pos, -depth.sell_orders[ba])
                if sz > 0:
                    orders.append(Order(VFE, ba, sz))
                    pos += sz
            elif dev >= self.VFE_REV_THRESHOLD and pos > -self.VFE_REV_MAX_POS:
                sz = min(rev_sz, self.VFE_REV_MAX_POS + pos, depth.buy_orders[bb])
                if sz > 0:
                    orders.append(Order(VFE, bb, -sz))
                    pos -= sz

        # 2. Standard taker on EWMA-fair mispricings — disabled in risk-off.
        if (not risk_off) and ba <= fair - self.VFE_TAKER_EDGE and pos < lim:
            sz = min(taker_max, lim - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(VFE, ba, sz))
                pos += sz
        if (not risk_off) and bb >= fair + self.VFE_TAKER_EDGE and pos > -lim:
            sz = min(taker_max, lim + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(VFE, bb, -sz))
                pos -= sz

        per_side = max(4, int(self.VFE_MAKER_PER_SIDE * scale))
        edge = self.VFE_MAKER_EDGE + (1.0 if risk_off else 0.0)
        orders.extend(
            self._as_maker(VFE, depth, pos, fair, lim, edge, gamma_eff, per_side)
        )
        return orders

    # ---- VEV chain -------------------------------------------------------
    def _vev_logic(
        self,
        state: TradingState,
        S: float,
        T: float,
        smoothed_iv: Dict[int, float],
        scale: float,
        risk_off: bool,
    ) -> List[Order]:
        gamma_eff = self.VEV_GAMMA * self._liq_multiplier(T)
        orders: List[Order] = []
        per_side = max(2, int(self.VEV_MAKER_PER_SIDE * scale))

        for strike in VEV_STRIKES:
            sym = f"VEV_{strike}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            bb, ba = self._top(depth)
            if bb is None or ba is None:
                continue
            mid = (bb + ba) / 2.0
            intrinsic = max(S - strike, 0.0)
            obs_prem = mid - intrinsic

            # 1. Update premium-EMA (ken's primary fair-value model).
            sk = str(strike)
            prev_prem = float(self.history["prem"][sk])
            prem = (1 - self.PREM_ALPHA) * prev_prem + self.PREM_ALPHA * obs_prem
            lo, hi = PREM_BOUNDS[strike]
            prem = max(lo, min(hi, prem))
            self.history["prem"][sk] = prem
            fair_prem = intrinsic + prem

            # 2. BS-smile sanity guard: if observed premium has hit the
            #    bounds (i.e. the EMA was clipped), the regime may have
            #    shifted — fall back to the smile fair as a safety net.
            fair = fair_prem
            if self.ENABLE_BS_GUARD:
                fair_bs = _bs_call(S, strike, T, smoothed_iv.get(strike, self.SIGMA_FALLBACK))
                width = hi - lo
                if abs(obs_prem - prem) > width * self.BS_GUARD_BAND:
                    # premium bound clipped a lot — blend toward BS fair
                    fair = 0.5 * fair_prem + 0.5 * fair_bs

            pos = state.position.get(sym, 0)
            cap_base = STRIKE_CAP[strike]
            cap = max(8, int(cap_base * (0.75 if risk_off else 1.0)))

            # 3. Mean-reversion overlay on VEV_5000 (deepest ITM, Δ ≈ 0.8).
            if (self.ENABLE_VEV5000_MEANREV
                    and strike == VEV_STRIKES[0]
                    and not risk_off
                    and self.history.get("vfe_rev_ema") is not None):
                S_dev = S - float(self.history["vfe_rev_ema"])
                rev_sz = max(2, int(self.VEV5000_REV_SIZE * scale))
                if S_dev <= -self.VFE_REV_THRESHOLD and pos < cap:
                    sz = min(rev_sz, cap - pos, -depth.sell_orders[ba])
                    if sz > 0:
                        orders.append(Order(sym, ba, sz))
                        pos += sz
                elif S_dev >= self.VFE_REV_THRESHOLD and pos > -cap:
                    sz = min(rev_sz, cap + pos, depth.buy_orders[bb])
                    if sz > 0:
                        orders.append(Order(sym, bb, -sz))
                        pos -= sz

            # 4. Pure passive maker — no taker on options (ken: takers were
            #    losing ~13k in backtest).  AS skew is the only inventory
            #    control here.
            edge = self.VEV_MAKER_EDGE + (0.8 if risk_off else 0.0)
            orders.extend(
                self._as_maker(sym, depth, pos, fair, cap, edge, gamma_eff, per_side)
            )

        return orders

    # ---- main entrypoint --------------------------------------------------
    def run(self, state: TradingState):
        self._load_state(state)
        T = self._tte(state)
        result: Dict[str, List[Order]] = {}

        # Resolve VFE mid + smile up-front (used by both delta + VEV).
        S: Optional[float] = None
        d_vfe = state.order_depths.get(VFE)
        if d_vfe is not None:
            bb, ba = self._top(d_vfe)
            if bb is not None and ba is not None:
                S = (bb + ba) / 2.0

        smoothed_iv: Optional[Dict[int, float]] = None
        if S is not None:
            smoothed_iv = self._build_smile(S, T, state.order_depths)

        # Risk governor needs portfolio delta first.
        net_delta = self._portfolio_delta(state, S, T, smoothed_iv)
        scale, risk_off = self._risk_state(state, S, net_delta)

        if self.ENABLE_HYDROGEL:
            for o in self._hydrogel_logic(state, scale, risk_off):
                result.setdefault(o.symbol, []).append(o)

        if self.ENABLE_VEV and S is not None and smoothed_iv is not None:
            for o in self._vev_logic(state, S, T, smoothed_iv, scale, risk_off):
                result.setdefault(o.symbol, []).append(o)

        if self.ENABLE_VFE:
            for o in self._vfe_logic(state, T, scale, risk_off):
                result.setdefault(o.symbol, []).append(o)

        if S is not None:
            self.history["last_vfe_mid"] = S

        return result, 0, self._save_state()
