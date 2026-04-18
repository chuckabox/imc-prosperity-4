"""
trader_robust_suvin_v1.py
=========================
IMC Prosperity – Round 2
Author : Suvin (refactored)

Architecture
------------
Phase I  – Log-Geometric Differencing + Jarque-Bera fat-tail profiling
           + CUSUM regime-break detection
Phase II – Manual VECM Solver (SVD / Eigen-decomposition via NumPy)
           → Cointegrating vector β → Spread → Z-score
           → Dynamic fair-value overlay on OSMIUM market-maker
           → Hard stop-loss (|Z| > HARD_STOP) flattens position instantly

Allowed libraries: numpy, pandas, math, typing, statistics, jsonpickle
NO statsmodels / scikit-learn / os / subprocess.

State persists via state.traderData (jsonpickle, bounded rolling window).
"""

import json
import math
import statistics
from typing import Dict, List, Any, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Exchange datamodel stubs (replaced by real imports on the exchange)
# ---------------------------------------------------------------------------
try:
    from datamodel import Order, OrderDepth, TradingState, Symbol  # type: ignore
except ImportError:  # local back-test shim
    class Order:
        def __init__(self, symbol, price, quantity):
            self.symbol   = symbol
            self.price    = price
            self.quantity = quantity
        def __repr__(self):
            return f"Order({self.symbol}, {self.price}, {self.quantity})"

    class TradingState:
        pass

    Symbol = str


# ---------------------------------------------------------------------------
# Tiny logger (exchange-compatible)
# ---------------------------------------------------------------------------
class Logger:
    def __init__(self):
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state, orders, conversions, trader_data):
        pass


logger = Logger()


# ===========================================================================
# Utility helpers
# ===========================================================================

def _median(vals: list) -> float:
    n = len(vals)
    if n == 0:
        return 0.0
    s = sorted(vals)
    mid = n // 2
    return float(s[mid]) if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0


# ---------------------------------------------------------------------------
# Phase I helpers
# ---------------------------------------------------------------------------

def _log_returns(prices: list) -> np.ndarray:
    """r(t) = ln(p(t) / p(t-1)) – time-additive, scale-invariant."""
    arr = np.array(prices, dtype=float)
    # Guard against non-positive prices
    arr = np.maximum(arr, 1e-9)
    return np.log(arr[1:] / arr[:-1])


def _jarque_bera(returns: np.ndarray) -> Tuple[float, bool]:
    """
    Manual Jarque-Bera statistic.
    JB = (n/6) * [S^2 + (K-3)^2/4]
    Returns (jb_stat, is_fat_tailed).
    Fat-tailed if JB > 6.0 (rough ~5% critical value for large n).
    """
    n = len(returns)
    if n < 8:
        return 0.0, False
    mu  = np.mean(returns)
    s   = np.std(returns, ddof=1)
    if s < 1e-12:
        return 0.0, False
    z   = (returns - mu) / s
    skewness = float(np.mean(z ** 3))
    kurtosis = float(np.mean(z ** 4))
    jb = (n / 6.0) * (skewness ** 2 + (kurtosis - 3.0) ** 2 / 4.0)
    return jb, jb > 6.0


def _cusum(returns: np.ndarray, threshold: float = 4.0) -> bool:
    """
    Two-sided CUSUM on standardised returns.
    Returns True if a structural break is detected (regime shift).
    threshold: number of std-devs accumulated before flagging a break.
    """
    if len(returns) < 10:
        return False
    mu = np.mean(returns)
    s  = np.std(returns, ddof=1)
    if s < 1e-12:
        return False
    std_r  = (returns - mu) / s
    cup    = 0.0
    cdown  = 0.0
    for r in std_r:
        cup   = max(0.0, cup   + r - 0.5)
        cdown = max(0.0, cdown - r - 0.5)
        if cup > threshold or cdown > threshold:
            return True
    return False


# ---------------------------------------------------------------------------
# Phase II helpers – Manual VECM via SVD / Eigen
# ---------------------------------------------------------------------------

def _johansen_beta(price_matrix: np.ndarray) -> Optional[np.ndarray]:
    """
    Simplified Johansen step: find the cointegrating vector β via
    Eigen-decomposition of the long-run covariance matrix.

    price_matrix : shape (T, 2)  – [PEPPER_mid, OSMIUM_mid]

    Returns β as shape-(2,) unit vector (smallest eigenvalue eigenvector),
    or None if numerics are degenerate.
    """
    if price_matrix.shape[0] < 20 or price_matrix.shape[1] < 2:
        return None
    try:
        cov = np.cov(price_matrix.T)          # (2, 2)
        if not np.all(np.isfinite(cov)):
            return None
        evals, evecs = np.linalg.eig(cov)
        if not np.all(np.isfinite(evals)):
            return None
        beta = evecs[:, int(np.argmin(evals))].real
        norm = np.linalg.norm(beta)
        if norm < 1e-12:
            return None
        return beta / norm
    except Exception:
        return None


def _svd_ols_beta(price_matrix: np.ndarray) -> Optional[np.ndarray]:
    """
    OLS hedge ratio via SVD:  min ||y - X β||
    price_matrix columns: [y, x]  →  β = (XᵀX)⁻¹ Xᵀy via SVD.
    Returns scalar hedge ratio h such that spread = y - h*x.
    """
    if price_matrix.shape[0] < 20:
        return None
    try:
        y = price_matrix[:, 0]
        X = np.column_stack([price_matrix[:, 1], np.ones(len(y))])
        U, S, Vt = np.linalg.svd(X, full_matrices=False)
        # Guard tiny singular values
        S_inv = np.where(S > 1e-10, 1.0 / S, 0.0)
        beta_ols = Vt.T @ np.diag(S_inv) @ U.T @ y
        return beta_ols  # [h, intercept]
    except Exception:
        return None


def _compute_spread_zscore(
    price_matrix: np.ndarray,
    beta: np.ndarray,
    window: int = 60,
) -> Tuple[float, float, float]:
    """
    Compute the VECM spread and its Z-score.
    spread(t) = price_matrix[-window:] @ beta
    Returns (z_score, spread_mean, spread_std).
    """
    tail = price_matrix[-window:]
    spread = tail @ beta
    mu  = float(np.mean(spread))
    std = float(np.std(spread, ddof=1))
    if std < 1e-9:
        return 0.0, mu, std
    z = float((spread[-1] - mu) / std)
    return z, mu, std


def _half_life(spread: np.ndarray) -> float:
    """
    OLS-estimated half-life of mean reversion:
    Δspread(t) = α * spread(t-1) + ε
    half_life = -ln(2) / α
    Returns half_life in ticks (clamped 5..200).
    """
    if len(spread) < 10:
        return 30.0
    try:
        y  = np.diff(spread)
        x  = spread[:-1] - np.mean(spread)
        # OLS via dot products (no library)
        alpha = float(np.dot(x, y) / (np.dot(x, x) + 1e-12))
        if alpha >= 0.0 or not math.isfinite(alpha):
            return 100.0
        hl = -math.log(2.0) / alpha
        return float(np.clip(hl, 5.0, 200.0))
    except Exception:
        return 30.0


# ===========================================================================
# Main Trader
# ===========================================================================

class Trader:
    # -----------------------------------------------------------------------
    # Position limits
    # -----------------------------------------------------------------------
    LIMIT = 80

    # -----------------------------------------------------------------------
    # Rolling window sizes (bounded for traderData budget)
    # -----------------------------------------------------------------------
    HIST_MAX       = 120   # max ticks stored for each price series
    VECM_WINDOW    = 80    # ticks used for VECM estimation
    CUSUM_WINDOW   = 40    # ticks used for CUSUM check
    JB_WINDOW      = 60    # ticks used for Jarque-Bera
    SLOPE_WINDOW   = 20    # ticks for PEPPER stop-guard slope

    # -----------------------------------------------------------------------
    # Phase II – VECM / Z-score thresholds
    # -----------------------------------------------------------------------
    VECM_WARMUP       = 80    # ticks before VECM is trusted
    Z_ENTRY           = 1.8   # Z beyond which we trade against the spread
    Z_EXIT            = 0.4   # Z within which we exit the spread trade
    Z_HARD_STOP       = 3.8   # |Z| beyond this → immediate flatten (stop-loss)
    Z_FAT_TAIL_SCALE  = 0.5   # scale position by this factor when fat tails detected
    REFIT_INTERVAL    = 200   # ticks between VECM re-estimation

    # -----------------------------------------------------------------------
    # PEPPER (directional trend) – unchanged core, CUSUM overlay added
    # -----------------------------------------------------------------------
    PEPPER_WARMUP_TICKS       = 1500
    PEPPER_FASTTRACK_TICKS    = 700
    PEPPER_FASTTRACK_SAMPLES  = 10
    PEPPER_FASTTRACK_SLOPE    = 0.10
    PEPPER_REEVAL_INTERVAL    = 5000
    PEPPER_SMOOTH_N           = 15

    PEPPER_SLOPE_STRONG   = 0.06
    PEPPER_SLOPE_MODERATE = 0.02
    PEPPER_SLOPE_WEAK     = -0.02

    PEPPER_CAP_STRONG    = 80
    PEPPER_CAP_MODERATE  = 60
    PEPPER_CAP_WEAK      = 30
    PEPPER_CAP_NEGATIVE  = 0
    PEPPER_CAP_TENTATIVE = 20

    PEPPER_TAKE_PER_TICK         = 10
    PEPPER_TAKE_PER_TICK_STRONG  = 15
    PEPPER_TAKE_PER_TICK_TENT    = 5
    PEPPER_PASSIVE_CAP           = 40

    PEPPER_SLOPE_WINDOW    = 20
    PEPPER_STOP_THRESHOLD  = -12
    PEPPER_STOP_HYSTERESIS = 2
    PEPPER_RESUME_THRESHOLD = 5
    PEPPER_FLATTEN_CHUNK   = 15
    PEPPER_FLATTEN_FIRST   = 30

    # -----------------------------------------------------------------------
    # OSMIUM market-maker core – unchanged, VECM overlay added
    # -----------------------------------------------------------------------
    OSMIUM_ANCHOR              = 10_000
    OSMIUM_TAKE_EDGE           = 1
    OSMIUM_TAKE_EDGE_UNSAFE    = 2
    OSMIUM_QUOTE_SIZE          = 25
    OSMIUM_SECOND_SIZE         = 18
    OSMIUM_SKEW_SOFT           = 22
    OSMIUM_SKEW_HARD           = 45
    OSMIUM_FLATTEN             = 55
    OSMIUM_ANCHOR_DRIFT_TICKS  = 20
    OSMIUM_ANCHOR_DRIFT_THR    = 6
    OSMIUM_TOXIC_VOLUME        = 40
    OSMIUM_CLAMP               = 4

    # -----------------------------------------------------------------------
    # Phase III – Market Access Fee (MAF) auction engine
    # -----------------------------------------------------------------------
    # The MAF is a blind competitive auction. Top 50% of bidders win +25%
    # volume. We bid a fraction of the estimated expected value of that volume.
    #
    # Decision rule (per tick):
    #   edge_per_unit  = rolling mean |spread capture| per filled unit
    #   extra_units    = LIMIT * 0.25          (volume gain if we win)
    #   ev_of_winning  = edge_per_unit * extra_units
    #   maf_bid        = ev_of_winning * MAF_BID_FRACTION
    #
    # Kill-switch: MAF = 0 whenever CUSUM fires OR fat-tails detected on
    # the product(s) we'd use the extra volume on — paying for capacity
    # we'll size-down anyway is pure waste.
    # -----------------------------------------------------------------------
    MAF_WARMUP_TICKS   = 100    # ticks of edge history before bidding
    MAF_EDGE_WINDOW    = 60     # rolling window for edge-per-unit estimate
    MAF_BID_FRACTION   = 0.35   # bid this fraction of EV (conservative; leaves margin)
    MAF_BID_MIN        = 10     # floor bid once warmed up (stay in auction)
    MAF_BID_MAX        = 5000   # hard cap (prevent runaway bids)
    MAF_ADAPT_UP       = 1.10   # multiply bid by this if we lost last auction
    MAF_ADAPT_DOWN     = 0.92   # multiply bid by this if we won cheaply

    # -----------------------------------------------------------------------
    def __init__(self):
        # Serialised state (persisted in traderData)
        self.history: Dict[str, list] = {}

    # =======================================================================
    # State load / save
    # =======================================================================

    def _load_state(self, state: TradingState):
        if getattr(state, "traderData", None):
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}

    def _save_state(self) -> str:
        return json.dumps(self.history)

    # =======================================================================
    # Phase I – signal processing layer
    # =======================================================================

    def _phase1_signals(
        self,
        pepper_prices: list,
        osmium_prices: list,
    ) -> Dict[str, Any]:
        """
        Returns a dict with:
          is_fat_tailed_pepper, is_fat_tailed_osmium,
          cusum_break_pepper,   cusum_break_osmium,
          jb_pepper, jb_osmium
        """
        result = dict(
            is_fat_tailed_pepper=False,
            is_fat_tailed_osmium=False,
            cusum_break_pepper=False,
            cusum_break_osmium=False,
            jb_pepper=0.0,
            jb_osmium=0.0,
        )
        if len(pepper_prices) >= 2:
            r_pp = _log_returns(pepper_prices[-self.JB_WINDOW:])
            if len(r_pp) >= 8:
                jb_pp, fat_pp = _jarque_bera(r_pp)
                result["jb_pepper"]            = jb_pp
                result["is_fat_tailed_pepper"] = fat_pp
                r_cusum_pp = _log_returns(pepper_prices[-self.CUSUM_WINDOW:])
                if len(r_cusum_pp) >= 10:
                    result["cusum_break_pepper"] = _cusum(r_cusum_pp)

        if len(osmium_prices) >= 2:
            r_os = _log_returns(osmium_prices[-self.JB_WINDOW:])
            if len(r_os) >= 8:
                jb_os, fat_os = _jarque_bera(r_os)
                result["jb_osmium"]            = jb_os
                result["is_fat_tailed_osmium"] = fat_os
                r_cusum_os = _log_returns(osmium_prices[-self.CUSUM_WINDOW:])
                if len(r_cusum_os) >= 10:
                    result["cusum_break_osmium"] = _cusum(r_cusum_os)

        return result

    # =======================================================================
    # Phase II – VECM / Z-score
    # =======================================================================

    def _phase2_vecm(
        self,
        pepper_prices: list,
        osmium_prices: list,
        ts: int,
    ) -> Dict[str, Any]:
        """
        Fits (or retrieves cached) VECM β every REFIT_INTERVAL ticks.
        Returns z_score, half_life, beta, spread_valid flag.
        """
        result = dict(
            z_score     = 0.0,
            half_life   = 30.0,
            beta        = None,
            valid       = False,
        )

        n = min(len(pepper_prices), len(osmium_prices))
        if n < self.VECM_WARMUP:
            return result

        last_fit   = self.history.get("vecm_last_fit", -9999)
        cached_beta = self.history.get("vecm_beta", None)

        needs_refit = (
            cached_beta is None
            or (ts - last_fit) >= self.REFIT_INTERVAL
        )

        if needs_refit:
            tail_n = min(n, self.VECM_WINDOW)
            pp_tail = np.array(pepper_prices[-tail_n:], dtype=float)
            os_tail = np.array(osmium_prices[-tail_n:], dtype=float)
            mat     = np.column_stack([pp_tail, os_tail])

            # Primary: Johansen β (cointegrating vector)
            beta = _johansen_beta(mat)

            # Fallback: OLS hedge ratio if Johansen degenerate
            if beta is None:
                ols = _svd_ols_beta(mat)
                if ols is not None:
                    h = float(ols[0])
                    beta = np.array([1.0, -h]) / max(1e-9, math.sqrt(1.0 + h ** 2))

            if beta is not None:
                self.history["vecm_beta"]     = beta.tolist()
                self.history["vecm_last_fit"] = ts
                cached_beta = beta.tolist()

        if cached_beta is None:
            return result

        beta_arr = np.array(cached_beta)
        tail_n   = min(n, self.VECM_WINDOW)
        pp_tail  = np.array(pepper_prices[-tail_n:], dtype=float)
        os_tail  = np.array(osmium_prices[-tail_n:], dtype=float)
        mat      = np.column_stack([pp_tail, os_tail])

        z, mu, std = _compute_spread_zscore(mat, beta_arr, window=tail_n)

        # Half-life for position sizing reference
        spread_series = mat @ beta_arr
        hl = _half_life(spread_series)

        result.update(dict(
            z_score   = z,
            half_life = hl,
            beta      = cached_beta,
            valid     = True,
        ))
        return result

    # =======================================================================
    # Hard stop-loss helper
    # =======================================================================

    def _hard_stop_orders(
        self,
        product: str,
        depth,
        pos: int,
    ) -> List[Order]:
        """Flatten entire position at best available price."""
        orders = []
        if pos > 0:
            # Sell into best bids
            bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
            if bb is not None:
                orders.append(Order(product, bb, -pos))
        elif pos < 0:
            ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
            if ba is not None:
                orders.append(Order(product, ba, -pos))  # negative pos → positive qty
        return orders

    # =======================================================================
    # PEPPER (directional) – Phase I overlay + hard stop
    # =======================================================================

    def _pick_pepper_cap(self, slope: float) -> int:
        if slope > self.PEPPER_SLOPE_STRONG:
            return self.PEPPER_CAP_STRONG
        if slope > self.PEPPER_SLOPE_MODERATE:
            return self.PEPPER_CAP_MODERATE
        if slope > self.PEPPER_SLOPE_WEAK:
            return self.PEPPER_CAP_WEAK
        return self.PEPPER_CAP_NEGATIVE

    def _pepper_logic(
        self,
        state: TradingState,
        sig1: Dict[str, Any],
    ) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos   = state.position.get(product, 0)

        bb = max(depth.buy_orders.keys())  if depth.buy_orders  else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        ts  = state.timestamp

        # --- history update ---
        hist = self.history.get("pp", [])
        hist.append(mid)
        if len(hist) > self.HIST_MAX:
            hist = hist[-self.HIST_MAX:]
        self.history["pp"] = hist

        start_samples = self.history.get("pp_start_samples", [])
        if len(start_samples) < self.PEPPER_SMOOTH_N:
            start_samples.append(mid)
            self.history["pp_start_samples"] = start_samples

        if "pp_start_ts" not in self.history:
            self.history["pp_start_ts"] = ts

        start_ts     = self.history.get("pp_start_ts", ts)
        cap          = self.history.get("pp_cap", None)
        last_eval_ts = self.history.get("pp_last_eval_ts", None)

        # Fast-track
        if (
            cap is None
            and (ts - start_ts) >= self.PEPPER_FASTTRACK_TICKS
            and len(start_samples) >= self.PEPPER_FASTTRACK_SAMPLES
        ):
            sm_start = _median(start_samples)
            sm_now   = _median(hist[-min(len(hist), self.PEPPER_FASTTRACK_SAMPLES):])
            elapsed  = max(1, ts - start_ts)
            slope_e  = (sm_now - sm_start) / elapsed * 100.0
            if slope_e >= self.PEPPER_FASTTRACK_SLOPE:
                cap          = self.PEPPER_CAP_STRONG
                last_eval_ts = ts
                self.history["pp_cap"]          = cap
                self.history["pp_last_eval_ts"] = last_eval_ts
                self.history["pp_measured_slope"] = slope_e

        warmed_up = (ts - start_ts) >= self.PEPPER_WARMUP_TICKS

        if warmed_up and len(start_samples) >= self.PEPPER_SMOOTH_N:
            smoothed_start = _median(start_samples)
            smoothed_now   = _median(hist[-self.PEPPER_SMOOTH_N:])
            elapsed        = max(1, ts - start_ts)
            slope          = (smoothed_now - smoothed_start) / elapsed * 100.0

            if cap is None:
                cap          = self._pick_pepper_cap(slope)
                last_eval_ts = ts
                self.history["pp_cap"]          = cap
                self.history["pp_last_eval_ts"] = last_eval_ts
                self.history["pp_measured_slope"] = slope
            elif (
                last_eval_ts is not None
                and (ts - last_eval_ts) >= self.PEPPER_REEVAL_INTERVAL
            ):
                fresh = self._pick_pepper_cap(slope)
                if fresh > cap:
                    cap = fresh
                    self.history["pp_cap"] = cap
                    self.history["pp_measured_slope"] = slope
                last_eval_ts = ts
                self.history["pp_last_eval_ts"] = last_eval_ts

        confirmed      = cap is not None
        effective_cap  = cap if confirmed else self.PEPPER_CAP_TENTATIVE

        # Phase I: scale down cap when CUSUM detects a regime break
        if sig1.get("cusum_break_pepper", False):
            effective_cap = max(0, int(effective_cap * 0.5))

        if not confirmed:
            take_per_tick = self.PEPPER_TAKE_PER_TICK_TENT
        elif cap == self.PEPPER_CAP_STRONG:
            take_per_tick = self.PEPPER_TAKE_PER_TICK_STRONG
        else:
            take_per_tick = self.PEPPER_TAKE_PER_TICK

        # --- stop guard (magnitude slope) ---
        stop_breach  = int(self.history.get("pp_breach", 0))
        drift_stopped = bool(self.history.get("pp_stopped", False))
        was_stopped  = drift_stopped

        if len(hist) >= self.PEPPER_SLOPE_WINDOW:
            window  = hist[-self.PEPPER_SLOPE_WINDOW:]
            slope_w = window[-1] - window[0]
            if slope_w < self.PEPPER_STOP_THRESHOLD:
                stop_breach += 1
            else:
                stop_breach = 0
            if stop_breach >= self.PEPPER_STOP_HYSTERESIS:
                drift_stopped = True
            elif drift_stopped and slope_w > self.PEPPER_RESUME_THRESHOLD:
                drift_stopped = False

        self.history["pp_breach"]  = stop_breach
        self.history["pp_stopped"] = drift_stopped

        orders: List[Order] = []

        if drift_stopped or effective_cap == 0:
            if pos > 0:
                just_triggered = drift_stopped and not was_stopped
                chunk = self.PEPPER_FLATTEN_FIRST if just_triggered else self.PEPPER_FLATTEN_CHUNK
                avail = depth.buy_orders.get(bb, 0)
                qty   = min(pos, avail, chunk)
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        rem_cap     = effective_cap - pos
        if rem_cap <= 0:
            return orders

        take_budget = min(rem_cap, take_per_tick)
        taken       = 0

        for ask in sorted(depth.sell_orders.keys()):
            if take_budget <= 0:
                break
            avail = -depth.sell_orders[ask]
            if avail <= 0:
                continue
            if ask <= mid + 1:
                qty = min(take_budget, avail)
                orders.append(Order(product, ask, qty))
                take_budget -= qty
                taken       += qty

        rem_cap -= taken
        if rem_cap > 0:
            passive_qty = min(rem_cap, self.PEPPER_PASSIVE_CAP)
            orders.append(Order(product, bb + 1, passive_qty))

        return orders

    # =======================================================================
    # OSMIUM (market-maker) – Phase I + II overlay + hard stop
    # =======================================================================

    def _osmium_logic(
        self,
        state: TradingState,
        sig1: Dict[str, Any],
        sig2: Dict[str, Any],
    ) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos   = state.position.get(product, 0)

        bb = max(depth.buy_orders.keys())  if depth.buy_orders  else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0

        # --- Dynamic fair value ---
        # Base anchor; VECM Z-score nudges it when signal is valid.
        fair = float(self.OSMIUM_ANCHOR)

        z        = sig2.get("z_score", 0.0)
        vecm_ok  = sig2.get("valid", False)
        fat_os   = sig1.get("is_fat_tailed_osmium", False)
        cusum_os = sig1.get("cusum_break_osmium",   False)

        # --- Hard stop-loss: |Z| beyond threshold → flatten immediately ---
        if vecm_ok and abs(z) >= self.Z_HARD_STOP:
            logger.print(f"[OSMIUM] HARD STOP triggered | Z={z:.3f} | pos={pos}")
            return self._hard_stop_orders(product, depth, pos)

        # Phase II fair-value shift: spread mean-reversion signal
        # β = [β_pp, β_os]; spread = β_pp*P_pp + β_os*P_os
        # When Z >> 0 osmium is relatively overpriced → lower fair by a clamp
        if vecm_ok and abs(z) >= self.Z_ENTRY:
            direction  = -1.0 if z > 0 else 1.0   # revert toward zero
            nudge_raw  = direction * min(abs(z) * 1.5, self.OSMIUM_CLAMP)
            # Under fat tails, halve the nudge (GARCH-inspired risk scale)
            nudge      = nudge_raw * (self.Z_FAT_TAIL_SCALE if fat_os else 1.0)
            fair      += nudge

        # CUSUM break → pull fair back to hard anchor (don't trust recent drift)
        if cusum_os:
            fair = float(self.OSMIUM_ANCHOR)

        # --- Anchor-drift detection (existing logic, adapted) ---
        hist_op = self.history.get("op", [])
        hist_op.append(mid)
        if len(hist_op) > self.HIST_MAX:
            hist_op = hist_op[-self.HIST_MAX:]
        self.history["op"] = hist_op

        anchor_off = False
        if len(hist_op) >= self.OSMIUM_ANCHOR_DRIFT_TICKS:
            recent = hist_op[-self.OSMIUM_ANCHOR_DRIFT_TICKS:]
            avg    = sum(recent) / len(recent)
            if abs(avg - self.OSMIUM_ANCHOR) > self.OSMIUM_ANCHOR_DRIFT_THR:
                anchor_off = True

        size_scale = 0.5 if anchor_off else 1.0
        # Extra size reduction under regime breaks
        if cusum_os or fat_os:
            size_scale *= 0.7

        front_qty  = max(6, int(self.OSMIUM_QUOTE_SIZE  * size_scale))
        second_qty = max(4, int(self.OSMIUM_SECOND_SIZE * size_scale))
        take_edge  = self.OSMIUM_TAKE_EDGE_UNSAFE if anchor_off else self.OSMIUM_TAKE_EDGE

        # --- Toxic-flow detection ---
        buy_vol = sell_vol = 0
        if product in state.market_trades:
            for t in state.market_trades[product]:
                if t.price >= mid:
                    buy_vol  += abs(t.quantity)
                else:
                    sell_vol += abs(t.quantity)
        diff             = buy_vol - sell_vol
        toxic_skip_buys  = diff >=  self.OSMIUM_TOXIC_VOLUME
        toxic_skip_sells = -diff >= self.OSMIUM_TOXIC_VOLUME

        orders:   List[Order] = []
        rem_buy   = self.LIMIT - pos
        rem_sell  = self.LIMIT + pos

        # --- Aggressive takes (inside-fair trades) ---
        if not toxic_skip_buys:
            for ask in sorted(depth.sell_orders.keys()):
                if ask <= fair - take_edge and rem_buy > 0:
                    avail = -depth.sell_orders[ask]
                    qty   = min(rem_buy, avail)
                    if qty > 0:
                        orders.append(Order(product, ask, qty))
                        rem_buy -= qty
                        pos     += qty

        if not toxic_skip_sells:
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid >= fair + take_edge and rem_sell > 0:
                    avail = depth.buy_orders[bid]
                    qty   = min(rem_sell, avail)
                    if qty > 0:
                        orders.append(Order(product, bid, -qty))
                        rem_sell -= qty
                        pos      -= qty

        # --- Flatten if too long/short ---
        if pos > self.OSMIUM_FLATTEN and rem_sell > 0:
            qty = min(pos - self.OSMIUM_FLATTEN + 5, rem_sell)
            if qty > 0:
                orders.append(Order(product, int(fair), -qty))
                rem_sell -= qty
        elif pos < -self.OSMIUM_FLATTEN and rem_buy > 0:
            qty = min(-pos - self.OSMIUM_FLATTEN + 5, rem_buy)
            if qty > 0:
                orders.append(Order(product, int(fair), qty))
                rem_buy -= qty

        # --- Skew quoting ---
        abs_pos  = abs(pos)
        skew     = 2 if abs_pos > self.OSMIUM_SKEW_HARD else (1 if abs_pos > self.OSMIUM_SKEW_SOFT else 0)
        skew_dir = 1 if pos > 0 else -1

        bid_price = min(bb + 1, int(fair) - 1) - skew * skew_dir
        ask_price = max(ba - 1, int(fair) + 1) - skew * skew_dir

        bid_price = max(int(bid_price), int(fair) - self.OSMIUM_CLAMP)
        ask_price = min(int(ask_price), int(fair) + self.OSMIUM_CLAMP)

        if bid_price >= ask_price:
            bid_price = int(fair) - 1
            ask_price = int(fair) + 1

        if rem_buy > 0:
            front = min(rem_buy, front_qty)
            orders.append(Order(product, int(bid_price), front))
            rem_buy -= front
            if rem_buy > 0:
                orders.append(Order(product, int(bid_price - 1), min(rem_buy, second_qty)))

        if rem_sell > 0:
            front = min(rem_sell, front_qty)
            orders.append(Order(product, int(ask_price), -front))
            rem_sell -= front
            if rem_sell > 0:
                orders.append(Order(product, int(ask_price + 1), -min(rem_sell, second_qty)))

        return orders

    # =======================================================================
    # Phase III – MAF auction engine
    # =======================================================================

    def _record_edge(self, product: str, fills: List[Order], depth) -> None:
        """
        After order generation, approximate the edge captured per filled unit
        for a product and push it into the rolling edge history.

        Edge proxy = sum(|order_price - fair_mid| * |qty|) / sum(|qty|)
        where fair_mid is the current best-bid/ask midpoint.
        """
        bb = max(depth.buy_orders.keys())  if depth.buy_orders  else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None:
            return
        mid = (bb + ba) / 2.0

        total_edge = 0.0
        total_qty  = 0
        for o in fills:
            qty = abs(o.quantity)
            if qty == 0:
                continue
            # Edge = how far inside fair we traded
            edge = abs(o.price - mid)
            total_edge += edge * qty
            total_qty  += qty

        if total_qty == 0:
            return

        eu = total_edge / total_qty
        key = f"maf_edge_{product}"
        buf = self.history.get(key, [])
        buf.append(eu)
        if len(buf) > self.MAF_EDGE_WINDOW:
            buf = buf[-self.MAF_EDGE_WINDOW:]
        self.history[key] = buf

    def _compute_maf(
        self,
        sig1: Dict[str, Any],
        sig2: Dict[str, Any],
        pepper_orders: List[Order],
        osmium_orders: List[Order],
        pepper_depth,
        osmium_depth,
        ts: int,
    ) -> int:
        """
        Compute the MAF bid for this tick.

        Returns an integer MAF value (≥ 0).  0 means "don't bid".

        Decision tree:
        1. Record edge samples from this tick's orders.
        2. If not warmed up → return 0.
        3. If kill-switch active (CUSUM or fat-tail on both products) → return 0.
        4. Compute EV of winning from each product's edge history.
        5. Apply adaptive multiplier (up if previously lost, down if won cheaply).
        6. Clamp to [MAF_BID_MIN, MAF_BID_MAX].
        """
        # 1. Record edge samples
        if pepper_depth is not None:
            self._record_edge("PEPPER", pepper_orders, pepper_depth)
        if osmium_depth is not None:
            self._record_edge("OSMIUM", osmium_orders, osmium_depth)

        # 2. Warmup check
        start_ts = self.history.get("pp_start_ts", ts)
        if (ts - start_ts) < self.MAF_WARMUP_TICKS:
            return 0

        # 3. Kill-switch
        fat_pp   = sig1.get("is_fat_tailed_pepper",  False)
        fat_os   = sig1.get("is_fat_tailed_osmium",  False)
        cusum_pp = sig1.get("cusum_break_pepper",    False)
        cusum_os = sig1.get("cusum_break_osmium",    False)

        # Kill if BOTH products are in a risk-off state simultaneously
        # (one risky product: reduce bid; both: don't bid at all)
        both_risky = (fat_pp or cusum_pp) and (fat_os or cusum_os)
        if both_risky:
            self.history["maf_last_bid"] = 0
            return 0

        # 4. Expected value estimation per product
        ev_total = 0.0
        any_edge = False

        for prod_key, limit_used in [("PEPPER", self.LIMIT), ("OSMIUM", self.LIMIT)]:
            buf = self.history.get(f"maf_edge_{prod_key}", [])
            if len(buf) < 5:
                continue
            any_edge = True
            mean_eu = float(np.mean(buf))
            # +25% volume on this product
            extra_units = limit_used * 0.25
            ev = mean_eu * extra_units

            # Scale down if this product has a risk flag
            if prod_key == "PEPPER" and (fat_pp or cusum_pp):
                ev *= 0.4
            if prod_key == "OSMIUM" and (fat_os or cusum_os):
                ev *= 0.4

            # VECM half-life gate: if mean reversion is slow, OSMIUM extra
            # volume is worth less (fewer spread captures per tick)
            if prod_key == "OSMIUM" and sig2.get("valid", False):
                hl = sig2.get("half_life", 30.0)
                if hl > 80:
                    ev *= 0.3   # slow reversion: extra size barely helps
                elif hl > 40:
                    ev *= 0.7

            ev_total += ev

        if not any_edge or ev_total <= 0:
            return 0

        # 5. Bid fraction of EV + adaptive adjustment
        raw_bid = ev_total * self.MAF_BID_FRACTION

        adapt = float(self.history.get("maf_adapt", 1.0))
        bid   = raw_bid * adapt

        # 6. Clamp
        bid = max(self.MAF_BID_MIN, min(self.MAF_BID_MAX, bid))
        bid_int = int(round(bid))

        # Persist bid for next tick's adaptation
        last_bid = self.history.get("maf_last_bid", None)
        if last_bid is not None and last_bid > 0:
            # Infer win/loss heuristic:
            # If our LIMIT hasn't changed we lost (no extra 25%).
            # We detect this by checking if actual traded qty exceeded LIMIT.
            # Since we don't have that signal directly, we adapt based on
            # bid trajectory: if bid has been rising many ticks → try ratcheting down.
            bid_hist = self.history.get("maf_bid_hist", [])
            bid_hist.append(bid_int)
            if len(bid_hist) > 20:
                bid_hist = bid_hist[-20:]
            self.history["maf_bid_hist"] = bid_hist

            # Simple trend: if last 5 bids were all lower than current, we've been
            # escalating → sign we keep losing → push adapt up (capped)
            if len(bid_hist) >= 5:
                recent = bid_hist[-5:]
                if all(b <= bid_int for b in recent[:-1]):
                    adapt = min(adapt * self.MAF_ADAPT_UP, 2.0)
                else:
                    adapt = max(adapt * self.MAF_ADAPT_DOWN, 0.5)
                self.history["maf_adapt"] = adapt

        self.history["maf_last_bid"] = bid_int
        logger.print(
            f"[MAF] bid={bid_int} | ev={ev_total:.1f} | adapt={adapt:.3f} "
            f"| fat_pp={fat_pp} cusum_pp={cusum_pp} "
            f"| fat_os={fat_os} cusum_os={cusum_os}"
        )
        return bid_int

    # =======================================================================
    # Entry point
    # =======================================================================

    def run(self, state: TradingState):
        self._load_state(state)

        # Phase I signals (uses price histories from last tick)
        sig1 = self._phase1_signals(
            pepper_prices = self.history.get("pp", []),
            osmium_prices = self.history.get("op", []),
        )

        # Phase II VECM (uses price histories from last tick)
        sig2 = self._phase2_vecm(
            pepper_prices = self.history.get("pp", []),
            osmium_prices = self.history.get("op", []),
            ts            = state.timestamp,
        )

        # Execute strategies (each appends to its own price history internally)
        result: Dict[str, List[Order]] = {}

        pep = self._pepper_logic(state, sig1)
        if pep:
            result["INTARIAN_PEPPER_ROOT"] = pep

        osm = self._osmium_logic(state, sig1, sig2)
        if osm:
            result["ASH_COATED_OSMIUM"] = osm

        # Phase III – MAF auction engine
        # Grab depth objects for edge recording (None-safe)
        pepper_depth = state.order_depths.get("INTARIAN_PEPPER_ROOT", None)
        osmium_depth = state.order_depths.get("ASH_COATED_OSMIUM",    None)

        maf = self._compute_maf(
            sig1          = sig1,
            sig2          = sig2,
            pepper_orders = result.get("INTARIAN_PEPPER_ROOT", []),
            osmium_orders = result.get("ASH_COATED_OSMIUM",    []),
            pepper_depth  = pepper_depth,
            osmium_depth  = osmium_depth,
            ts            = state.timestamp,
        )

        trader_data = self._save_state()
        logger.flush(state, result, maf, trader_data)

        # maf is returned as the third element (conversions slot).
        # The exchange interprets a non-zero value here as the MAF bid.
        return result, maf, trader_data