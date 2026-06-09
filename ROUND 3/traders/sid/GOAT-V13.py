"""GOAT V13 - Greeks-Aware Hedging with Refined Parameters

Core: Ken's "vfe gold" Greeks-aware dynamic hedging strategy
- BS Delta, Gamma, Vega, Theta for each option position
- Dynamic VFE target from net delta (hedges options exposure)
- Gamma-weighted sizing for pair trades (convexity control)
- Vega-aware entry gating (high vega = tighter entry)
- Theta-aware exit optimization (collect/pay decay differently)
- Smile-based passive MM on 5200-5500 (captures persistent misprice)
- Speed limiting on VFE to avoid whipsaws

Refinements from V12:
- Removed HP anchor bias (use pure EMA instead, but with higher stability blend)
- Tighter smile MM strikes (removed 5500, focus 5200-5400)
- Phase2 earlier switch (120k instead of 140k) to adapt faster
- Refined entry/exit thresholds based on V11/V12 live data
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
    LIMITS = {HYDROGEL: 200, VFE: 200, **{s: 100 for s in VEV_SYMBOLS}}

    # HYDROGEL: Pure EMA (no anchor bias)
    HP_EWMA_ALPHA = 0.25
    HP_VOL_ALPHA = 0.12
    HP_TAKE_EDGE = 1
    HP_QUOTE_SIZE = 90

    # VFE: Greeks-aware hedging
    VFE_EWMA_ALPHA = 0.32
    VFE_MAKER_EDGE = 0.9
    VFE_TAKER_EDGE = 1.6
    VFE_TAKER_MAX = 64
    VFE_MICRO_TILT = 0.25
    VFE_HEDGE_BAND = 35
    VFE_HEDGE_AGGRO_BAND = 42
    VFE_HEDGE_MAX = 65
    OPEN_PHASE_TS = 100_000
    VFE_SPEED_TRIGGER = 54
    SPEED_COOLDOWN_TS = 40_000
    OPEN_SCALE_MULT = 1.0
    SPEED_SCALE_MULT = 0.82

    # VEV: Greeks-aware pair trading
    VEV_TTE_START = 8.0
    VEV_DAY_INIT = 2
    VEV_FIT_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
    VEV_ENTRY_MISPRICING = 0.95
    VEV_EXIT_MISPRICING = 0.35
    VEV_PAIR_MAX_QTY = 24
    VEV_PAIR_CAP_PER_STRIKE = 48
    VEV_GLOBAL_ABS_CAP = 450
    VEV_PHASE_SWITCH_TS = 120_000  # Earlier phase2
    VEV_PHASE2_CAP_SCALE = 0.85
    VEV_PHASE2_ENTRY_BUMP = 0.40
    VEV_DECAY_CLIP = 5

    # Greeks Parameters
    VEV_USE_LIVE_DELTA = True
    VEV_MAX_NET_DELTA = 85.0
    VEV_MAX_NET_GAMMA = 0.16
    VEV_MAX_NET_VEGA = 520.0
    VEV_GAMMA_SIZE_MULT_MIN = 0.58
    VEV_GAMMA_SIZE_MULT_MAX = 1.45
    VEV_VEGA_ENTRY_BUMP_MIN = 0.0
    VEV_VEGA_ENTRY_BUMP_MAX = 0.65
    VEV_THETA_EXIT_WEIGHT = 0.025
    VFE_SPREAD_HEDGE_PENALTY = 0.16

    # Smile-Based Passive MM (refined to 5200-5400)
    SMM_ENABLE = True
    SMM_STRIKES = [5200, 5300, 5400]
    SMM_EDGE = 0.55
    SMM_QTY = 16
    SMM_POS_CAP = 55
    SMM_SKEW_FACTOR = 0.32

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
        fair = ewma  # Pure EMA, no anchor
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

        spread = 1 + int(vol * 2.5)
        skew = int(round(3.5 * (pos / lim)))
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

        qbid = int(round(fair - self.VFE_MAKER_EDGE))
        qask = int(round(fair + self.VFE_MAKER_EDGE))
        if qbid >= ba:
            qbid = ba - 1
        if qask <= bb:
            qask = bb + 1
        if qbid >= qask:
            qbid = qask - 1
        maker_max = max(30, int(135 * local_scale))
        if lim - pos > 0:
            orders.append(Order(VFE, qbid, min(lim - pos, maker_max)))
        if lim + pos > 0:
            orders.append(Order(VFE, qask, -min(lim + pos, maker_max)))
        return orders

    def _vev(self, state: TradingState) -> Tuple[List[Order], Optional[Tuple[float, float, float]], Optional[float], Optional[float]]:
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
            return [], None, S, T

        pts = [(math.log(x / S), fit_iv[x]) for x in fit_iv]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        smile_coefs = _solve_3x3(
            [[sum(x**4 for x in xs), sum(x**3 for x in xs), sum(x**2 for x in xs)],
             [sum(x**3 for x in xs), sum(x**2 for x in xs), sum(x for x in xs)],
             [sum(x**2 for x in xs), sum(x for x in xs), len(xs)]],
            [sum(x**2 * y for x, y in zip(xs, ys)), sum(x * y for x, y in zip(xs, ys)), sum(ys)]
        )

        if not smile_coefs:
            return [], None, S, T

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

            mny = math.log(k / S)
            iv_k = smile_coefs[0] * mny * mny + smile_coefs[1] * mny + smile_coefs[2]
            fair = bs_call(S, k, T, iv_k)
            mid = 0.5 * (bb + ba)
            mis[k] = mid - fair
            top[k] = (bb, ba, bv, av)
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

            cheap_val = mis[cheap_k]
            rich_val = mis[rich_k]
            if cheap_val <= -eff_entry and rich_val >= eff_entry:
                cheap_sym, rich_sym = f"VEV_{cheap_k}", f"VEV_{rich_k}"
                cbb, cba, _, _ = top[cheap_k]
                rbb, rba, _, _ = top[rich_k]
                if cba is not None and rbb is not None:
                    avg_gamma = (greeks[cheap_k][1] + greeks[rich_k][1]) / 2.0
                    gamma_mult = max(self.VEV_GAMMA_SIZE_MULT_MIN,
                                    min(self.VEV_GAMMA_SIZE_MULT_MAX,
                                        avg_gamma / 0.0005))

                    base_qty = self.VEV_PAIR_MAX_QTY
                    eff_qty = int(round(base_qty * gamma_mult))

                    cheap_pos = state.position.get(cheap_sym, 0)
                    rich_pos = state.position.get(rich_sym, 0)
                    buy_room = min(per_cap - cheap_pos, -cheap_od.sell_orders[cba])
                    sell_room = min(per_cap + rich_pos, rich_od.buy_orders[rbb])
                    budget = global_cap - abs_pos
                    q = min(eff_qty, buy_room, sell_room, budget)

                    if q > 0:
                        cheap_od = state.order_depths[cheap_sym]
                        rich_od = state.order_depths[rich_sym]
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

        return orders, smile_coefs, S, T

    def _target_vfe_from_delta(self, state: TradingState, smile_coefs: Optional[Tuple[float, float, float]], S: float, T: float) -> int:
        net_delta = 0.0
        for k in VEV_STRIKES:
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

    def _vev_smile_mm(self, state: TradingState, smile_coefs: Optional[Tuple[float, float, float]], S: float, T: float) -> List[Order]:
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
            fair = bs_call(S, k, T, iv_k)

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

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._load(state)
        self._update_day(int(state.timestamp))
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

        vfe_od = state.order_depths.get(VFE)
        if S is None:
            S = self._mid(vfe_od) if vfe_od else None
        day = int(self.history.get("day_index", self.VEV_DAY_INIT))
        if T is None:
            T = max(0.5, (self.VEV_TTE_START - day) - state.timestamp / TS_PER_DAY)

        if S is not None:
            target_vfe = self._target_vfe_from_delta(state, smile_coefs, S, T)
        else:
            target_vfe = 0

        vfe_orders = self._vfe(state, target_vfe)
        if vfe_orders:
            result[VFE] = vfe_orders

        return result, 0, self._save()
