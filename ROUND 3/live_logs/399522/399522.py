"""trader_adin_v2.py — DP-driven mean-reversion scalper.

WHY v1 LOST MONEY (post-mortem)
-------------------------------
v1 used sigma_model = 0.0175 (true RV) while market IV is ~0.0125.  That
makes BS_fair systematically +15…+30 XIRECs above market mid on every
strike.  The guarded maker clamped bid to (ask-1) and effectively *lifted
every offer* on the chain, hit per-strike caps, then ate theta + spread.
Layered on top, explicit delta-hedge via VFE paid the spread on every
rebalance — Frankfurt explicitly warns this kills the gamma P&L.

WHAT v2 DOES DIFFERENTLY
-----------------------
1. Fair value = BS(smile_IV) only.  No directional vol bet.  We scalp
   short-term *residuals* of (market_mid − smile_fair), which is a signal
   the Frankfurt write-up validates with 1-lag negative autocorrelation.

2. Per-strike AR(1) residual model.  Tracks slow-EMA mean and exponential
   half-life of the residual.  A Bellman-style closed form gives the
   *optimal target inventory* in each strike:

       q* = signal / (γ · σ_resid² · h)              (1)

   from maximising

       U(q) = signal · q − ½ γ σ_resid² h q²        (2)

   where γ is risk aversion, σ_resid is residual stdev, h is the
   expected reversion horizon (= 1/(1−ρ)).  We trade toward q*.

3. Avellaneda-Stoikov inventory-skewed quotes.  Reservation price

       r(q,t) = mid − q · γ · σ² · (T−t)            (3)

   skewed bid/ask around r.  This is the closed-form solution to the
   market-maker Bellman equation; positions naturally mean-revert toward
   zero without forcing taker trades.

4. End-of-horizon liquidation DP.  As we approach the option expiry (or
   end of round) we increase γ so the AS skew flattens inventory faster.

5. NO explicit delta-hedge.  The mean-reversion overlay on VFE and
   VEV_5000 is Frankfurt's "hedge against bad luck" — a minimax bet that
   covers the regime where mean reversion dominates.

Calibration anchors come from ROUND 3/data_capsule day 0 + day 1
(see ROUND_3_ANALYSIS.md): VFE σ ≈ 2.15 %/day, market IV ≈ 1.26 %/day,
HYDROGEL mean ≈ 9991, OU half-life ≈ 301 ticks.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]


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


# ===========================================================================
# Trader
# ===========================================================================
class Trader:
    # --- Module switches --------------------------------------------------
    ENABLE_HYDROGEL = True
    ENABLE_VFE = True
    ENABLE_VEV = True
    ENABLE_VFE_MEANREV = True
    ENABLE_VEV5000_MEANREV = True

    # --- Time-to-expiry tracking -------------------------------------------
    INITIAL_DAY = 0
    TTE_AT_DAY_0_START = 8.0
    DAY_LENGTH_TS = 1_000_000

    # --- HYDROGEL_PACK -----------------------------------------------------
    HP_LIMIT = 80
    HP_ANCHOR = 9993.0
    HP_EWMA_ALPHA = 0.20
    HP_TAKER_EDGE = 2.0
    HP_MAKER_EDGE = 2.0
    HP_TAKER_MAX = 20
    HP_GAMMA = 0.04                        # AS inventory penalty (XIRECs/lot)

    # --- VELVETFRUIT_EXTRACT ----------------------------------------------
    VFE_LIMIT = 80
    VFE_EWMA_ALPHA = 0.20
    VFE_REV_EMA_ALPHA = 0.03
    VFE_REV_THRESHOLD = 8.0
    VFE_REV_MAX_POS = 30
    VFE_REV_SIZE = 12
    VFE_MAKER_EDGE = 2.0
    VFE_GAMMA = 0.05                       # AS inventory penalty

    # --- VEV chain ---------------------------------------------------------
    VEV_LIMIT_PER_STRIKE = 30              # tighter than v1 (60 → 30)
    VEV_RES_EMA_ALPHA = 0.05               # slow EMA on price residual
    VEV_TAKER_THRESHOLD = 3.0              # |residual − ema| to trigger taker
    VEV_TAKER_MAX = 5
    VEV_MAKER_EDGE = 2.0
    VEV_AS_GAMMA = 0.20                    # AS inventory penalty per strike
    VEV_TARGET_HALF_LIFE = 25              # ticks; AR(1) → ρ ≈ exp(-1/25)
    VEV_TRADE_COST = 1.5                   # round-trip half-spread cost
    VEV_AR1_RHO = math.exp(-1.0 / 25.0)    # ≈ 0.961
    VEV_REVERSION_HORIZON = 60             # ticks we expect to hold a scalp

    # Smile fitting
    SIGMA_FLOOR = 0.005
    SIGMA_CEIL = 0.040
    SIGMA_FALLBACK = 0.013                 # market chain-flat IV from capsule

    # End-of-horizon liquidation DP — multiplier on γ as TTE shrinks
    LIQ_TTE_TRIGGER = 0.5                  # below 0.5 days remaining → ramp γ
    LIQ_GAMMA_MULT = 4.0                   # max multiplier at TTE = 0

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
        self.history.setdefault("day_count", 0)
        self.history.setdefault("last_ts", -1)
        self.history.setdefault("res_ema", {str(k): 0.0 for k in VEV_STRIKES})
        self.history.setdefault("res_var", {str(k): 4.0 for k in VEV_STRIKES})

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
        """Ramp γ as we approach expiry — Bellman-style end-of-horizon term."""
        if T >= self.LIQ_TTE_TRIGGER:
            return 1.0
        frac = max(0.0, T) / self.LIQ_TTE_TRIGGER
        return 1.0 + (self.LIQ_GAMMA_MULT - 1.0) * (1.0 - frac)

    # ---- AS quote with inventory skew ------------------------------------
    def _as_maker(
        self,
        symbol: str,
        depth: OrderDepth,
        pos: int,
        fair: float,
        limit: int,
        edge: float,
        gamma: float,
    ) -> List[Order]:
        """Avellaneda-Stoikov style.  bid = (fair − γ·q) − edge, ask = (fair − γ·q) + edge.
        With long inventory (q>0) the reservation price drops, so both quotes
        skew lower and we lean into selling (the DP-optimal mean-reversion
        signal for an inventory-averse market maker).
        """
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
        room_long = limit - pos
        room_short = limit + pos
        if room_long > 0 and qbid > 0:
            out.append(Order(symbol, qbid, room_long))
        if room_short > 0 and qask > 0:
            out.append(Order(symbol, qask, -room_short))
        return out

    # ---- HYDROGEL --------------------------------------------------------
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

        orders.extend(
            self._as_maker(HYDROGEL, depth, pos, fair, lim, self.HP_MAKER_EDGE, self.HP_GAMMA)
        )
        return orders

    # ---- volatility smile -------------------------------------------------
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

    # ---- DP optimal target inventory --------------------------------------
    def _optimal_target_inventory(
        self,
        signal: float,
        var_resid: float,
        gamma: float,
    ) -> int:
        """Closed-form maximiser of  U(q) = signal·q − ½ γ σ² q²
        derived from the residual-mean-reversion Bellman equation.
        signal = expected price reversion per lot from current → fair.
        """
        denom = max(gamma * var_resid, 1e-3)
        q_star = signal / denom
        # Cap by the per-strike position limit.
        cap = self.VEV_LIMIT_PER_STRIKE
        return max(-cap, min(cap, int(round(q_star))))

    # ---- VEV chain --------------------------------------------------------
    def _vev_logic(self, state: TradingState, S: float, T: float) -> List[Order]:
        smoothed_iv = self._build_smile(S, T, state.order_depths)
        liq_mult = self._liq_multiplier(T)
        gamma_eff = self.VEV_AS_GAMMA * liq_mult

        # Expected fraction of residual that mean-reverts over horizon h.
        revert_frac = 1.0 - self.VEV_AR1_RHO ** self.VEV_REVERSION_HORIZON

        orders: List[Order] = []

        for strike in VEV_STRIKES:
            sym = f"VEV_{strike}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            bb, ba = self._top(depth)
            if bb is None or ba is None:
                continue

            sigma_k = smoothed_iv[strike]
            mid = (bb + ba) / 2.0
            fair = _bs_call(S, strike, T, sigma_k)
            residual = mid - fair                                  # signed price deviation

            # --- update residual EMA + variance (online estimator) -------
            sk = str(strike)
            prev_ema = float(self.history["res_ema"].get(sk, 0.0))
            prev_var = float(self.history["res_var"].get(sk, 4.0))
            ema = (1 - self.VEV_RES_EMA_ALPHA) * prev_ema + self.VEV_RES_EMA_ALPHA * residual
            dev = residual - ema
            var = (1 - self.VEV_RES_EMA_ALPHA) * prev_var + self.VEV_RES_EMA_ALPHA * dev * dev
            var = max(var, 0.5)
            self.history["res_ema"][sk] = ema
            self.history["res_var"][sk] = var

            # --- Bellman-style optimal inventory ---------------------------
            # Expected price revert (per lot) is −dev · revert_frac
            # (positive when residual is BELOW its baseline → option cheap → buy).
            expected_revert = -dev * revert_frac
            # Net signal must exceed round-trip cost to be worth trading.
            signal = 0.0
            if abs(expected_revert) > self.VEV_TRADE_COST:
                signal = expected_revert - math.copysign(self.VEV_TRADE_COST, expected_revert)

            target_q = self._optimal_target_inventory(signal, var, gamma_eff)
            pos = state.position.get(sym, 0)
            cap = self.VEV_LIMIT_PER_STRIKE

            # --- taker leg: only when |dev| > threshold AND target wants more ---
            if dev <= -self.VEV_TAKER_THRESHOLD and target_q > pos and pos < cap:
                want = min(target_q - pos, self.VEV_TAKER_MAX, cap - pos, -depth.sell_orders[ba])
                if want > 0:
                    orders.append(Order(sym, ba, want))
                    pos += want
            elif dev >= self.VEV_TAKER_THRESHOLD and target_q < pos and pos > -cap:
                want = min(pos - target_q, self.VEV_TAKER_MAX, cap + pos, depth.buy_orders[bb])
                if want > 0:
                    orders.append(Order(sym, bb, -want))
                    pos -= want

            # --- VEV_5000 mean-reversion overlay ---------------------------
            # Frankfurt: the deepest ITM call (delta ≈ 0.8) doubles up on the
            # underlying mean-reversion bet — the "hedge against bad luck".
            if (self.ENABLE_VEV5000_MEANREV
                    and strike == VEV_STRIKES[0]
                    and self.history.get("vfe_rev_ema") is not None):
                S_dev = S - float(self.history["vfe_rev_ema"])
                rev_size = 6
                if S_dev <= -self.VFE_REV_THRESHOLD and pos < cap:
                    sz = min(rev_size, cap - pos, -depth.sell_orders[ba])
                    if sz > 0:
                        orders.append(Order(sym, ba, sz))
                        pos += sz
                elif S_dev >= self.VFE_REV_THRESHOLD and pos > -cap:
                    sz = min(rev_size, cap + pos, depth.buy_orders[bb])
                    if sz > 0:
                        orders.append(Order(sym, bb, -sz))
                        pos -= sz

            # --- AS-skewed maker uses smile fair as the reservation centre ---
            orders.extend(
                self._as_maker(sym, depth, pos, fair, cap, self.VEV_MAKER_EDGE, gamma_eff)
            )

        return orders

    # ---- VFE underlying ---------------------------------------------------
    def _vfe_logic(self, state: TradingState, T: float) -> List[Order]:
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

        # Mean-reversion overlay (Frankfurt's lightweight model).
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

        orders.extend(
            self._as_maker(VFE, depth, pos, fair, lim, self.VFE_MAKER_EDGE, gamma_eff)
        )
        return orders

    # ---- main entrypoint --------------------------------------------------
    def run(self, state: TradingState):
        self._load_state(state)
        T = self._tte(state)
        result: Dict[str, List[Order]] = {}

        if self.ENABLE_HYDROGEL:
            for o in self._hydrogel_logic(state):
                result.setdefault(o.symbol, []).append(o)

        # Resolve VFE mid for the option pricing.
        S: Optional[float] = None
        d_vfe = state.order_depths.get(VFE)
        if d_vfe is not None:
            bb, ba = self._top(d_vfe)
            if bb is not None and ba is not None:
                S = (bb + ba) / 2.0

        if self.ENABLE_VEV and S is not None:
            for o in self._vev_logic(state, S, T):
                result.setdefault(o.symbol, []).append(o)

        if self.ENABLE_VFE:
            for o in self._vfe_logic(state, T):
                result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save_state()