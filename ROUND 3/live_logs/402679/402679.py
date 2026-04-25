"""trader5.py - Hybrid Hedgehog Strategy v3.
Combines VFE Mean Reversion with VEV Gamma Scalping.
No forced delta hedging to save on spread costs.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState


# ---------------- Black-Scholes ----------------
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1)


# ---------------- Constants ----------------
HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]
TS_PER_DAY = 1_000_000
TOTAL_DAYS = 8


def _best_bid_ask(od: OrderDepth) -> Tuple[int | None, int | None]:
    bid = max(od.buy_orders.keys()) if od.buy_orders else None
    ask = min(od.sell_orders.keys()) if od.sell_orders else None
    return bid, ask


def _mid(od: OrderDepth) -> float | None:
    b, a = _best_bid_ask(od)
    if b is None or a is None:
        return None
    return 0.5 * (b + a)


class Trader:
    # ---- Official Limits ----
    LIMITS = {HYDROGEL: 200, VFE: 200, **{s: 300 for s in VEV_SYMBOLS}}

    # ---- Module Switches ----
    ENABLE_VFE_ALPHA = True
    ENABLE_VEV_GAMMA = True
    ENABLE_HYDROGEL = True

    # ---- VFE Mean Reversion ----
    VFE_EMA_SPAN = 100
    VFE_REV_THRESHOLD = 2.5
    VFE_REV_SIZE = 60
    VFE_QUOTE_SIZE = 40

    # ---- VEV Gamma Scalp ----
    VEV_SIGMA_MODEL = 0.014
    VEV_EDGE_REQ = 1.0
    VEV_TAKE_SIZE = 100
    VEV_DELTA_MAX_UNHEDGED = 180

    # ---- HYDROGEL MM ----
    HP_ANCHOR = 9991.0
    HP_EWMA_ALPHA = 0.25
    HP_TAKE_EDGE = 2

    def __init__(self) -> None:
        self.tick = 0
        self.vfe_ema: float | None = None
        self.hp_ewma: float | None = None

    def _serialise(self) -> str:
        return json.dumps({
            "tick": self.tick,
            "vfe_ema": self.vfe_ema,
            "hp_ewma": self.hp_ewma,
        })

    def _restore(self, td: str) -> None:
        if not td: return
        try:
            d = json.loads(td)
            self.tick = int(d.get("tick", 0))
            self.vfe_ema = d.get("vfe_ema")
            self.hp_ewma = d.get("hp_ewma")
        except Exception: pass

    # ---------- module 1: HYDROGEL MM ----------
    def _hydrogel(self, state: TradingState) -> List[Order]:
        sym = HYDROGEL
        if sym not in state.order_depths: return []
        od = state.order_depths[sym]
        m = _mid(od)
        if m is None: return []
        if self.hp_ewma is None: self.hp_ewma = m
        self.hp_ewma = self.HP_EWMA_ALPHA * m + (1 - self.HP_EWMA_ALPHA) * self.hp_ewma
        
        fair = 0.6 * self.hp_ewma + 0.4 * self.HP_ANCHOR
        pos = state.position.get(sym, 0)
        lim = self.LIMITS[sym]
        orders: List[Order] = []

        b, a = _best_bid_ask(od)
        if a is not None and a <= fair - self.HP_TAKE_EDGE:
            qty = min(-od.sell_orders[a], lim - pos)
            if qty > 0: orders.append(Order(sym, a, qty)); pos += qty
        if b is not None and b >= fair + self.HP_TAKE_EDGE:
            qty = min(od.buy_orders[b], lim + pos)
            if qty > 0: orders.append(Order(sym, b, -qty)); pos -= qty
            
        # Skewed quoter
        skew = -1 if pos > 80 else (1 if pos < -80 else 0)
        orders.append(Order(sym, int(round(fair - 1 + skew)), min(30, lim - pos)))
        orders.append(Order(sym, int(round(fair + 1 + skew)), -min(30, lim + pos)))
        return orders

    # ---------- module 2: VFE Mean Reversion ----------
    def _vfe_logic(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths: return []
        od = state.order_depths[VFE]
        m = _mid(od)
        if m is None: return []
        if self.vfe_ema is None: self.vfe_ema = m
        alpha = 2.0 / (self.VFE_EMA_SPAN + 1)
        self.vfe_ema = alpha * m + (1 - alpha) * self.vfe_ema
        
        dev = m - self.vfe_ema
        pos = state.position.get(VFE, 0)
        lim = self.LIMITS[VFE]
        orders: List[Order] = []
        
        # Signal based taker
        b, a = _best_bid_ask(od)
        if dev < -self.VFE_REV_THRESHOLD and a is not None and a <= self.vfe_ema:
            qty = min(-od.sell_orders[a], self.VFE_REV_SIZE, lim - pos)
            if qty > 0: orders.append(Order(VFE, a, qty)); pos += qty
        elif dev > self.VFE_REV_THRESHOLD and b is not None and b >= self.vfe_ema:
            qty = min(od.buy_orders[b], self.VFE_REV_SIZE, lim + pos)
            if qty > 0: orders.append(Order(VFE, b, -qty)); pos -= qty
            
        # Market making (passive)
        skew = -1 if pos > 50 else (1 if pos < -50 else 0)
        orders.append(Order(VFE, int(round(m - 1 + skew)), min(self.VFE_QUOTE_SIZE, lim - pos)))
        orders.append(Order(VFE, int(round(m + 1 + skew)), -min(self.VFE_QUOTE_SIZE, lim + pos)))
        return orders

    # ---------- module 3: VEV Gamma Scalping ----------
    def _vev_logic(self, state: TradingState) -> Tuple[List[Order], float]:
        if VFE not in state.order_depths: return [], 0.0
        S = _mid(state.order_depths[VFE])
        if S is None: return [], 0.0
        
        day = int(state.timestamp // TS_PER_DAY)
        ts_in_day = state.timestamp % TS_PER_DAY
        TTE = (TOTAL_DAYS - day) - ts_in_day / TS_PER_DAY
        if TTE <= 0: return [], 0.0

        orders: List[Order] = []
        current_opt_delta = 0.0
        
        # Snapshot current delta and find opportunities
        opps = []
        for K in VEV_STRIKES:
            sym = f"VEV_{K}"
            pos = state.position.get(sym, 0)
            delta = bs_delta(S, K, TTE, self.VEV_SIGMA_MODEL)
            current_opt_delta += pos * delta
            
            if sym not in state.order_depths: continue
            od = state.order_depths[sym]
            fair = bs_call(S, K, TTE, self.VEV_SIGMA_MODEL)
            b, a = _best_bid_ask(od)
            if a is not None and a <= fair - self.VEV_EDGE_REQ:
                opps.append(('BUY', sym, K, a, fair - a, delta))
            if b is not None and b >= fair + self.VEV_EDGE_REQ:
                opps.append(('SELL', sym, K, b, b - fair, delta))

        opps.sort(key=lambda x: x[4], reverse=True)

        for side, sym, K, px, edge, delta in opps:
            pos = state.position.get(sym, 0)
            lim = self.LIMITS[sym]
            if side == 'BUY':
                qty = min(-state.order_depths[sym].sell_orders[px], lim - pos, self.VEV_TAKE_SIZE)
                potential_delta = qty * delta
                if abs(current_opt_delta + potential_delta) < abs(current_opt_delta) or abs(current_opt_delta + potential_delta) <= self.VEV_DELTA_MAX_UNHEDGED:
                    if qty > 0: orders.append(Order(sym, px, qty)); current_opt_delta += potential_delta
            else:
                qty = min(state.order_depths[sym].buy_orders[px], lim + pos, self.VEV_TAKE_SIZE)
                potential_delta = -qty * delta
                if abs(current_opt_delta + potential_delta) < abs(current_opt_delta) or abs(current_opt_delta + potential_delta) <= self.VEV_DELTA_MAX_UNHEDGED:
                    if qty > 0: orders.append(Order(sym, px, -qty)); current_opt_delta += potential_delta
        
        return orders, current_opt_delta

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._restore(state.traderData)
        self.tick += 1
        result: Dict[str, List[Order]] = {}

        if self.ENABLE_HYDROGEL:
            result[HYDROGEL] = self._hydrogel(state)

        if self.ENABLE_VFE_ALPHA:
            result[VFE] = self._vfe_logic(state)

        if self.ENABLE_VEV_GAMMA:
            vev_orders, _ = self._vev_logic(state)
            for o in vev_orders:
                result.setdefault(o.symbol, []).append(o)

        return result, 0, self._serialise()