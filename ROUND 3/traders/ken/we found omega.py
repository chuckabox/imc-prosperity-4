"""we found omega.py — successor to epsilon, voucher P&L upgrade.

What changed vs epsilon (HP + VFE logic preserved as-is):
  1. Gamma-weighted RV pair size  (alphas.md #5)
       qty *= clip(avg_gamma / target, [0.5, 1.7])
  2. Vega-aware entry hurdle      (alphas.md #6)
       entry_eff = entry + max_vega * vfe_spread * penalty
  3. Theta-aware exits            (alphas.md #8 — proven 1612 → 1710)
       eff_exit_long  = -EXIT + (|pos|/100) * theta_decay * weight  (tighter)
       eff_exit_short = +EXIT + (|pos|/100) * theta_decay * weight  (looser)
       Now runs every tick, not just phase 2.
  4. Multi-pair RV, up to 2 non-overlapping pairs per tick.  Picks by
     extreme mispricing rather than the hard-coded {5000,5100} ↔
     {5200,5300} buckets, and only requires 200-strike separation.
  5. Smile-wide passive maker on all 6 fit strikes at smile_fair ± edge,
     skipping any strike that just got an RV trade.  Adds spread-capture
     income (alphas.md "future roadmap" item).
  6. Static call-spread no-arbitrage check across adjacent fit strikes.
     Hits if best_bid(K1) − best_ask(K2) ≥ (K2 − K1) + min_edge, or the
     monotonicity violation best_ask(K1) < best_bid(K2).  Rare but free.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState


# ===========================================================================
# Black-Scholes helpers
# ===========================================================================
_SQRT_2PI_INV = 1.0 / math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return _SQRT_2PI_INV * math.exp(-0.5 * x * x)


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def bs_gamma(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10 or S <= 0.0:
        return 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    return _norm_pdf(d1) / (S * sigma * sqrt_T)


def bs_vega(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10 or S <= 0.0:
        return 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    return S * _norm_pdf(d1) * sqrt_T


def bs_theta_decay(S: float, K: float, T: float, sigma: float) -> float:
    """Daily theta decay magnitude (positive). Long pos loses this/day."""
    if T <= 1e-10 or sigma <= 1e-10 or S <= 0.0:
        return 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    return S * _norm_pdf(d1) * sigma / (2.0 * sqrt_T)


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


class Trader:
    LIMITS = {HYDROGEL: 200, VFE: 200, **{s: 100 for s in VEV_SYMBOLS}}

    # HYDROGEL — epsilon + peter OBI skew
    HP_ANCHOR = 9991.0
    HP_BLEND = 0.8
    HP_EWMA_ALPHA = 0.20
    HP_VOL_ALPHA = 0.10
    HP_TAKE_EDGE = 1
    HP_QUOTE_SIZE = 85
    HP_OBI_THRESHOLD = 0.7              # |OBI| > 0.7 → skew fair (peter)
    HP_OBI_SKEW = 1

    # VFE — epsilon + peter lag-1 asymm + whale fade
    VFE_EWMA_ALPHA = 0.3
    VFE_MAKER_EDGE = 0.9
    VFE_TAKER_EDGE = 1.6
    VFE_TAKER_MAX = 64
    VFE_MICRO_TILT = 0.24
    VFE_HEDGE_BAND = 10
    VFE_HEDGE_AGGRO_BAND = 40
    VFE_HEDGE_MAX = 64
    OPEN_PHASE_TS = 100_000
    VFE_SPEED_TRIGGER = 54
    VFE_BIG_MOVE = 2.0                  # |Δmid| ≥ 2 = asymm quote next tick
    VFE_ASYMM_BUMP = 1                  # widen the side that's about to revert away from us
    VFE_WHALE_QTY = 30                  # market_trade size = whale
    VFE_WHALE_FADE_SIZE = 6
    VFE_WHALE_TTL_TICKS = 5
    SPEED_COOLDOWN_TS = 40_000
    OPEN_SCALE_MULT = 1.0
    SPEED_SCALE_MULT = 0.82

    # VEV core — same as epsilon
    VEV_TTE_START = 8.0
    VEV_DAY_INIT = 2
    VEV_FIT_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
    VEV_ENTRY_MISPRICING = 0.9
    VEV_EXIT_MISPRICING = 0.3
    VEV_PAIR_MAX_QTY = 22
    VEV_PAIR_CAP_PER_STRIKE = 45
    VEV_GLOBAL_ABS_CAP = 420
    VEV_PHASE_SWITCH_TS = 140_000
    VEV_PHASE2_CAP_SCALE = 0.9
    VEV_PHASE2_ENTRY_BUMP = 0.35
    VEV_DECAY_CLIP = 4

    # NEW VEV alphas (omega)
    VEV_GAMMA_TARGET = 0.0025          # baseline ATM gamma — pair size scales by avg_gamma / this
    VEV_GAMMA_SCALE_MIN = 0.5
    VEV_GAMMA_SCALE_MAX = 1.7
    VEV_VEGA_PENALTY = 1.5e-5          # vega × vfe_spread × penalty → entry hurdle bump
    VEV_THETA_EXIT_WEIGHT = 0.035      # eff_exit shift = (|pos|/100) × theta_decay × weight
    VEV_MAX_PAIRS_PER_TICK = 2
    VEV_MIN_PAIR_STRIKE_GAP = 200      # cheap & rich legs at least 200 apart
    VEV_PASSIVE_SIZE = 4
    VEV_PASSIVE_EDGE = 1.6
    VEV_PASSIVE_PER_STRIKE_CAP = 30
    VEV_NOARB_MIN_EDGE = 1.0           # min XIRECs over no-arb violation to lock arb
    VEV_NOARB_MAX_QTY = 6

    DELTA_APPROX: Dict[int, float] = {
        4000: 1.00, 4500: 0.98, 5000: 0.82, 5100: 0.70, 5200: 0.57,
        5300: 0.44, 5400: 0.31, 5500: 0.21, 6000: 0.10, 6500: 0.05,
    }

    # ----------------------------------------------------------------------
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
        self.history.setdefault("last_vfe_mid", None)
        self.history.setdefault("whale_until", -1)
        self.history.setdefault("whale_dir", 0)

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

    # ---- HYDROGEL (epsilon, unchanged) -----------------------------------
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

        # Peter alpha: OBI skew on top of anchor-blended fair.
        bb, ba, bv, av = self._top(od)
        total_v = bv + av
        obi = (bv - av) / total_v if total_v > 0 else 0.0
        obi_skew = 0
        if obi > self.HP_OBI_THRESHOLD:
            obi_skew = self.HP_OBI_SKEW
        elif obi < -self.HP_OBI_THRESHOLD:
            obi_skew = -self.HP_OBI_SKEW
        fair = self.HP_BLEND * ewma + (1 - self.HP_BLEND) * self.HP_ANCHOR + obi_skew
        pos = state.position.get(HYDROGEL, 0)
        lim = self.LIMITS[HYDROGEL]
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

    def _in_open_phase(self, state: TradingState) -> bool:
        return int(state.timestamp) <= self.OPEN_PHASE_TS

    def _speed_limited_vfe(self, state: TradingState) -> bool:
        now = int(state.timestamp)
        pos = int(state.position.get(VFE, 0))
        last_pos = int(self.history.get("last_vfe_pos", 0))
        if abs(pos - last_pos) >= self.VFE_SPEED_TRIGGER:
            self.history["vfe_speed_cooldown_until"] = now + self.SPEED_COOLDOWN_TS
        self.history["last_vfe_pos"] = pos
        return now < int(self.history.get("vfe_speed_cooldown_until", -1))

    def _detect_whale(self, state: TradingState, ts: int, last_mid: Optional[float]) -> int:
        """Returns +1 (expect up), -1 (expect down), 0 (none).
        Detects market_trade on VFE with |qty| ≥ VFE_WHALE_QTY in this tick.
        Side inferred by trade price vs last mid: lift offer → expect short
        revert (return -1 to fade), hit bid → expect bounce (+1).  Signal
        persists VFE_WHALE_TTL_TICKS × 100 timestamp units.
        """
        whale_until = int(self.history.get("whale_until", -1))
        whale_dir = int(self.history.get("whale_dir", 0))
        if ts >= whale_until:
            whale_dir = 0
        trades = state.market_trades.get(VFE, []) if state.market_trades else []
        for t in trades:
            if abs(t.quantity) >= self.VFE_WHALE_QTY and last_mid is not None:
                whale_dir = -1 if t.price >= last_mid else +1
                whale_until = ts + self.VFE_WHALE_TTL_TICKS * 100
                break
        self.history["whale_until"] = whale_until
        self.history["whale_dir"] = whale_dir
        return whale_dir

    # ---- VFE (epsilon + peter lag-1 + whale fade) ------------------------
    def _vfe(self, state: TradingState, target_pos: int) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        od = state.order_depths[VFE]
        bb, ba, bv, av = self._top(od)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0
        prev = self.history.get("vfe_ewma")
        ewma = mid if prev is None else (1 - self.VFE_EWMA_ALPHA) * prev + self.VFE_EWMA_ALPHA * mid
        self.history["vfe_ewma"] = ewma
        micro = (bb * av + ba * bv) / (bv + av) if (bv + av) > 0 else mid
        fair = (1.0 - self.VFE_MICRO_TILT) * ewma + self.VFE_MICRO_TILT * micro

        # Peter alphas: lag-1 negative autocorr + whale fade.
        last_mid = self.history.get("last_vfe_mid")
        big_move = 0
        if last_mid is not None:
            d = mid - float(last_mid)
            if d >= self.VFE_BIG_MOVE:
                big_move = +1
            elif d <= -self.VFE_BIG_MOVE:
                big_move = -1
        whale = self._detect_whale(state, int(state.timestamp), last_mid)
        bias = -big_move + whale     # negative = expect down, positive = expect up
        self.history["last_vfe_mid"] = mid

        local_scale = 1.0
        if self._in_open_phase(state):
            local_scale *= self.OPEN_SCALE_MULT
        if self._speed_limited_vfe(state):
            local_scale *= self.SPEED_SCALE_MULT
        pos = state.position.get(VFE, 0)
        lim = self.LIMITS[VFE]
        orders: List[Order] = []
        residual = target_pos - pos
        if abs(residual) >= self.VFE_HEDGE_BAND:
            hmx = max(8, int(self.VFE_HEDGE_MAX * local_scale))
            if residual > 0 and pos < lim:
                hq = min(hmx, residual, lim - pos, -od.sell_orders[ba])
                if hq > 0:
                    orders.append(Order(VFE, ba, hq))
                    pos += hq
            elif residual < 0 and pos > -lim:
                hq = min(hmx, -residual, lim + pos, od.buy_orders[bb])
                if hq > 0:
                    orders.append(Order(VFE, bb, -hq))
                    pos -= hq
        taker_max = max(10, int(self.VFE_TAKER_MAX * local_scale * 1.15))
        if abs(target_pos - pos) <= self.VFE_HEDGE_AGGRO_BAND:
            rem = taker_max
            for ask in sorted(od.sell_orders):
                if ask > fair - self.VFE_TAKER_EDGE or rem <= 0 or pos >= lim:
                    break
                qty = min(-od.sell_orders[ask], lim - pos, rem)
                if qty > 0:
                    orders.append(Order(VFE, ask, qty))
                    pos += qty
                    rem -= qty
            rem = taker_max
            for bid in sorted(od.buy_orders, reverse=True):
                if bid < fair + self.VFE_TAKER_EDGE or rem <= 0 or pos <= -lim:
                    break
                qty = min(od.buy_orders[bid], lim + pos, rem)
                if qty > 0:
                    orders.append(Order(VFE, bid, -qty))
                    pos -= qty
                    rem -= qty
        # Asymmetric edge: widen the side that's about to revert away from
        # us, hold the side that's about to revert toward us (peter alpha).
        bid_widen = self.VFE_ASYMM_BUMP if bias < 0 else 0
        ask_widen = self.VFE_ASYMM_BUMP if bias > 0 else 0
        # Whale fade: small market-order opposite the whale direction.
        if whale > 0 and pos < lim:
            sz = min(self.VFE_WHALE_FADE_SIZE, lim - pos, -od.sell_orders[ba])
            if sz > 0:
                orders.append(Order(VFE, ba, sz))
                pos += sz
        elif whale < 0 and pos > -lim:
            sz = min(self.VFE_WHALE_FADE_SIZE, lim + pos, od.buy_orders[bb])
            if sz > 0:
                orders.append(Order(VFE, bb, -sz))
                pos -= sz

        qbid = int(round(fair - self.VFE_MAKER_EDGE - bid_widen))
        qask = int(round(fair + self.VFE_MAKER_EDGE + ask_widen))
        if qbid >= ba:
            qbid = ba - 1
        if qask <= bb:
            qask = bb + 1
        if qbid >= qask:
            qbid = qask - 1
        maker_max = max(30, int(128 * local_scale))
        if lim - pos > 0:
            orders.append(Order(VFE, qbid, min(lim - pos, maker_max)))
        if lim + pos > 0:
            orders.append(Order(VFE, qask, -min(lim + pos, maker_max)))
        return orders

    # ----------------------------------------------------------------------
    # VEV — omega upgrades
    # ----------------------------------------------------------------------
    def _vev(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        S = self._mid(state.order_depths[VFE])
        if S is None:
            return []

        # VFE spread for vega hurdle
        vfe_bb, vfe_ba, _, _ = self._top(state.order_depths[VFE])
        vfe_spread = (vfe_ba - vfe_bb) if (vfe_bb is not None and vfe_ba is not None) else 5

        day = int(self.history.get("day_index", self.VEV_DAY_INIT))
        T = max(0.5, (self.VEV_TTE_START - day) - state.timestamp / TS_PER_DAY)
        phase2 = int(state.timestamp) >= self.VEV_PHASE_SWITCH_TS
        cap_scale = self.VEV_PHASE2_CAP_SCALE if phase2 else 1.0
        entry = self.VEV_ENTRY_MISPRICING + (self.VEV_PHASE2_ENTRY_BUMP if phase2 else 0.0)
        per_cap = int(self.VEV_PAIR_CAP_PER_STRIKE * cap_scale)
        global_cap = int(self.VEV_GLOBAL_ABS_CAP * cap_scale)

        # 1. Strike-by-strike implied vols
        fit_iv: Dict[int, float] = {}
        for k in self.VEV_FIT_STRIKES:
            sym = f"VEV_{k}"
            od = state.order_depths.get(sym)
            if not od:
                continue
            m = self._mid(od)
            if m and m > 0:
                iv = iv_solve(m, S, k, T)
                if iv is not None:
                    fit_iv[k] = iv
        if len(fit_iv) < 4:
            return []

        # 2. Leave-one-out smile fit → mispricing per strike + Greeks
        mis: Dict[int, float] = {}
        smile_fair: Dict[int, float] = {}
        gamma_k: Dict[int, float] = {}
        vega_k: Dict[int, float] = {}
        theta_k: Dict[int, float] = {}
        top: Dict[int, Tuple[Optional[int], Optional[int], int, int]] = {}
        for k in self.VEV_FIT_STRIKES:
            sym = f"VEV_{k}"
            od = state.order_depths.get(sym)
            if not od:
                continue
            bb, ba, bv, av = self._top(od)
            if bb is None or ba is None:
                continue
            others = [x for x in self.VEV_FIT_STRIKES if x != k and x in fit_iv]
            if len(others) < 4:
                continue
            xs = [math.log(x / S) for x in others]
            ys = [fit_iv[x] for x in others]
            n = len(xs)
            sx = sum(xs)
            sx2 = sum(x * x for x in xs)
            sx3 = sum(x ** 3 for x in xs)
            sx4 = sum(x ** 4 for x in xs)
            sy = sum(ys)
            sxy = sum(x * y for x, y in zip(xs, ys))
            sx2y = sum(x * x * y for x, y in zip(xs, ys))
            coefs = _solve_3x3([[sx4, sx3, sx2], [sx3, sx2, sx], [sx2, sx, n]], [sx2y, sxy, sy])
            if not coefs:
                continue
            mny = math.log(k / S)
            iv_k = coefs[0] * mny * mny + coefs[1] * mny + coefs[2]
            if iv_k <= 1e-4 or iv_k > 2.0:
                continue
            fair = bs_call(S, k, T, iv_k)
            mid = 0.5 * (bb + ba)
            mis[k] = mid - fair
            smile_fair[k] = fair
            gamma_k[k] = bs_gamma(S, k, T, iv_k)
            vega_k[k] = bs_vega(S, k, T, iv_k)
            theta_k[k] = bs_theta_decay(S, k, T, iv_k)
            top[k] = (bb, ba, bv, av)

        if not mis:
            return []

        orders: List[Order] = []
        running_pos: Dict[str, int] = {f"VEV_{k}": state.position.get(f"VEV_{k}", 0)
                                        for k in self.VEV_FIT_STRIKES}
        used_strikes: set = set()
        abs_pos = sum(abs(running_pos[f"VEV_{k}"]) for k in self.VEV_FIT_STRIKES)

        # ----- Multi-pair RV with gamma-weighted size + vega hurdle ------
        cheap_pool = sorted([k for k in mis], key=lambda k: mis[k])
        rich_pool = sorted([k for k in mis], key=lambda k: -mis[k])
        for _ in range(self.VEV_MAX_PAIRS_PER_TICK):
            cheap_k = next((k for k in cheap_pool if k not in used_strikes), None)
            rich_k = next((k for k in rich_pool
                           if k not in used_strikes and abs(k - (cheap_k or 0)) >= self.VEV_MIN_PAIR_STRIKE_GAP),
                          None)
            if cheap_k is None or rich_k is None:
                break
            cheap_val = mis[cheap_k]
            rich_val = mis[rich_k]

            # Vega hurdle scales entry threshold by underlying spread cost.
            max_vega = max(vega_k.get(cheap_k, 0.0), vega_k.get(rich_k, 0.0))
            vega_bump = max_vega * vfe_spread * self.VEV_VEGA_PENALTY
            entry_eff = entry + vega_bump

            if not (cheap_val <= -entry_eff and rich_val >= entry_eff):
                break

            cheap_sym = f"VEV_{cheap_k}"
            rich_sym = f"VEV_{rich_k}"
            cheap_od = state.order_depths[cheap_sym]
            rich_od = state.order_depths[rich_sym]
            cbb, cba, _, _ = top[cheap_k]
            rbb, rba, _, _ = top[rich_k]
            if cba is None or rbb is None:
                used_strikes.add(cheap_k); used_strikes.add(rich_k)
                continue

            # Gamma-weighted size scaling.
            avg_gamma = 0.5 * (gamma_k.get(cheap_k, 0.0) + gamma_k.get(rich_k, 0.0))
            g_scale = max(self.VEV_GAMMA_SCALE_MIN,
                          min(self.VEV_GAMMA_SCALE_MAX, avg_gamma / self.VEV_GAMMA_TARGET))
            base_qty = int(round(self.VEV_PAIR_MAX_QTY * g_scale))

            cheap_pos = running_pos[cheap_sym]
            rich_pos = running_pos[rich_sym]
            buy_room = min(per_cap - cheap_pos, -cheap_od.sell_orders[cba])
            sell_room = min(per_cap + rich_pos, rich_od.buy_orders[rbb])
            budget = global_cap - abs_pos
            q = min(base_qty, buy_room, sell_room, budget)
            if q > 0:
                orders.append(Order(cheap_sym, cba, q))
                orders.append(Order(rich_sym, rbb, -q))
                running_pos[cheap_sym] = cheap_pos + q
                running_pos[rich_sym] = rich_pos - q
                abs_pos += 2 * q
            used_strikes.add(cheap_k)
            used_strikes.add(rich_k)

        # ----- Theta-aware decay exit (every tick) ------------------------
        for k, v in mis.items():
            sym = f"VEV_{k}"
            pos = running_pos[sym]
            if pos == 0:
                continue
            bb, ba, _, _ = top[k]
            theta = theta_k.get(k, 0.0)
            theta_adj = (abs(pos) / 100.0) * theta * self.VEV_THETA_EXIT_WEIGHT
            od = state.order_depths[sym]
            if pos > 0 and bb is not None:
                # Long bleeds theta — tighten exit (smaller magnitude trigger).
                exit_thresh = -self.VEV_EXIT_MISPRICING + theta_adj
                if v >= exit_thresh:
                    q = min(pos, od.buy_orders[bb], self.VEV_DECAY_CLIP)
                    if q > 0:
                        orders.append(Order(sym, bb, -q))
                        running_pos[sym] = pos - q
                        abs_pos -= q
            elif pos < 0 and ba is not None:
                # Short collects theta — loosen exit (allow bigger reversion).
                exit_thresh = self.VEV_EXIT_MISPRICING + theta_adj
                if v <= exit_thresh:
                    q = min(-pos, -od.sell_orders[ba], self.VEV_DECAY_CLIP)
                    if q > 0:
                        orders.append(Order(sym, ba, q))
                        running_pos[sym] = pos + q
                        abs_pos -= q

        # ----- Static call-spread no-arbitrage ---------------------------
        # For K1 < K2: lock arb if best_bid(K1) − best_ask(K2) ≥ (K2 − K1) + edge
        # OR if best_ask(K1) < best_bid(K2) (monotonicity violation).
        sorted_K = sorted(top.keys())
        for i in range(len(sorted_K) - 1):
            K1, K2 = sorted_K[i], sorted_K[i + 1]
            sym1, sym2 = f"VEV_{K1}", f"VEV_{K2}"
            bb1, ba1, _, _ = top[K1]
            bb2, ba2, _, _ = top[K2]
            od1 = state.order_depths[sym1]
            od2 = state.order_depths[sym2]
            gap = K2 - K1
            # Slope arb: K1 expensive vs K2 + intrinsic gap.
            if bb1 is not None and ba2 is not None and (bb1 - ba2) >= gap + self.VEV_NOARB_MIN_EDGE:
                pos1 = running_pos[sym1]
                pos2 = running_pos[sym2]
                sell1 = min(self.VEV_NOARB_MAX_QTY, per_cap + pos1, od1.buy_orders[bb1])
                buy2 = min(self.VEV_NOARB_MAX_QTY, per_cap - pos2, -od2.sell_orders[ba2])
                q = min(sell1, buy2, max(0, global_cap - abs_pos))
                if q > 0:
                    orders.append(Order(sym1, bb1, -q))
                    orders.append(Order(sym2, ba2, q))
                    running_pos[sym1] = pos1 - q
                    running_pos[sym2] = pos2 + q
                    abs_pos += 2 * q
            # Monotonicity arb: K1 < K2 should always have C(K1) ≥ C(K2).
            if ba1 is not None and bb2 is not None and ba1 < bb2 - self.VEV_NOARB_MIN_EDGE:
                pos1 = running_pos[sym1]
                pos2 = running_pos[sym2]
                buy1 = min(self.VEV_NOARB_MAX_QTY, per_cap - pos1, -od1.sell_orders[ba1])
                sell2 = min(self.VEV_NOARB_MAX_QTY, per_cap + pos2, od2.buy_orders[bb2])
                q = min(buy1, sell2, max(0, global_cap - abs_pos))
                if q > 0:
                    orders.append(Order(sym1, ba1, q))
                    orders.append(Order(sym2, bb2, -q))
                    running_pos[sym1] = pos1 + q
                    running_pos[sym2] = pos2 - q
                    abs_pos += 2 * q

        # ----- Smile-wide passive maker ----------------------------------
        # Quote each fit strike at smile_fair ± edge with small size, but
        # skip strikes that just got an RV trade so we don't compound risk.
        for k in self.VEV_FIT_STRIKES:
            if k in used_strikes:
                continue
            if k not in smile_fair or k not in top:
                continue
            sym = f"VEV_{k}"
            bb, ba, _, _ = top[k]
            if bb is None or ba is None:
                continue
            fair = smile_fair[k]
            qbid = int(round(fair - self.VEV_PASSIVE_EDGE))
            qask = int(round(fair + self.VEV_PASSIVE_EDGE))
            if qbid >= ba:
                qbid = ba - 1
            if qask <= bb:
                qask = bb + 1
            if qbid >= qask:
                qbid = qask - 1
            cap = self.VEV_PASSIVE_PER_STRIKE_CAP
            pos = running_pos[sym]
            room_long = min(self.VEV_PASSIVE_SIZE, cap - pos)
            room_short = min(self.VEV_PASSIVE_SIZE, cap + pos)
            if room_long > 0 and qbid > 0:
                orders.append(Order(sym, qbid, room_long))
            if room_short > 0 and qask > 0:
                orders.append(Order(sym, qask, -room_short))

        return orders

    # ---- VFE delta-hedge target (epsilon) --------------------------------
    def _target_vfe_from_delta(self, state: TradingState) -> int:
        net_delta = 0.0
        for k, d in self.DELTA_APPROX.items():
            net_delta += state.position.get(f"VEV_{k}", 0) * d
        lim = self.LIMITS[VFE]
        return max(-lim, min(lim, int(round(-net_delta))))

    # ---- main entrypoint --------------------------------------------------
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._load(state)
        self._update_day(int(state.timestamp))
        result: Dict[str, List[Order]] = {}

        hp_orders = self._hp(state)
        if hp_orders:
            result[HYDROGEL] = hp_orders

        vev_orders = self._vev(state)
        for o in vev_orders:
            result.setdefault(o.symbol, []).append(o)

        target_vfe = self._target_vfe_from_delta(state)
        vfe_orders = self._vfe(state, target_vfe)
        if vfe_orders:
            result[VFE] = vfe_orders

        return result, 0, self._save()
