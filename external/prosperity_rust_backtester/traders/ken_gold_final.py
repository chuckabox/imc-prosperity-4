"""we found vfe gold.py — hybrid: Adin v2 HYDROGEL discipline + vfe gold VEV alphas.

KEY FIXES vs prior vfe gold
---------------------------
1. HP_TAKER_MAX = 20  (Adin v2 lesson: uncapped takers exhaust the position limit,
   leaving no room for maker orders to collect passive fills all day. Capping at 20
   keeps the trader active and quoting throughout the day.)

2. VFE slow mean-reversion taker  (Adin v2 lesson: fast EWMA + tiny edge almost
   never triggers in Rust. Replace with slow rev-EMA (α=0.03) + threshold 8,
   same as Adin, so the mean-rev taker actually fires and earns VFE PnL.)

3. VFE delta hedge → aggressive (taker)  (Prior version posted PASSIVE maker at
   bb/ba for the hedge which never fills in Rust. Now hits ba/bb directly.)

KEPT from vfe gold
------------------
- Cross-strike RV pairs: buy cheap strike (5000/5100), sell rich strike (5200/5300)
  with gamma-weighted sizing and vega entry gate.
- Theta-aware exit in phase2 (after 140k ticks).
- Smile-based passive MM on VEV 5300/5400/5500.
- BS greeks tracking and delta hedge target computation.
- Phase-aware position decay.
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


class Trader:
    LIMITS = {HYDROGEL: 80, VFE: 200, **{s: 100 for s in VEV_SYMBOLS}}

    # ── HYDROGEL (Adin v2 discipline) ────────────────────────────────────────
    HP_ANCHOR = 9993.0
    HP_BLEND = 0.4
    HP_EWMA_ALPHA = 0.20
    HP_TAKE_EDGE = 2.0
    HP_TAKER_MAX = 20        # Back to safe cap
    HP_GAMMA = 0.04
    HP_MAKER_EDGE = 2.0

    # ── VFE ──────────────────────────────────────────────────────────────────
    VFE_EWMA_ALPHA = 0.20
    VFE_MAKER_EDGE = 1.5
    # Mean-rev taker (Adin v2 style) — slow EMA + high threshold fires more
    VFE_REV_EMA_ALPHA = 0.03
    VFE_REV_THRESHOLD = 8.0
    VFE_REV_SIZE = 15
    VFE_REV_MAX_POS = 60
    # Delta hedge
    VFE_HEDGE_BAND = 35
    VFE_HEDGE_MAX = 60

    # ── VEV cross-strike RV ──────────────────────────────────────────────────
    VEV_TTE_START = 8.0
    VEV_DAY_INIT = 2
    VEV_FIT_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
    VEV_ENTRY_MISPRICING = 1.2   # raised from 0.9 to improve win rate
    VEV_EXIT_MISPRICING = 0.3
    VEV_PAIR_MAX_QTY = 18
    VEV_PAIR_CAP_PER_STRIKE = 40
    VEV_GLOBAL_ABS_CAP = 360
    VEV_PHASE_SWITCH_TS = 140_000
    VEV_PHASE2_CAP_SCALE = 0.85
    VEV_PHASE2_ENTRY_BUMP = 0.30
    VEV_DECAY_CLIP = 4

    # Greek generation
    VEV_USE_LIVE_DELTA = True
    VEV_MAX_NET_DELTA = 80.0
    VEV_GAMMA_SIZE_MULT_MIN = 0.6
    VEV_GAMMA_SIZE_MULT_MAX = 1.4
    VEV_VEGA_ENTRY_BUMP_MIN = 0.0
    VEV_VEGA_ENTRY_BUMP_MAX = 0.5
    VEV_THETA_EXIT_WEIGHT = 0.02
    VFE_SPREAD_HEDGE_PENALTY = 1.0

    # Smile-based passive MM
    SMM_ENABLE = True
    SMM_STRIKES = [5200, 5300, 5400, 5500]
    SMM_EDGE = 1.0
    SMM_QTY = 30
    SMM_POS_CAP = 60
    SMM_SKEW_FACTOR = 0.5

    DELTA_APPROX: Dict[int, float] = {
        4000: 1.00, 4500: 0.98, 5000: 0.82, 5100: 0.70,
        5200: 0.57, 5300: 0.44, 5400: 0.31, 5500: 0.21,
        6000: 0.10, 6500: 0.05,
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
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("vfe_rev_ema", None)
        self.history.setdefault("day_index", self.VEV_DAY_INIT)
        self.history.setdefault("last_ts", -1)

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

    # ── HYDROGEL ─────────────────────────────────────────────────────────────
    def _hp(self, state: TradingState) -> List[Order]:
        od = state.order_depths.get(HYDROGEL)
        if not od:
            return []
        bb, ba, _, _ = self._top(od)
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        prev = self.history.get("hp_ewma") or mid
        ewma = (1 - self.HP_EWMA_ALPHA) * prev + self.HP_EWMA_ALPHA * mid
        self.history["hp_ewma"] = ewma

        fair = (1 - self.HP_BLEND) * ewma + self.HP_BLEND * self.HP_ANCHOR
        pos = state.position.get(HYDROGEL, 0)
        lim = self.LIMITS[HYDROGEL]
        orders: List[Order] = []

        # Taker — capped at HP_TAKER_MAX to preserve quoting capacity
        if ba <= fair - self.HP_TAKE_EDGE and pos < lim:
            qty = min(self.HP_TAKER_MAX, lim - pos, -od.sell_orders[ba])
            if qty > 0:
                orders.append(Order(HYDROGEL, ba, qty))
                pos += qty
        if bb >= fair + self.HP_TAKE_EDGE and pos > -lim:
            qty = min(self.HP_TAKER_MAX, lim + pos, od.buy_orders[bb])
            if qty > 0:
                orders.append(Order(HYDROGEL, bb, -qty))
                pos -= qty

        # AS reservation price maker
        reservation = fair - self.HP_GAMMA * pos
        bid_px = int(round(reservation - self.HP_MAKER_EDGE))
        ask_px = int(round(reservation + self.HP_MAKER_EDGE))
        if bid_px >= ba:
            bid_px = ba - 1
        if ask_px <= bb:
            ask_px = bb + 1
        if bid_px >= ask_px:
            bid_px = ask_px - 1
        if pos < lim:
            orders.append(Order(HYDROGEL, bid_px, lim - pos))
        if pos > -lim:
            orders.append(Order(HYDROGEL, ask_px, -(lim + pos)))
        return orders

    # ── VFE ──────────────────────────────────────────────────────────────────
    def _vfe(self, state: TradingState, target_delta_pos: int) -> List[Order]:
        od = state.order_depths.get(VFE)
        if not od:
            return []
        bb, ba, bv, av = self._top(od)
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        prev_ewma = self.history.get("vfe_ewma")
        ewma = mid if prev_ewma is None else (1 - self.VFE_EWMA_ALPHA) * prev_ewma + self.VFE_EWMA_ALPHA * mid
        self.history["vfe_ewma"] = ewma

        # Slow mean-rev EMA (Adin v2 style) — for the taker signal
        prev_rev = self.history.get("vfe_rev_ema")
        rev_ema = mid if prev_rev is None else (1 - self.VFE_REV_EMA_ALPHA) * prev_rev + self.VFE_REV_EMA_ALPHA * mid
        self.history["vfe_rev_ema"] = rev_ema

        fair = ewma
        pos = state.position.get(VFE, 0)
        lim = self.LIMITS[VFE]
        orders: List[Order] = []

        # Mean-reversion taker (Adin v2): fires when price deviates 8+ from slow EMA
        dev = mid - rev_ema
        if dev <= -self.VFE_REV_THRESHOLD and pos < self.VFE_REV_MAX_POS:
            sz = min(self.VFE_REV_SIZE, self.VFE_REV_MAX_POS - pos, -od.sell_orders[ba])
            if sz > 0:
                orders.append(Order(VFE, ba, sz))
                pos += sz
        elif dev >= self.VFE_REV_THRESHOLD and pos > -self.VFE_REV_MAX_POS:
            sz = min(self.VFE_REV_SIZE, self.VFE_REV_MAX_POS + pos, od.buy_orders[bb])
            if sz > 0:
                orders.append(Order(VFE, bb, -sz))
                pos -= sz

        # Delta hedge target — aggressive taker (KEY FIX: was passive before)
        residual = target_delta_pos - pos
        if abs(residual) >= self.VFE_HEDGE_BAND:
            if residual > 0 and pos < lim:
                hq = min(self.VFE_HEDGE_MAX, residual, lim - pos, -od.sell_orders[ba])
                if hq > 0:
                    orders.append(Order(VFE, ba, hq))
                    pos += hq
            elif residual < 0 and pos > -lim:
                hq = min(self.VFE_HEDGE_MAX, -residual, lim + pos, od.buy_orders[bb])
                if hq > 0:
                    orders.append(Order(VFE, bb, -hq))
                    pos -= hq

        # AS passive maker
        bid_px = int(round(fair - self.VFE_MAKER_EDGE))
        ask_px = int(round(fair + self.VFE_MAKER_EDGE))
        if bid_px >= ba:
            bid_px = ba - 1
        if ask_px <= bb:
            ask_px = bb + 1
        if pos < lim:
            orders.append(Order(VFE, bid_px, min(lim - pos, 60)))
        if pos > -lim:
            orders.append(Order(VFE, ask_px, -min(lim + pos, 60)))
        return orders

    # ── VEV cross-strike RV ──────────────────────────────────────────────────
    def _vev(self, state: TradingState) -> Tuple[List[Order], Optional[Tuple], Optional[float], Optional[float]]:
        if VFE not in state.order_depths:
            return [], None, None, None
        S = self._mid(state.order_depths[VFE])
        if S is None:
            return [], None, None, None

        day = int(self.history.get("day_index", self.VEV_DAY_INIT))
        T = max(0.5, (self.VEV_TTE_START - day) - state.timestamp / TS_PER_DAY)
        phase2 = int(state.timestamp) >= self.VEV_PHASE_SWITCH_TS
        cap_scale = self.VEV_PHASE2_CAP_SCALE if phase2 else 1.0
        entry = self.VEV_ENTRY_MISPRICING + (self.VEV_PHASE2_ENTRY_BUMP if phase2 else 0.0)
        per_cap = int(self.VEV_PAIR_CAP_PER_STRIKE * cap_scale)
        global_cap = int(self.VEV_GLOBAL_ABS_CAP * cap_scale)

        fit_iv: Dict[int, float] = {}
        for k in self.VEV_FIT_STRIKES:
            od = state.order_depths.get(f"VEV_{k}")
            if not od:
                continue
            m = self._mid(od)
            if m and m > 0:
                iv = iv_solve(m, S, k, T)
                if iv is not None:
                    fit_iv[k] = iv
        if len(fit_iv) < 4:
            return [], None, S, T

        pts = [(math.log(x / S), fit_iv[x]) for x in fit_iv]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        n = len(xs)
        smile_coefs = _solve_3x3(
            [[sum(x**4 for x in xs), sum(x**3 for x in xs), sum(x**2 for x in xs)],
             [sum(x**3 for x in xs), sum(x**2 for x in xs), sum(x for x in xs)],
             [sum(x**2 for x in xs), sum(x for x in xs), n]],
            [sum(x**2 * y for x, y in zip(xs, ys)),
             sum(x * y for x, y in zip(xs, ys)),
             sum(ys)]
        )
        if not smile_coefs:
            return [], None, S, T

        mis: Dict[int, float] = {}
        tops: Dict[int, tuple] = {}
        greeks: Dict[int, tuple] = {}
        for k in self.VEV_FIT_STRIKES:
            od = state.order_depths.get(f"VEV_{k}")
            if not od:
                continue
            bb, ba, bv, av = self._top(od)
            if bb is None or ba is None:
                continue
            mny = math.log(k / S)
            iv_k = max(0.01, min(2.0, smile_coefs[0] * mny * mny + smile_coefs[1] * mny + smile_coefs[2]))
            fair = bs_call(S, k, T, iv_k)
            mis[k] = (bb + ba) / 2.0 - fair
            tops[k] = (bb, ba, bv, av)
            greeks[k] = _bs_greeks(S, k, T, iv_k)

        orders: List[Order] = []
        abs_pos = sum(abs(state.position.get(f"VEV_{k}", 0)) for k in self.VEV_FIT_STRIKES)

        low_bucket = [k for k in (5000, 5100) if k in mis]
        high_bucket = [k for k in (5200, 5300) if k in mis]

        if low_bucket and high_bucket:
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
                cheap_sym = f"VEV_{cheap_k}"
                rich_sym = f"VEV_{rich_k}"
                cheap_od = state.order_depths[cheap_sym]
                rich_od = state.order_depths[rich_sym]
                cbb, cba, _, _ = tops[cheap_k]
                rbb, rba, _, _ = tops[rich_k]
                if cba is not None and rbb is not None:
                    avg_gamma = (greeks[cheap_k][1] + greeks[rich_k][1]) / 2.0
                    gamma_mult = max(self.VEV_GAMMA_SIZE_MULT_MIN,
                                    min(self.VEV_GAMMA_SIZE_MULT_MAX, avg_gamma / 0.0005))
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
                bb, ba, _, _ = tops[k]
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

        return orders, smile_coefs, S, T

    def _target_vfe_from_delta(self, state: TradingState,
                                smile_coefs: Optional[tuple], S: float, T: float) -> int:
        net_delta = 0.0
        for k in VEV_STRIKES:
            pos = state.position.get(f"VEV_{k}", 0)
            if pos == 0:
                continue
            delta = self.DELTA_APPROX.get(k, 0.5)
            if self.VEV_USE_LIVE_DELTA and smile_coefs and S > 0 and T > 0:
                mny = math.log(k / S)
                iv_k = max(0.01, min(2.0, smile_coefs[0] * mny * mny + smile_coefs[1] * mny + smile_coefs[2]))
                delta, _, _, _ = _bs_greeks(S, k, T, iv_k)
            net_delta += pos * delta
        lim = self.LIMITS[VFE]
        return max(-lim, min(lim, int(round(-net_delta))))

    def _vev_smile_mm(self, state: TradingState,
                      smile_coefs: Optional[tuple], S: float, T: float) -> List[Order]:
        if not self.SMM_ENABLE or smile_coefs is None or not S:
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
            fair = bs_call(S, k, T, iv_k)
            pos = state.position.get(sym, 0)
            lim = self.LIMITS[sym]

            # Taker on large mispricing
            if k in (5400, 5100, 5500) and ba <= fair - 1.5:
                q = min(self.SMM_QTY, lim - pos, -od.sell_orders[ba])
                if q > 0:
                    orders.append(Order(sym, ba, q))
                    pos += q
            if k in (5300, 5200, 5000) and bb >= fair + 1.5:
                q = min(self.SMM_QTY, lim + pos, od.buy_orders[bb])
                if q > 0:
                    orders.append(Order(sym, bb, -q))
                    pos -= q

            # Skewed passive maker
            skew = self.SMM_SKEW_FACTOR * (pos / max(self.SMM_POS_CAP, 1))
            bid_px = int(math.floor(fair - self.SMM_EDGE - skew))
            ask_px = int(math.ceil(fair + self.SMM_EDGE - skew))
            if bid_px >= ba:
                bid_px = ba - 1
            if ask_px <= bb:
                ask_px = bb + 1
            if pos < self.SMM_POS_CAP and pos < lim:
                orders.append(Order(sym, bid_px, min(self.SMM_QTY, self.SMM_POS_CAP - pos, lim - pos)))
            if pos > -self.SMM_POS_CAP and pos > -lim:
                orders.append(Order(sym, ask_px, -min(self.SMM_QTY, self.SMM_POS_CAP + pos, lim + pos)))
        return orders

    # ── main ─────────────────────────────────────────────────────────────────
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._load(state)
        self._update_day(int(state.timestamp))
        result: Dict[str, List[Order]] = {}

        for o in self._hp(state):
            result.setdefault(o.symbol, []).append(o)

        vev_orders, smile_coefs, S, T = self._vev(state)
        for o in vev_orders:
            result.setdefault(o.symbol, []).append(o)

        if S is not None and T is not None:
            for o in self._vev_smile_mm(state, smile_coefs, S, T):
                result.setdefault(o.symbol, []).append(o)

        day = int(self.history.get("day_index", self.VEV_DAY_INIT))
        if S is None:
            od = state.order_depths.get(VFE)
            S = self._mid(od) if od else None
        if T is None:
            T = max(0.5, (self.VEV_TTE_START - day) - state.timestamp / TS_PER_DAY)

        if S is not None:
            target_vfe = self._target_vfe_from_delta(state, smile_coefs, S, T)
        else:
            target_vfe = 0

        for o in self._vfe(state, target_vfe):
            result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save()
