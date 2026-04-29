"""GOAT R4 trader_1 — counterparty-aware MM ($62.9k vs Ken's $25.3k on 3-day backtest)

Round 4 changes from R3:
- Counterparty IDs are now visible in market_trades (Mark 01 ... Mark 67).
- Voucher position limit 100 -> 300; HP/VFE unchanged (200).
- VEV TTE shifted: starts at 4 days (was 8 in R3).

COUNTERPARTY ANALYSIS (3 days of R4 historic data, ~4k trades):

  Product            Sharp (follow)         Dumb (fade)
  HYDROGEL_PACK      Mark 14 (+$8.0/u)      Mark 38 (-$7.9/u)
  VFE                Mark 14, Mark 01       Mark 55 (-$2.5/u)
  VEV_4000 (deep ITM)Mark 14 (+$10.4/u)     Mark 38 (-$10.4/u)
  VEV_5200..6500     Mark 01 (+$0.5/u)      Mark 22 (-$0.5/u)

Mark 14 alone has +$50k of edge across all products; Mark 38 has -$41k.

WHAT WORKS (kept):
- HP: V14 anchor-blended fair + Mark 14/38 bias  -> +$42.7k
- VFE: simple Ken-style MM (no delta hedge) + Mark bias -> +$8k
- Deep-ITM intrinsic MM on 4000/4500 (cap 100) + bias -> +$5.9k

WHAT DIDN'T (disabled):
- Pair trading 5000/5100 vs 5200/5300: bled -$17k. Smile fit unstable
  with shorter R4 TTE.
- Greeks-aware delta hedging: cost more in VFE round-trips than it saved
  in directional protection (-$10.5k on VFE).
- Smile passive MM on 5200-5500: net ~$0, removed for clarity.

COUNTERPARTY SIGNAL MECHANISM:
  bias = sum_over_recent_trades( edge_score(buyer) - edge_score(seller) ) * qty
  Each tick, signal *= 0.92 (decay). Bias applied to fair value.
  Stronger isn't better: HP=0.50 over-reacts, 0.30 is sweet spot.

3-DAY BACKTEST: $40,220 + $17,032 + $5,655 = $62,907 total
  (vs Ken's lamp.py: $12.4k + $4.5k + $8.3k = $25,280)
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def _bs_greeks(S: float, K: float, T: float, sigma: float) -> Tuple[float, float, float, float]:
    if T <= 1e-10 or sigma <= 1e-10:
        return (1.0 if S > K else 0.0), 0.0, 0.0, 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    delta = _norm_cdf(d1)
    gamma = _norm_pdf(d1) / (S * sigma * sqrt_T)
    vega = S * _norm_pdf(d1) * sqrt_T
    theta = -(S * _norm_pdf(d1) * sigma) / (2 * sqrt_T)
    return delta, gamma, vega, theta


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


# Counterparty edge profiles (calibrated from 3 days of R4 historic trade data).
# +1 = sharp (follow), -1 = dumb (fade). Magnitude reflects observed edge $/unit.
# Indexed first by product, then by counterparty name.
COUNTERPARTY_EDGE = {
    HYDROGEL: {
        "Mark 14": +1.0,   # +$8/u sharp
        "Mark 38": -1.0,   # -$8/u dumb
        "Mark 22": +0.4,   # tiny sharp on HP
    },
    VFE: {
        "Mark 14": +0.4,   # +$2.4/u sharp
        "Mark 01": +0.4,   # +$2.6/u sharp
        "Mark 49": +0.1,
        "Mark 55": -0.4,   # -$2.5/u dumb
        "Mark 67": -0.15,  # -$0.77/u dumb
    },
    "VEV_4000": {
        "Mark 14": +1.2,   # +$10/u sharp
        "Mark 38": -1.2,   # -$10/u dumb
    },
    "VEV_5200": {
        "Mark 14": +0.2,
        "Mark 01": +0.1,
        "Mark 22": -0.15,
    },
    "VEV_5300": {
        "Mark 01": +0.2,
        "Mark 22": -0.2,
    },
    "VEV_5400": {
        "Mark 01": +0.15,
        "Mark 14": +0.1,
        "Mark 22": -0.15,
    },
    "VEV_5500": {
        "Mark 01": +0.15,
        "Mark 14": +0.1,
        "Mark 22": -0.15,
    },
    "VEV_6000": {
        "Mark 01": +0.1,
        "Mark 22": -0.1,
    },
    "VEV_6500": {
        "Mark 01": +0.1,
        "Mark 22": -0.1,
    },
}

# Per-product fair-value bias scale: $ per unit of accumulated signal.
# Larger for products where the alpha is bigger ($8-10 on HP/VEV_4000).
SIGNAL_BIAS_SCALE = {
    HYDROGEL: 0.30,        # 0.50 over-reacts; 0.30 sweet spot for HP +$42k
    VFE: 0.10,             # 0.20 caused -$27k Day 3 directional blowup
    "VEV_4000": 0.20,
    "VEV_4500": 0.10,
    "VEV_5200": 0.05,
    "VEV_5300": 0.05,
    "VEV_5400": 0.04,
    "VEV_5500": 0.04,
    "VEV_6000": 0.02,
    "VEV_6500": 0.02,
}

SIGNAL_DECAY = 0.92        # per-tick exponential decay (~30-tick half-life)
SIGNAL_CLAMP = 30.0        # max abs signal


class Trader:
    LIMITS = {HYDROGEL: 200, VFE: 200, **{s: 300 for s in VEV_SYMBOLS}}

    # HYDROGEL (Ken's exact — proven $42k/3-day generator)
    HP_ANCHOR = 9991.0
    HP_BLEND = 0.8
    HP_EWMA_ALPHA = 0.20
    HP_VOL_ALPHA = 0.10
    HP_TAKE_EDGE = 1
    HP_QUOTE_SIZE = 85

    # VFE — simplified Ken-style MM (no delta target). Lighter, slower, with
    # counterparty bias. Original V14 maker_max=128 + taker bled -$7.7k in R4.
    VFE_EWMA_ALPHA = 0.30
    VFE_MAKER_EDGE = 2          # Wider than V14's 0.9 — give market more room
    VFE_TAKER_EDGE = 2.5        # Less aggressive taking
    VFE_TAKER_MAX = 12          # Small clips
    VFE_MAKER_MAX = 18
    VFE_MICRO_TILT = 0.20
    VFE_MOMO_K = 0.20           # momentum tilt
    VFE_POS_SOFT_CAP = 80       # soft cap on quoting size by abs position

    # VEV cross-strike RV — DISABLED for R4 (lost -$17k in backtest;
    # short TTE + counterparty-driven smile makes pair-trade unstable).
    VEV_TTE_START = 4.0       # R4: VEV_5000 starts at TTE=4 days
    VEV_DAY_INIT = 0
    VEV_FIT_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
    VEV_PAIR_ENABLE = False   # KILL pair trading
    VEV_ENTRY_MISPRICING = 1.5
    VEV_EXIT_MISPRICING = 0.3
    VEV_PAIR_MAX_QTY = 30
    VEV_PAIR_CAP_PER_STRIKE = 80
    VEV_GLOBAL_ABS_CAP = 700
    VEV_PHASE_SWITCH_TS = 140_000
    VEV_PHASE2_CAP_SCALE = 0.9
    VEV_PHASE2_ENTRY_BUMP = 0.35
    VEV_DECAY_CLIP = 6

    # Greeks
    VEV_USE_LIVE_DELTA = True
    VEV_DELTA_HEDGE_ENABLE = False      # Hedging cost more than directional saves
    VEV_DELTA_HEDGE_ITM_ONLY = True
    VEV_GAMMA_SIZE_MULT_MIN = 0.6
    VEV_GAMMA_SIZE_MULT_MAX = 1.4
    VEV_VEGA_ENTRY_BUMP_MIN = 0.0
    VEV_VEGA_ENTRY_BUMP_MAX = 0.6
    VEV_THETA_EXIT_WEIGHT = 0.02
    VFE_SPREAD_HEDGE_PENALTY = 0.15

    # Smile passive MM — net negative in backtest, disable
    SMM_ENABLE = False
    SMM_STRIKES = [5200, 5300, 5400, 5500]
    SMM_EDGE = 0.5
    SMM_QTY = 35
    SMM_POS_CAP = 130
    SMM_SKEW_FACTOR = 0.3

    # Deep-ITM intrinsic. cap=80 too tight (-$12k), cap=150 too loose on day 3.
    ITM_ENABLE = True
    ITM_STRIKES = [4000, 4500]
    ITM_EDGE = 1
    ITM_QUOTE_SIZE = 40
    ITM_POS_CAP = 100

    DELTA_APPROX: Dict[int, float] = {
        4000: 1.00, 4500: 0.98, 5000: 0.82, 5100: 0.70, 5200: 0.57,
        5300: 0.44, 5400: 0.31, 5500: 0.21, 6000: 0.10, 6500: 0.05,
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
        self.history.setdefault("last_vfe_pos", 0)
        self.history.setdefault("vfe_speed_cooldown_until", -1)
        self.history.setdefault("day_index", self.VEV_DAY_INIT)
        self.history.setdefault("last_ts", -1)
        self.history.setdefault("mark_signal", {})  # product -> accumulated signal

    def _save(self) -> str:
        return json.dumps(self.history)

    def _update_day(self, ts: int) -> None:
        last = int(self.history.get("last_ts", -1))
        if last >= 0 and ts < last:
            self.history["day_index"] = int(self.history.get("day_index", self.VEV_DAY_INIT)) + 1
        self.history["last_ts"] = ts

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

    # ---------- Counterparty signal ----------
    def _update_mark_signals(self, state: TradingState) -> None:
        """Decay existing signals and add fresh observations from this tick."""
        signals: Dict[str, float] = self.history.get("mark_signal", {})

        # Decay
        decayed: Dict[str, float] = {}
        for prod, s in signals.items():
            d = s * SIGNAL_DECAY
            if abs(d) > 0.05:
                decayed[prod] = d
        signals = decayed

        # Apply new trades from market_trades
        market_trades = getattr(state, "market_trades", {}) or {}
        for sym, trades in market_trades.items():
            edges = COUNTERPARTY_EDGE.get(sym)
            if not edges:
                continue
            if not trades:
                continue
            s = signals.get(sym, 0.0)
            for t in trades:
                buyer = getattr(t, "buyer", None) or ""
                seller = getattr(t, "seller", None) or ""
                qty = abs(getattr(t, "quantity", 0))
                if qty <= 0:
                    continue
                # If buyer is sharp -> bullish (s += w*qty). If buyer dumb -> bearish.
                # If seller is sharp -> bearish. If seller dumb -> bullish.
                bw = edges.get(buyer, 0.0)
                sw = edges.get(seller, 0.0)
                s += bw * qty - sw * qty
            if abs(s) < 0.05:
                signals.pop(sym, None)
            else:
                signals[sym] = max(-SIGNAL_CLAMP, min(SIGNAL_CLAMP, s))

        self.history["mark_signal"] = signals

    def _bias(self, sym: str) -> float:
        s = self.history.get("mark_signal", {}).get(sym, 0.0)
        return s * SIGNAL_BIAS_SCALE.get(sym, 0.0)

    # ---------- HP ----------
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

        # V16 base fair + counterparty bias
        fair = self.HP_BLEND * ewma + (1 - self.HP_BLEND) * self.HP_ANCHOR + self._bias(HYDROGEL)

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

    def _vfe(self, state: TradingState, target_pos: int) -> List[Order]:
        """Simple VFE MM with EWMA fair, momentum tilt, counterparty bias.
        Ignores target_pos (kept for signature compat) since delta hedging is off."""
        if VFE not in state.order_depths:
            return []
        od = state.order_depths[VFE]
        bb, ba, _, _ = self._top(od)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0

        prev = self.history.get("vfe_ewma")
        ewma = mid if prev is None else (1 - self.VFE_EWMA_ALPHA) * prev + self.VFE_EWMA_ALPHA * mid
        self.history["vfe_ewma"] = ewma

        last_mid = self.history.get("vfe_last_mid", mid)
        momo = mid - last_mid
        self.history["vfe_last_mid"] = mid

        fair = ewma + self.VFE_MOMO_K * momo + self._bias(VFE)
        pos = state.position.get(VFE, 0)
        lim = self.LIMITS[VFE]
        orders: List[Order] = []

        # Take when price clearly favorable
        if ba <= fair - self.VFE_TAKER_EDGE and pos < lim:
            qty = min(self.VFE_TAKER_MAX, -od.sell_orders[ba], lim - pos)
            if qty > 0:
                orders.append(Order(VFE, ba, qty))
                pos += qty
        if bb >= fair + self.VFE_TAKER_EDGE and pos > -lim:
            qty = min(self.VFE_TAKER_MAX, od.buy_orders[bb], lim + pos)
            if qty > 0:
                orders.append(Order(VFE, bb, -qty))
                pos -= qty

        # Light maker quote with inventory skew (no target chase — pure MM)
        skew = -0.04 * pos          # tilt fair against inventory
        qbid = int(round(fair + skew - self.VFE_MAKER_EDGE))
        qask = int(round(fair + skew + self.VFE_MAKER_EDGE))
        if qbid >= ba:
            qbid = ba - 1
        if qask <= bb:
            qask = bb + 1
        if qbid >= qask:
            qbid = qask - 1

        # Reduce quote size as we approach soft cap
        size_mult = max(0.0, 1.0 - max(0, abs(pos) - self.VFE_POS_SOFT_CAP) / max(1, lim - self.VFE_POS_SOFT_CAP))
        maker = max(4, int(self.VFE_MAKER_MAX * size_mult))
        if lim - pos > 0 and pos < lim:
            orders.append(Order(VFE, qbid, min(maker, lim - pos)))
        if lim + pos > 0 and pos > -lim:
            orders.append(Order(VFE, qask, -min(maker, lim + pos)))
        return orders

    def _vev(self, state: TradingState):
        if VFE not in state.order_depths:
            return [], None, None, None
        S = self._mid(state.order_depths[VFE])
        if S is None:
            return [], None, None, None
        # Apply VFE counterparty bias to S used in option pricing
        S_eff = S + self._bias(VFE)
        day = int(self.history.get("day_index", self.VEV_DAY_INIT))
        T = max(0.05, (self.VEV_TTE_START - day) - state.timestamp / TS_PER_DAY)
        phase2 = int(state.timestamp) >= self.VEV_PHASE_SWITCH_TS
        cap_scale = self.VEV_PHASE2_CAP_SCALE if phase2 else 1.0
        entry = self.VEV_ENTRY_MISPRICING + (self.VEV_PHASE2_ENTRY_BUMP if phase2 else 0.0)
        per_cap = int(self.VEV_PAIR_CAP_PER_STRIKE * cap_scale)
        global_cap = int(self.VEV_GLOBAL_ABS_CAP * cap_scale)

        fit_iv: Dict[int, float] = {}
        for k in self.VEV_FIT_STRIKES:
            sym = f"VEV_{k}"
            od = state.order_depths.get(sym)
            if not od:
                continue
            m = self._mid(od)
            if m and m > 0:
                iv = iv_solve(m, S_eff, k, T)
                if iv is not None:
                    fit_iv[k] = iv
        if len(fit_iv) < 4:
            return [], None, S_eff, T

        pts = [(math.log(x / S_eff), fit_iv[x]) for x in fit_iv]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        smile_coefs = _solve_3x3(
            [[sum(x**4 for x in xs), sum(x**3 for x in xs), sum(x**2 for x in xs)],
             [sum(x**3 for x in xs), sum(x**2 for x in xs), sum(x for x in xs)],
             [sum(x**2 for x in xs), sum(x for x in xs), len(xs)]],
            [sum(x**2 * y for x, y in zip(xs, ys)), sum(x * y for x, y in zip(xs, ys)), sum(ys)]
        )
        if not smile_coefs:
            return [], None, S_eff, T

        mis: Dict[int, float] = {}
        top: Dict[int, Tuple[Optional[int], Optional[int], int, int]] = {}
        greeks: Dict[int, Tuple[float, float, float, float]] = {}
        for k in self.VEV_FIT_STRIKES:
            sym = f"VEV_{k}"
            od = state.order_depths.get(sym)
            if not od:
                continue
            bb, ba, bv, av = self._top(od)
            if bb is None or ba is None:
                continue
            mny = math.log(k / S_eff)
            iv_k = smile_coefs[0] * mny * mny + smile_coefs[1] * mny + smile_coefs[2]
            fair = bs_call(S_eff, k, T, iv_k)
            mid = 0.5 * (bb + ba)
            mis[k] = mid - fair
            top[k] = (bb, ba, bv, av)
            greeks[k] = _bs_greeks(S_eff, k, T, iv_k)

        orders: List[Order] = []
        abs_pos = sum(abs(state.position.get(f"VEV_{k}", 0)) for k in self.VEV_FIT_STRIKES)
        low_bucket = [k for k in (5000, 5100) if k in mis]
        high_bucket = [k for k in (5200, 5300) if k in mis]

        if self.VEV_PAIR_ENABLE and low_bucket and high_bucket:
            cheap_k = min(low_bucket, key=lambda k: mis[k])
            rich_k = max(high_bucket, key=lambda k: mis[k])

            vfe_od = state.order_depths[VFE]
            vbb, vba, _, _ = self._top(vfe_od)
            v_spread = (vba - vbb) if (vba is not None and vbb is not None) else 1.0

            avg_vega = (greeks[cheap_k][2] + greeks[rich_k][2]) / 2.0
            vega_bump = max(self.VEV_VEGA_ENTRY_BUMP_MIN,
                            min(self.VEV_VEGA_ENTRY_BUMP_MAX,
                                (avg_vega / 500.0) * v_spread * self.VFE_SPREAD_HEDGE_PENALTY))
            eff_entry = entry + vega_bump

            if mis[cheap_k] <= -eff_entry and mis[rich_k] >= eff_entry:
                cheap_sym, rich_sym = f"VEV_{cheap_k}", f"VEV_{rich_k}"
                cheap_od, rich_od = state.order_depths[cheap_sym], state.order_depths[rich_sym]
                cbb, cba, _, _ = top[cheap_k]
                rbb, rba, _, _ = top[rich_k]
                if cba is not None and rbb is not None:
                    avg_gamma = (greeks[cheap_k][1] + greeks[rich_k][1]) / 2.0
                    gamma_mult = max(self.VEV_GAMMA_SIZE_MULT_MIN,
                                     min(self.VEV_GAMMA_SIZE_MULT_MAX,
                                         avg_gamma / 0.0005))
                    eff_qty = int(round(self.VEV_PAIR_MAX_QTY * gamma_mult))
                    cheap_pos = state.position.get(cheap_sym, 0)
                    rich_pos = state.position.get(rich_sym, 0)
                    buy_room = min(per_cap - cheap_pos, -cheap_od.sell_orders[cba])
                    sell_room = min(per_cap + rich_pos, rich_od.buy_orders[rbb])
                    budget = global_cap - abs_pos
                    q = min(eff_qty, buy_room, sell_room, budget)
                    if q > 0:
                        orders.append(Order(cheap_sym, cba, q))
                        orders.append(Order(rich_sym, rbb, -q))
                        abs_pos += 2 * q

        if phase2:
            for k, v in mis.items():
                sym = f"VEV_{k}"
                pos = state.position.get(sym, 0)
                if pos == 0:
                    continue
                bb, ba, _, _ = top[k]
                od = state.order_depths[sym]
                th = greeks[k][3]
                th_adj = -(pos / 100.0) * th * self.VEV_THETA_EXIT_WEIGHT
                eff_exit = self.VEV_EXIT_MISPRICING + th_adj
                if pos > 0 and bb is not None and v >= -eff_exit:
                    q = min(pos, od.buy_orders[bb], self.VEV_DECAY_CLIP)
                    if q > 0:
                        orders.append(Order(sym, bb, -q))
                elif pos < 0 and ba is not None and v <= eff_exit:
                    q = min(-pos, -od.sell_orders[ba], self.VEV_DECAY_CLIP)
                    if q > 0:
                        orders.append(Order(sym, ba, q))

        return orders, smile_coefs, S_eff, T

    def _target_vfe_from_delta(self, state: TradingState, smile_coefs, S: float, T: float) -> int:
        """Compute VFE position needed to hedge net delta of option holdings.
        ITM-only mode: only consider 4000/4500 (delta ~1), since the smile-MM
        positions are intentionally short-lived and cheaper to leave un-hedged."""
        strikes = self.ITM_STRIKES if self.VEV_DELTA_HEDGE_ITM_ONLY else VEV_STRIKES
        net_delta = 0.0
        for k in strikes:
            pos = state.position.get(f"VEV_{k}", 0)
            if pos == 0:
                continue
            delta = self.DELTA_APPROX.get(k, 0.5)
            if self.VEV_USE_LIVE_DELTA and smile_coefs and S > 0 and T > 0:
                mny = math.log(k / S)
                iv_k = smile_coefs[0] * mny * mny + smile_coefs[1] * mny + smile_coefs[2]
                iv_k = max(0.01, min(2.0, iv_k))
                d, _, _, _ = _bs_greeks(S, k, T, iv_k)
                delta = d
            net_delta += pos * delta
        lim = self.LIMITS[VFE]
        return max(-lim, min(lim, int(round(-net_delta))))

    def _vev_smile_mm(self, state: TradingState, smile_coefs, S: float, T: float) -> List[Order]:
        if not self.SMM_ENABLE or smile_coefs is None or S is None or S <= 0:
            return []
        orders: List[Order] = []
        for k in self.SMM_STRIKES:
            sym = f"VEV_{k}"
            od = state.order_depths.get(sym)
            if not od:
                continue
            bb, ba, _, _ = self._top(od)
            if bb is None or ba is None:
                continue
            mny = math.log(k / S)
            iv_k = smile_coefs[0] * mny * mny + smile_coefs[1] * mny + smile_coefs[2]
            if iv_k <= 0.01:
                continue
            fair = bs_call(S, k, T, iv_k) + self._bias(sym)
            pos = state.position.get(sym, 0)
            lim = self.LIMITS[sym]
            skew = self.SMM_SKEW_FACTOR * (pos / max(self.SMM_POS_CAP, 1))
            bid_px = int(math.floor(fair - self.SMM_EDGE - skew))
            if bid_px >= ba:
                bid_px = ba - 1
            if bid_px >= 1 and pos < self.SMM_POS_CAP and pos < lim:
                qty = min(self.SMM_QTY, self.SMM_POS_CAP - pos, lim - pos)
                if qty > 0:
                    orders.append(Order(sym, bid_px, qty))
            ask_px = int(math.ceil(fair + self.SMM_EDGE - skew))
            if ask_px <= bb:
                ask_px = bb + 1
            if ask_px >= 1 and pos > -self.SMM_POS_CAP and pos > -lim:
                qty = min(self.SMM_QTY, self.SMM_POS_CAP + pos, lim + pos)
                if qty > 0:
                    orders.append(Order(sym, ask_px, -qty))
        return orders

    def _vev_itm(self, state: TradingState, S: Optional[float]) -> List[Order]:
        if not self.ITM_ENABLE or S is None or S <= 0:
            return []
        orders: List[Order] = []
        for k in self.ITM_STRIKES:
            sym = f"VEV_{k}"
            od = state.order_depths.get(sym)
            if not od:
                continue
            bb, ba, _, _ = self._top(od)
            if bb is None or ba is None:
                continue
            intrinsic = max(0.0, S - k)
            # Counterparty bias: for VEV_4000 Mark 14/38 give us a real signal
            biased_intrinsic = intrinsic + self._bias(sym)
            pos = state.position.get(sym, 0)
            lim = self.LIMITS[sym]
            if ba <= biased_intrinsic and pos < self.ITM_POS_CAP:
                qty = min(-od.sell_orders[ba], self.ITM_POS_CAP - pos, lim - pos)
                if qty > 0:
                    orders.append(Order(sym, ba, qty))
                    pos += qty
            if bb >= biased_intrinsic + self.ITM_EDGE + 1 and pos > -self.ITM_POS_CAP:
                qty = min(od.buy_orders[bb], self.ITM_POS_CAP + pos, lim + pos)
                if qty > 0:
                    orders.append(Order(sym, bb, -qty))
                    pos -= qty
            bid_px = int(math.floor(biased_intrinsic))
            ask_px = int(math.ceil(biased_intrinsic + self.ITM_EDGE + 1))
            if bid_px >= ba:
                bid_px = ba - 1
            if ask_px <= bb:
                ask_px = bb + 1
            if bid_px >= 1 and pos < self.ITM_POS_CAP:
                qty = min(self.ITM_QUOTE_SIZE, self.ITM_POS_CAP - pos, lim - pos)
                if qty > 0:
                    orders.append(Order(sym, bid_px, qty))
            if pos > -self.ITM_POS_CAP:
                qty = min(self.ITM_QUOTE_SIZE, self.ITM_POS_CAP + pos, lim + pos)
                if qty > 0:
                    orders.append(Order(sym, ask_px, -qty))
        return orders

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._load(state)
        self._update_day(int(state.timestamp))
        self._update_mark_signals(state)
        result: Dict[str, List[Order]] = {}

        hp_orders = self._hp(state)
        if hp_orders:
            result[HYDROGEL] = hp_orders

        vev_orders, smile_coefs, S, T = self._vev(state)
        for o in vev_orders:
            result.setdefault(o.symbol, []).append(o)

        if S is not None:
            smm_orders = self._vev_smile_mm(state, smile_coefs, S, T)
            for o in smm_orders:
                result.setdefault(o.symbol, []).append(o)
            itm_orders = self._vev_itm(state, S)
            for o in itm_orders:
                result.setdefault(o.symbol, []).append(o)

        vfe_od = state.order_depths.get(VFE)
        if S is None:
            S = self._mid(vfe_od) if vfe_od else None
        day = int(self.history.get("day_index", self.VEV_DAY_INIT))
        if T is None:
            T = max(0.05, (self.VEV_TTE_START - day) - state.timestamp / TS_PER_DAY)

        if S is not None and self.VEV_DELTA_HEDGE_ENABLE:
            target_vfe = self._target_vfe_from_delta(state, smile_coefs, S, T)
        else:
            target_vfe = 0
        vfe_orders = self._vfe(state, target_vfe)
        if vfe_orders:
            result[VFE] = vfe_orders

        return result, 0, self._save()
