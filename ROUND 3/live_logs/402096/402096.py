"""trader3.py - Scaling up trader2 for high PnL targets.
Focused on aggressive HYDROGEL_PACK MM and calibrated VEV gamma.
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


def implied_vol(price: float, S: float, K: float, T: float,
                lo: float = 1e-4, hi: float = 2.0, n: int = 60) -> float | None:
    intrinsic = max(0.0, S - K)
    if price <= intrinsic + 1e-6 or price >= S:
        return None
    for _ in range(n):
        mid = 0.5 * (lo + hi)
        if bs_call(S, K, T, mid) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-5:
            break
    return 0.5 * (lo + hi)


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
    # ---- module enables ----
    ENABLE_HYDROGEL = True
    ENABLE_VFE_MM = False
    ENABLE_VEV_GAMMA = True
    ENABLE_IV_SCALP = False
    ENABLE_HEDGE = True
    ENABLE_CROSS_ARBITRAGE = True

    # ---- limits (R3 High-Capacity Test) ----
    LIMITS = {HYDROGEL: 400, VFE: 250, **{s: 100 for s in VEV_SYMBOLS}}

    # ---- HYDROGEL MM (Scaled) ----
    HP_ANCHOR = 9991.0
    HP_EWMA_ALPHA = 0.25
    HP_TAKE_EDGE = 2
    HP_QUOTE_FRONT = 80
    HP_QUOTE_SECOND = 60
    HP_SKEW_SOFT = 150
    HP_SKEW_HARD = 250
    HP_FLATTEN = 350

    # ---- VEV gamma ----
    VEV_SIGMA_MODEL = 0.014
    VEV_PRIMARY_STRIKES = [5100, 5200, 5300, 5400]
    VEV_SECONDARY_STRIKES = [5000, 5500]
    VEV_GAMMA_EDGE_REQ = 1.2
    VEV_GAMMA_SELL_EDGE = 1.2
    VEV_PER_STRIKE_CAP = 80
    VEV_TAKE_SIZE = 40

    # ---- delta hedge ----
    HEDGE_DEAD_BAND = 12
    HEDGE_MAX_PER_TICK = 40
    HEDGE_EVERY_N = 1

    def __init__(self) -> None:
        self.tick = 0
        self.hp_ewma: float | None = None
        self.vfe_ema: float | None = None
        self.last_vfe_mid: float | None = None

    def _serialise(self) -> str:
        return json.dumps({
            "tick": self.tick,
            "hp_ewma": self.hp_ewma,
            "vfe_ema": self.vfe_ema,
            "last_vfe_mid": self.last_vfe_mid
        })

    def _restore(self, td: str) -> None:
        if not td: return
        try:
            d = json.loads(td)
            self.tick = int(d.get("tick", 0))
            self.hp_ewma = d.get("hp_ewma")
            self.vfe_ema = d.get("vfe_ema")
            self.last_vfe_mid = d.get("last_vfe_mid")
        except Exception: pass

    def _hydrogel(self, state: TradingState) -> List[Order]:
        sym = HYDROGEL
        if sym not in state.order_depths: return []
        od = state.order_depths[sym]
        m = _mid(od)
        if m is None: return []
        if self.hp_ewma is None: self.hp_ewma = m
        self.hp_ewma = self.HP_EWMA_ALPHA * m + (1 - self.HP_EWMA_ALPHA) * self.hp_ewma
        
        # Balance anchor and moving average
        fair = 0.5 * self.hp_ewma + 0.5 * self.HP_ANCHOR
        pos = state.position.get(sym, 0)
        lim = self.LIMITS[sym]
        orders: List[Order] = []

        # 1) Aggressive Taker
        b, a = _best_bid_ask(od)
        if a is not None and a <= fair - self.HP_TAKE_EDGE:
            qty = min(-od.sell_orders[a], lim - pos)
            if qty > 0:
                orders.append(Order(sym, a, qty))
                pos += qty
        if b is not None and b >= fair + self.HP_TAKE_EDGE:
            qty = min(od.buy_orders[b], lim + pos)
            if qty > 0:
                orders.append(Order(sym, b, -qty))
                pos -= qty

        # 2) Quoting
        skew = 0
        if abs(pos) > self.HP_SKEW_HARD: skew = -2 if pos > 0 else 2
        elif abs(pos) > self.HP_SKEW_SOFT: skew = -1 if pos > 0 else 1

        bid_px = int(round(fair - 1 + skew))
        ask_px = int(round(fair + 1 + skew))
        
        max_buy = lim - pos
        max_sell = lim + pos
        if max_buy > 0:
            orders.append(Order(sym, bid_px, min(self.HP_QUOTE_FRONT, max_buy)))
            if max_buy > self.HP_QUOTE_FRONT:
                orders.append(Order(sym, bid_px - 2, min(self.HP_QUOTE_SECOND, max_buy - self.HP_QUOTE_FRONT)))
        if max_sell > 0:
            orders.append(Order(sym, ask_px, -min(self.HP_QUOTE_FRONT, max_sell)))
            if max_sell > self.HP_QUOTE_FRONT:
                orders.append(Order(sym, ask_px + 2, -min(self.HP_QUOTE_SECOND, max_sell - self.HP_QUOTE_FRONT)))

        return orders

    def _vev_logic(self, state: TradingState) -> Tuple[List[Order], float]:
        if VFE not in state.order_depths: return [], 0.0
        S = _mid(state.order_depths[VFE])
        if S is None: return [], 0.0
        day = int(state.timestamp // TS_PER_DAY)
        ts_in_day = state.timestamp % TS_PER_DAY
        TTE = (TOTAL_DAYS - day) - ts_in_day / TS_PER_DAY
        if TTE <= 0: return [], 0.0

        orders: List[Order] = []
        portfolio_delta = 0.0

        for K in VEV_STRIKES:
            sym = f"VEV_{K}"
            if sym not in state.order_depths: continue
            od = state.order_depths[sym]
            pos = state.position.get(sym, 0)
            lim = self.VEV_PER_STRIKE_CAP
            
            delta = bs_delta(S, K, TTE, self.VEV_SIGMA_MODEL)
            portfolio_delta += pos * delta
            
            fair = bs_call(S, K, TTE, self.VEV_SIGMA_MODEL)
            b, a = _best_bid_ask(od)
            
            # Gamma taker
            if a is not None and a <= fair - self.VEV_GAMMA_EDGE_REQ:
                qty = min(-od.sell_orders[a], lim - pos, self.VEV_TAKE_SIZE)
                if qty > 0:
                    orders.append(Order(sym, a, qty))
                    portfolio_delta += qty * delta
            if b is not None and b >= fair + self.VEV_GAMMA_SELL_EDGE:
                qty = min(od.buy_orders[b], lim + pos, self.VEV_TAKE_SIZE)
                if qty > 0:
                    orders.append(Order(sym, b, -qty))
                    portfolio_delta -= qty * delta
                    
        return orders, portfolio_delta

    def _hedge(self, state: TradingState, portfolio_delta: float, pending_orders: List[Order]) -> List[Order]:
        pos = state.position.get(VFE, 0)
        net_pending = sum(o.quantity for o in pending_orders if o.symbol == VFE)
        target = -int(round(portfolio_delta))
        delta = target - pos - net_pending
        if abs(delta) < self.HEDGE_DEAD_BAND: return []
        delta = max(min(delta, self.HEDGE_MAX_PER_TICK), -self.HEDGE_MAX_PER_TICK)
        lim = self.LIMITS[VFE]
        max_buy = lim - pos - net_pending
        max_sell = lim + pos + net_pending
        
        b, a = _best_bid_ask(state.order_depths.get(VFE, OrderDepth()))
        if delta > 0 and a is not None:
            qty = min(delta, max_buy)
            if qty > 0: return [Order(VFE, a, qty)]
        elif delta < 0 and b is not None:
            qty = min(-delta, max_sell)
            if qty > 0: return [Order(VFE, b, -qty)]
        return []

    def _cross_arbitrage(self, state: TradingState, prior_orders: List[Order]) -> List[Order]:
        strikes = sorted(VEV_STRIKES)
        orders: List[Order] = []
        temp_pos = {s: state.position.get(s, 0) for s in VEV_SYMBOLS}
        for o in prior_orders:
            if o.symbol in temp_pos: temp_pos[o.symbol] += o.quantity
        
        for i in range(len(strikes)):
            for j in range(i + 1, len(strikes)):
                K1, K2 = strikes[i], strikes[j]
                sym1, sym2 = f"VEV_{K1}", f"VEV_{K2}"
                if sym1 not in state.order_depths or sym2 not in state.order_depths: continue
                b1, a1 = _best_bid_ask(state.order_depths[sym1])
                b2, a2 = _best_bid_ask(state.order_depths[sym2])
                if b1 is None or a1 is None or b2 is None or a2 is None: continue

                if a1 < b2: # Buy low K1, Sell high K2
                    qty = min(self.LIMITS[sym1] - temp_pos[sym1], self.LIMITS[sym2] + temp_pos[sym2])
                    if qty > 0:
                        orders.extend([Order(sym1, a1, qty), Order(sym2, b2, -qty)])
                        temp_pos[sym1] += qty; temp_pos[sym2] -= qty
                if b1 - a2 > (K2 - K1): # Risk-free spread
                    qty = min(self.LIMITS[sym1] + temp_pos[sym1], self.LIMITS[sym2] - temp_pos[sym2])
                    if qty > 0:
                        orders.extend([Order(sym1, b1, -qty), Order(sym2, a2, qty)])
                        temp_pos[sym1] -= qty; temp_pos[sym2] += qty
        return orders

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._restore(state.traderData)
        self.tick += 1
        result: Dict[str, List[Order]] = {}
        all_orders: List[Order] = []

        if self.ENABLE_HYDROGEL:
            o = self._hydrogel(state)
            if o:
                result[HYDROGEL] = o
                all_orders.extend(o)

        portfolio_delta = 0.0
        if self.ENABLE_VEV_GAMMA:
            vev_orders, portfolio_delta = self._vev_logic(state)
            for o in vev_orders:
                result.setdefault(o.symbol, []).append(o)
            all_orders.extend(vev_orders)

        if self.ENABLE_HEDGE and (self.tick % self.HEDGE_EVERY_N == 0):
            o = self._hedge(state, portfolio_delta, all_orders)
            if o:
                result.setdefault(VFE, []).extend(o)
                all_orders.extend(o)

        if self.ENABLE_CROSS_ARBITRAGE:
            o = self._cross_arbitrage(state, all_orders)
            if o:
                for ord in o: result.setdefault(ord.symbol, []).append(ord)
                all_orders.extend(o)

        return result, 0, self._serialise()