"""trader1.py — Round 4 Production Candidate.
Base: we found vfe gold.py
Integrations:
1. Counterparty Flow Signals (Mark 67, 49, 22 for VFE; Mark 38, 14 for HGP).
2. Hydrogel as Volatility Oracle (HGP mid -> sigma mapping).
3. ITM Option Arbitrage (VEV 4000/4500 parity).
4. Updated Position Limits (HGP 200, VFE 200, VEV 300).
5. Flow-aware fair value skew.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState, Trade


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
    # Updated Position Limits for Round 4
    LIMITS = {HYDROGEL: 200, VFE: 200, **{s: 300 for s in VEV_SYMBOLS}}

    # ── HYDROGEL ─────────────────────────────────────────────────────────────
    HP_ANCHOR = 9993.0
    HP_BLEND = 0.35
    HP_EWMA_ALPHA = 0.20
    HP_TAKE_EDGE = 1.5
    HP_TAKER_MAX = 40
    HP_GAMMA = 0.03
    HP_MAKER_EDGE = 1.5
    HP_FLOW_SKEW = 0.1  # Impact of flow on fair value

    # ── VFE ──────────────────────────────────────────────────────────────────
    VFE_EWMA_ALPHA = 0.20
    VFE_MAKER_EDGE = 1.5
    VFE_REV_EMA_ALPHA = 0.03
    VFE_REV_THRESHOLD = 7.0
    VFE_REV_SIZE = 20
    VFE_REV_MAX_POS = 100
    VFE_FLOW_SKEW = 0.2  # Impact of flow on fair value

    # ── VEV cross-strike RV ──────────────────────────────────────────────────
    VEV_TTE_START = 5.0
    VEV_DAY_INIT = 1  # Round 4 Day 1 -> T = 4.0
    VEV_FIT_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
    VEV_ENTRY_MISPRICING = 1.0
    VEV_EXIT_MISPRICING = 0.2
    VEV_PAIR_MAX_QTY = 25
    VEV_PAIR_CAP_PER_STRIKE = 100
    VEV_GLOBAL_ABS_CAP = 900
    VEV_PHASE_SWITCH_TS = 150_000
    VEV_DECAY_CLIP = 6

    # Delta hedge
    VFE_HEDGE_BAND = 25
    VFE_HEDGE_MAX = 80

    # Smile-based passive MM
    SMM_ENABLE = True
    SMM_STRIKES = [5200, 5300, 5400, 5500]
    SMM_EDGE = 0.8
    SMM_QTY = 40
    SMM_POS_CAP = 150
    SMM_SKEW_FACTOR = 0.4

    # Oracle Params
    ORACLE_BASE_SIGMA = 0.18
    ORACLE_SENSITIVITY = 0.00002 # Sigma change per HGP point

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
        self.history.setdefault("vfe_flow_ema", 0.0)
        self.history.setdefault("hp_flow_ema", 0.0)
        self.history.setdefault("day_index", self.VEV_DAY_INIT)
        self.history.setdefault("last_ts", -1)

    def _save(self) -> str:
        return json.dumps(self.history)

    def _update_day(self, ts: int) -> None:
        last = int(self.history.get("last_ts", -1))
        if last >= 0 and ts < last:
            self.history["day_index"] = int(self.history.get("day_index", self.VEV_DAY_INIT)) + 1
        self.history["last_ts"] = ts

    def _process_trades(self, state: TradingState) -> None:
        # VFE Flow: Mark 67 (B), Mark 49, 22 (S)
        vfe_trades = state.market_trades.get(VFE, [])
        vfe_imbalance = 0
        for t in vfe_trades:
            if t.buyer == 'Mark 67': vfe_imbalance += t.quantity
            if t.seller == 'Mark 67': vfe_imbalance -= t.quantity
            if t.buyer in ['Mark 49', 'Mark 22']: vfe_imbalance -= t.quantity
            if t.seller in ['Mark 49', 'Mark 22']: vfe_imbalance += t.quantity
        
        prev_vfe_flow = self.history.get("vfe_flow_ema", 0.0)
        self.history["vfe_flow_ema"] = 0.85 * prev_vfe_flow + 0.15 * vfe_imbalance

        # HGP Flow: Mark 38 (B), Mark 14 (S)
        hp_trades = state.market_trades.get(HYDROGEL, [])
        hp_imbalance = 0
        for t in hp_trades:
            if t.buyer == 'Mark 38': hp_imbalance += t.quantity
            if t.seller == 'Mark 38': hp_imbalance -= t.quantity
            if t.buyer == 'Mark 14': hp_imbalance -= t.quantity
            if t.seller == 'Mark 14': hp_imbalance += t.quantity
        
        prev_hp_flow = self.history.get("hp_flow_ema", 0.0)
        self.history["hp_flow_ema"] = 0.85 * prev_hp_flow + 0.15 * hp_imbalance

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
        if not od: return []
        bb, ba, _, _ = self._top(od)
        if bb is None or ba is None: return []

        mid = (bb + ba) / 2.0
        prev = self.history.get("hp_ewma") or mid
        ewma = (1 - self.HP_EWMA_ALPHA) * prev + self.HP_EWMA_ALPHA * mid
        self.history["hp_ewma"] = ewma

        # Fair price with flow skew
        flow_skew = self.history.get("hp_flow_ema", 0.0) * self.HP_FLOW_SKEW
        fair = (1 - self.HP_BLEND) * ewma + self.HP_BLEND * self.HP_ANCHOR + flow_skew
        
        pos = state.position.get(HYDROGEL, 0)
        lim = self.LIMITS[HYDROGEL]
        orders: List[Order] = []

        # Taker
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

        # Maker
        reservation = fair - self.HP_GAMMA * pos
        bid_px = int(round(reservation - self.HP_MAKER_EDGE))
        ask_px = int(round(reservation + self.HP_MAKER_EDGE))
        if bid_px >= ba: bid_px = ba - 1
        if ask_px <= bb: ask_px = bb + 1
        if pos < lim: orders.append(Order(HYDROGEL, bid_px, lim - pos))
        if pos > -lim: orders.append(Order(HYDROGEL, ask_px, -(lim + pos)))
        return orders

    # ── VFE ──────────────────────────────────────────────────────────────────
    def _vfe(self, state: TradingState, target_delta_pos: int) -> List[Order]:
        od = state.order_depths.get(VFE)
        if not od: return []
        bb, ba, _, _ = self._top(od)
        if bb is None or ba is None: return []

        mid = (bb + ba) / 2.0
        prev_ewma = self.history.get("vfe_ewma")
        ewma = mid if prev_ewma is None else (1 - self.VFE_EWMA_ALPHA) * prev_ewma + self.VFE_EWMA_ALPHA * mid
        self.history["vfe_ewma"] = ewma

        # Slow mean-rev EMA
        prev_rev = self.history.get("vfe_rev_ema")
        rev_ema = mid if prev_rev is None else (1 - self.VFE_REV_EMA_ALPHA) * prev_rev + self.VFE_REV_EMA_ALPHA * mid
        self.history["vfe_rev_ema"] = rev_ema

        # Fair with flow skew
        flow_skew = self.history.get("vfe_flow_ema", 0.0) * self.VFE_FLOW_SKEW
        fair = ewma + flow_skew
        
        pos = state.position.get(VFE, 0)
        lim = self.LIMITS[VFE]
        orders: List[Order] = []

        # Mean-rev taker
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

        # Delta hedge taker
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

        # Maker
        bid_px = int(round(fair - self.VFE_MAKER_EDGE))
        ask_px = int(round(fair + self.VFE_MAKER_EDGE))
        if bid_px >= ba: bid_px = ba - 1
        if ask_px <= bb: ask_px = bb + 1
        if pos < lim: orders.append(Order(VFE, bid_px, min(lim - pos, 100)))
        if pos > -lim: orders.append(Order(VFE, ask_px, -min(lim + pos, 100)))
        return orders

    # ── VEV cross-strike RV ──────────────────────────────────────────────────
    def _vev(self, state: TradingState) -> Tuple[List[Order], Optional[Tuple], Optional[float], Optional[float]]:
        if VFE not in state.order_depths: return [], None, None, None
        S = self._mid(state.order_depths[VFE])
        if S is None: return [], None, None, None

        day = int(self.history.get("day_index", self.VEV_DAY_INIT))
        T = max(0.5, (self.VEV_TTE_START - day) - state.timestamp / TS_PER_DAY)
        phase2 = int(state.timestamp) >= self.VEV_PHASE_SWITCH_TS
        
        # Oracle Sigma from HGP
        hp_mid = self.history.get("hp_ewma") or 10000.0
        oracle_sigma = self.ORACLE_BASE_SIGMA + (hp_mid - 10000.0) * self.ORACLE_SENSITIVITY
        oracle_sigma = max(0.05, min(0.5, oracle_sigma))

        fit_iv: Dict[int, float] = {}
        for k in self.VEV_FIT_STRIKES:
            od = state.order_depths.get(f"VEV_{k}")
            if not od: continue
            m = self._mid(od)
            if m and m > 0:
                iv = iv_solve(m, S, k, T)
                if iv is not None: fit_iv[k] = iv
        
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
        if not smile_coefs: return [], None, S, T

        mis: Dict[int, float] = {}
        tops: Dict[int, tuple] = {}
        greeks: Dict[int, tuple] = {}
        for k in self.VEV_FIT_STRIKES:
            sym = f"VEV_{k}"
            od = state.order_depths.get(sym)
            if not od: continue
            bb, ba, bv, av = self._top(od)
            if bb is None or ba is None: continue
            mny = math.log(k / S)
            # Blend smile IV with Oracle IV
            iv_smile = max(0.01, min(2.0, smile_coefs[0] * mny * mny + smile_coefs[1] * mny + smile_coefs[2]))
            iv_k = 0.7 * iv_smile + 0.3 * oracle_sigma
            
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

            if mis[cheap_k] <= -self.VEV_ENTRY_MISPRICING and mis[rich_k] >= self.VEV_ENTRY_MISPRICING:
                cheap_sym, rich_sym = f"VEV_{cheap_k}", f"VEV_{rich_k}"
                cheap_od, rich_od = state.order_depths[cheap_sym], state.order_depths[rich_sym]
                _, cba, _, _ = tops[cheap_k]
                rbb, _, _, _ = tops[rich_k]
                
                if cba is not None and rbb is not None:
                    eff_qty = self.VEV_PAIR_MAX_QTY
                    cheap_pos, rich_pos = state.position.get(cheap_sym, 0), state.position.get(rich_sym, 0)
                    buy_room = min(self.VEV_PAIR_CAP_PER_STRIKE - cheap_pos, -cheap_od.sell_orders[cba])
                    sell_room = min(self.VEV_PAIR_CAP_PER_STRIKE + rich_pos, rich_od.buy_orders[rbb])
                    budget = self.VEV_GLOBAL_ABS_CAP - abs_pos
                    q = min(eff_qty, buy_room, sell_room, budget // 2)
                    if q > 0:
                        orders.append(Order(cheap_sym, cba, q))
                        orders.append(Order(rich_sym, rbb, -q))
                        abs_pos += 2 * q

        if phase2:
            for k, v in mis.items():
                sym = f"VEV_{k}"
                pos = state.position.get(sym, 0)
                if pos == 0: continue
                bb, ba, _, _ = tops[k]
                od = state.order_depths[sym]
                if pos > 0 and bb is not None and v >= -self.VEV_EXIT_MISPRICING:
                    q = min(pos, od.buy_orders[bb], self.VEV_DECAY_CLIP)
                    if q > 0: orders.append(Order(sym, bb, -q))
                elif pos < 0 and ba is not None and v <= self.VEV_EXIT_MISPRICING:
                    q = min(-pos, -od.sell_orders[ba], self.VEV_DECAY_CLIP)
                    if q > 0: orders.append(Order(sym, ba, q))

        return orders, smile_coefs, S, T

    def _itm_arb(self, state: TradingState, S: float) -> List[Order]:
        orders = []
        for k in [4000, 4500]:
            sym = f"VEV_{k}"
            od = state.order_depths.get(sym)
            if not od: continue
            bb, ba, _, _ = self._top(od)
            fair = max(0.0, S - k)
            pos = state.position.get(sym, 0)
            lim = self.LIMITS.get(sym, 300)
            
            # If ask is below intrinsic, buy (synthetic underlying)
            if ba is not None and ba < fair - 0.5:
                qty = min(lim - pos, -od.sell_orders[ba])
                if qty > 0: orders.append(Order(sym, ba, qty))
            # If bid is above intrinsic, sell
            if bb is not None and bb > fair + 0.5:
                qty = min(lim + pos, od.buy_orders[bb])
                if qty > 0: orders.append(Order(sym, bb, -qty))
        return orders

    def _target_vfe_from_delta(self, state: TradingState,
                                smile_coefs: Optional[tuple], S: float, T: float) -> int:
        net_delta = 0.0
        for k in VEV_STRIKES:
            pos = state.position.get(f"VEV_{k}", 0)
            if pos == 0: continue
            delta = self.DELTA_APPROX.get(k, 0.5)
            if smile_coefs and S > 0 and T > 0:
                mny = math.log(k / S)
                iv_k = max(0.01, min(2.0, smile_coefs[0] * mny * mny + smile_coefs[1] * mny + smile_coefs[2]))
                delta, _, _, _ = _bs_greeks(S, k, T, iv_k)
            net_delta += pos * delta
        lim = self.LIMITS[VFE]
        return max(-lim, min(lim, int(round(-net_delta))))

    def _vev_smile_mm(self, state: TradingState,
                      smile_coefs: Optional[tuple], S: float, T: float) -> List[Order]:
        if not self.SMM_ENABLE or smile_coefs is None or not S: return []
        orders: List[Order] = []
        for k in self.SMM_STRIKES:
            sym = f"VEV_{k}"
            od = state.order_depths.get(sym)
            if not od: continue
            bb, ba, _, _ = self._top(od)
            if bb is None or ba is None: continue
            mny = math.log(k / S)
            iv_k = smile_coefs[0] * mny * mny + smile_coefs[1] * mny + smile_coefs[2]
            if iv_k <= 0.01: continue
            fair = bs_call(S, k, T, iv_k)
            pos = state.position.get(sym, 0)
            lim = self.LIMITS[sym]

            # Skewed passive maker
            skew = self.SMM_SKEW_FACTOR * (pos / max(self.SMM_POS_CAP, 1))
            bid_px = int(math.floor(fair - self.SMM_EDGE - skew))
            ask_px = int(math.ceil(fair + self.SMM_EDGE - skew))
            if bid_px >= ba: bid_px = ba - 1
            if ask_px <= bb: ask_px = bb + 1
            if pos < self.SMM_POS_CAP and pos < lim:
                orders.append(Order(sym, bid_px, min(self.SMM_QTY, self.SMM_POS_CAP - pos, lim - pos)))
            if pos > -self.SMM_POS_CAP and pos > -lim:
                orders.append(Order(sym, ask_px, -min(self.SMM_QTY, self.SMM_POS_CAP + pos, lim + pos)))
        return orders

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._load(state)
        self._update_day(int(state.timestamp))
        self._process_trades(state)
        result: Dict[str, List[Order]] = {}

        # Hydrogel MM
        for o in self._hp(state):
            result.setdefault(o.symbol, []).append(o)

        # VEV Cross-strike RV
        vev_orders, smile_coefs, S, T = self._vev(state)
        for o in vev_orders:
            result.setdefault(o.symbol, []).append(o)

        # VEV ITM Arb
        if S is not None:
            for o in self._itm_arb(state, S):
                result.setdefault(o.symbol, []).append(o)

        # VEV Smile MM
        if S is not None and T is not None:
            for o in self._vev_smile_mm(state, smile_coefs, S, T):
                result.setdefault(o.symbol, []).append(o)

        # VFE Hedging & MM
        if S is None:
            od = state.order_depths.get(VFE)
            S = self._mid(od) if od else None
        
        day = int(self.history.get("day_index", self.VEV_DAY_INIT))
        if T is None:
            T = max(0.5, (self.VEV_TTE_START - day) - state.timestamp / TS_PER_DAY)

        if S is not None:
            target_vfe = self._target_vfe_from_delta(state, smile_coefs, S, T)
        else:
            target_vfe = 0

        for o in self._vfe(state, target_vfe):
            result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save()
