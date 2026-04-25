"""we found smile mm.py

Greek-aware generation for Prosperity Round 3:
- Dynamic BS delta for VFE hedging
- Gamma-weighted position sizing
- Vega-aware entry gating
- Theta-aware exit optimization
- Smile-based passive market making on VEV options
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
    """Returns (delta, gamma, vega, theta) for a call option."""
    if T <= 1e-10 or sigma <= 1e-10:
        return (1.0 if S > K else 0.0), 0.0, 0.0, 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    delta = _norm_cdf(d1)
    gamma = _norm_pdf(d1) / (S * sigma * sqrt_T)
    vega = S * _norm_pdf(d1) * sqrt_T
    # Theta (simplified for r=0)
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

    # HYDROGEL
    HP_ANCHOR = 9991.0
    HP_BLEND = 0.8
    HP_EWMA_ALPHA = 0.20
    HP_VOL_ALPHA = 0.10
    HP_TAKE_EDGE = 1
    HP_QUOTE_SIZE = 85

    # VFE
    VFE_EWMA_ALPHA = 0.3
    VFE_MAKER_EDGE = 0.9
    VFE_TAKER_EDGE = 1.6
    VFE_TAKER_MAX = 64
    VFE_MICRO_TILT = 0.24
    VFE_HEDGE_BAND = 35         # Optimized for Rust/Reality to balance drift vs fees
    VFE_HEDGE_AGGRO_BAND = 40
    VFE_HEDGE_MAX = 100
    OPEN_PHASE_TS = 100_000
    VFE_SPEED_TRIGGER = 54
    SPEED_COOLDOWN_TS = 40_000
    OPEN_SCALE_MULT = 1.0
    SPEED_SCALE_MULT = 0.82

    # VEV cross-strike RV (aggressive)
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

    # Greek Generation Parameters
    VEV_USE_LIVE_DELTA = True
    VEV_MAX_NET_DELTA = 80.0
    VEV_MAX_NET_GAMMA = 0.15
    VEV_MAX_NET_VEGA = 500.0
    VEV_GAMMA_SIZE_MULT_MIN = 0.6
    VEV_GAMMA_SIZE_MULT_MAX = 1.4
    VEV_VEGA_ENTRY_BUMP_MIN = 0.0
    VEV_VEGA_ENTRY_BUMP_MAX = 0.6
    VEV_THETA_EXIT_WEIGHT = 0.02
    VEV_DUAL_PAIR_ENABLE = False # Phase 5
    VEV_DUAL_PAIR_EXTRA_QTY = 12
    VFE_SPREAD_HEDGE_PENALTY = 1.0 # 1.0 = improve Best Bid/Ask by 1 to jump queue

    # Smile-Based Passive MM Parameters
    SMM_ENABLE = True
    SMM_STRIKES = [5200, 5300, 5400, 5500]
    SMM_EDGE = 0.5              # Balanced edge
    SMM_QTY = 50                # Larger size to capture the 'Voucher'
    SMM_POS_CAP = 100           # Full strike capacity
    SMM_SKEW_FACTOR = 0.5

    DELTA_APPROX: Dict[int, float] = {
        4000: 1.00,
        4500: 0.98,
        5000: 0.82,
        5100: 0.70,
        5200: 0.57,
        5300: 0.44,
        5400: 0.31,
        5500: 0.21,
        6000: 0.10,
        6500: 0.05,
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
        fair = self.HP_BLEND * ewma + (1 - self.HP_BLEND) * self.HP_ANCHOR
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
                # Improve best ask by penalty to jump queue
                hq = min(hmx, residual, lim - pos) # Remove liquidity cap
                if hq > 0:
                    px = int(ba) # Use ba directly like Hydrogel
                    orders.append(Order(VFE, px, hq))
                    if int(state.timestamp) % 10000 == 0:
                        print(f"[Ken-VFE] BUY {hq} @ {px} (Target={target_pos} Pos={pos}) Bids={od.buy_orders} Asks={od.sell_orders}")
                    pos += hq
            elif residual < 0 and pos > -lim:
                # Improve best bid by penalty to jump queue
                hq = min(hmx, -residual, lim + pos) # Remove liquidity cap
                if hq > 0:
                    px = int(bb) # Use bb directly like Hydrogel
                    orders.append(Order(VFE, px, -hq))
                    if int(state.timestamp) % 10000 == 0:
                        print(f"[Ken-VFE] SELL {-hq} @ {px} (Target={target_pos} Pos={pos}) Bids={od.buy_orders} Asks={od.sell_orders}")
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
        maker_max = max(30, int(128 * local_scale))
        if lim - pos > 0:
            orders.append(Order(VFE, qbid, min(lim - pos, maker_max)))
        if lim + pos > 0:
            orders.append(Order(VFE, qask, -min(lim + pos, maker_max)))
        return orders

    def _vev(self, state: TradingState) -> Tuple[List[Order], Optional[Tuple[float, float, float]]]:
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

        # GLOBAL FIT
        pts_all = [(math.log(x / S), fit_iv[x]) for x in fit_iv]
        xs_all = [p[0] for p in pts_all]
        ys_all = [p[1] for p in pts_all]
        n_all = len(xs_all)
        smile_coefs = _solve_3x3([[sum(x**4 for x in xs_all), sum(x**3 for x in xs_all), sum(x**2 for x in xs_all)], 
                                  [sum(x**3 for x in xs_all), sum(x**2 for x in xs_all), sum(x for x in xs_all)], 
                                  [sum(x**2 for x in xs_all), sum(x for x in xs_all), n_all]], 
                                 [sum(x**2 * y for x, y in zip(xs_all, ys_all)), sum(x * y for x, y in zip(xs_all, ys_all)), sum(ys_all)])
        
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
            iv_k = max(0.01, min(2.0, iv_k))
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
                cheap_od, rich_od = state.order_depths[cheap_sym], state.order_depths[rich_sym]
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
                
                # Theta-aware exit optimization
                th = greeks[k][3] # Theta is negative for calls
                # If pos > 0 (long), th < 0 means we pay. We want higher hurdle (exit sooner).
                # If pos < 0 (short), th < 0 means we collect. We want lower hurdle (exit later).
                th_adj = - (pos / 100.0) * th * self.VEV_THETA_EXIT_WEIGHT
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
            if not od: continue
            bb, ba, _, _ = self._top(od)
            if bb is None or ba is None: continue
            
            mny = math.log(k / S)
            iv_k = smile_coefs[0] * mny * mny + smile_coefs[1] * mny + smile_coefs[2]
            if iv_k <= 0.01: continue
            fair = bs_call(S, k, T, iv_k)
            pos = state.position.get(sym, 0)
            lim = self.LIMITS[sym]
            
            # TAKER: Hit if mispricing is massive
            if k in [5400, 5100, 5500] and ba <= fair - 1.5:
                q = min(self.SMM_QTY, lim - pos)
                if q > 0:
                    orders.append(Order(sym, ba, q)); pos += q
            if k in [5300, 5200, 5000] and bb >= fair + 1.5:
                q = min(self.SMM_QTY, lim + pos)
                if q > 0:
                    orders.append(Order(sym, bb, -q)); pos -= q

            # MAKER: Passive priority quoting
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
        result: Dict[str, List[Order]] = {}

        hp_orders = self._hp(state)
        if hp_orders: result[HYDROGEL] = hp_orders

        vev_orders, smile_coefs, S, T = self._vev(state)
        for o in vev_orders: result.setdefault(o.symbol, []).append(o)

        if S is not None:
            smm_orders = self._vev_smile_mm(state, smile_coefs, S, T)
            for o in smm_orders: result.setdefault(o.symbol, []).append(o)

        # BS Delta Hedging: PASSIVE (Maker) to avoid spread fees
        vfe_od = state.order_depths.get(VFE)
        if S is None: S = self._mid(vfe_od) if vfe_od else None
        day = int(self.history.get("day_index", self.VEV_DAY_INIT))
        if T is None: T = max(0.5, (self.VEV_TTE_START - day) - state.timestamp / TS_PER_DAY)
        
        if S is not None:
            target_vfe = self._target_vfe_from_delta(state, smile_coefs, S, T)
            pos = state.position.get(VFE, 0)
            residual = target_vfe - pos
            if abs(residual) >= self.VFE_HEDGE_BAND and vfe_od:
                bb, ba, _, _ = self._top(vfe_od)
                if bb is not None and ba is not None:
                    # PASSIVE orders at the Best Bid/Ask
                    if residual > 0: # Buy
                        result.setdefault(VFE, []).append(Order(VFE, bb, min(residual, self.LIMITS[VFE] - pos)))
                    else: # Sell
                        result.setdefault(VFE, []).append(Order(VFE, ba, max(residual, -self.LIMITS[VFE] - pos)))

        return result, 0, self._save()
