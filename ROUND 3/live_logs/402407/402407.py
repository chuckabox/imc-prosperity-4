"""trader4.py - Official Round 3 Strategy.
Enforces limits: HYDROGEL_PACK=200, VELVETFRUIT_EXTRACT=200, VEV_VOUCHERS=300/strike.
Implements Delta-Neutral Capacity Management and Optimized Gamma Scalping.
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
    # ---- module enables ----
    ENABLE_HYDROGEL = True
    ENABLE_VEV_GAMMA = True
    ENABLE_HEDGE = True
    ENABLE_CROSS_ARBITRAGE = True

    # ---- Official Limits ----
    LIMITS = {
        HYDROGEL: 200,
        VFE: 200,
        **{s: 300 for s in VEV_SYMBOLS}
    }

    # ---- HYDROGEL MM ----
    HP_ANCHOR = 9991.0
    HP_EWMA_ALPHA = 0.30
    HP_TAKE_EDGE = 2
    HP_QUOTE_FRONT = 40
    HP_QUOTE_SECOND = 30
    HP_SKEW_SOFT = 60
    HP_SKEW_HARD = 120
    HP_FLATTEN = 180

    # ---- VEV Gamma ----
    VEV_SIGMA_MODEL = 0.014
    VEV_GAMMA_EDGE_REQ = 1.0
    VEV_TAKE_SIZE = 80
    VEV_DELTA_MAX_UNHEDGED = 190   # Capacity of VFE limit

    # ---- Delta Hedge ----
    HEDGE_DEAD_BAND = 15
    HEDGE_MAX_PER_TICK = 60

    def __init__(self) -> None:
        self.tick = 0
        self.hp_ewma: float | None = None

    def _serialise(self) -> str:
        return json.dumps({
            "tick": self.tick,
            "hp_ewma": self.hp_ewma
        })

    def _restore(self, td: str) -> None:
        if not td: return
        try:
            d = json.loads(td)
            self.tick = int(d.get("tick", 0))
            self.hp_ewma = d.get("hp_ewma")
        except Exception: pass

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

        # Taker
        b, a = _best_bid_ask(od)
        if a is not None and a <= fair - self.HP_TAKE_EDGE:
            qty = min(-od.sell_orders[a], lim - pos)
            if qty > 0: orders.append(Order(sym, a, qty)); pos += qty
        if b is not None and b >= fair + self.HP_TAKE_EDGE:
            qty = min(od.buy_orders[b], lim + pos)
            if qty > 0: orders.append(Order(sym, b, -qty)); pos -= qty

        # Quoter
        skew = 0
        if abs(pos) > self.HP_SKEW_HARD: skew = -2 if pos > 0 else 2
        elif abs(pos) > self.HP_SKEW_SOFT: skew = -1 if pos > 0 else 1

        bid_px = int(round(fair - 1 + skew))
        ask_px = int(round(fair + 1 + skew))
        
        max_buy = lim - pos
        max_sell = lim + pos
        if max_buy > 0:
            orders.append(Order(sym, bid_px, min(self.HP_QUOTE_FRONT, max_buy)))
        if max_sell > 0:
            orders.append(Order(sym, ask_px, -min(self.HP_QUOTE_FRONT, max_sell)))

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
        
        # Calculate current delta
        current_delta = 0.0
        for K in VEV_STRIKES:
            sym = f"VEV_{K}"
            pos = state.position.get(sym, 0)
            if pos != 0:
                current_delta += pos * bs_delta(S, K, TTE, self.VEV_SIGMA_MODEL)

        # Logic: prioritize strikes with most edge, but cap by delta capacity
        opportunities = []
        for K in VEV_STRIKES:
            sym = f"VEV_{K}"
            if sym not in state.order_depths: continue
            od = state.order_depths[sym]
            fair = bs_call(S, K, TTE, self.VEV_SIGMA_MODEL)
            b, a = _best_bid_ask(od)
            if a is not None and a <= fair - self.VEV_GAMMA_EDGE_REQ:
                opportunities.append(('BUY', sym, K, a, fair - a))
            if b is not None and b >= fair + self.VEV_GAMMA_EDGE_REQ:
                opportunities.append(('SELL', sym, K, b, b - fair))

        # Sort by edge descending
        opportunities.sort(key=lambda x: x[4], reverse=True)

        for side, sym, K, px, edge in opportunities:
            pos = state.position.get(sym, 0)
            lim = self.LIMITS[sym]
            delta = bs_delta(S, K, TTE, self.VEV_SIGMA_MODEL)
            
            if side == 'BUY':
                qty = min(-state.order_depths[sym].sell_orders[px], lim - pos, self.VEV_TAKE_SIZE)
                potential_delta = qty * delta
                # Only if it reduces delta OR we have capacity
                if abs(current_delta + potential_delta) < abs(current_delta) or abs(current_delta + potential_delta) <= self.VEV_DELTA_MAX_UNHEDGED:
                    if qty > 0:
                        orders.append(Order(sym, px, qty))
                        current_delta += potential_delta
            else:
                qty = min(state.order_depths[sym].buy_orders[px], lim + pos, self.VEV_TAKE_SIZE)
                potential_delta = -qty * delta
                if abs(current_delta + potential_delta) < abs(current_delta) or abs(current_delta + potential_delta) <= self.VEV_DELTA_MAX_UNHEDGED:
                    if qty > 0:
                        orders.append(Order(sym, px, -qty))
                        current_delta += potential_delta
                        
        return orders, current_delta

    def _hedge(self, state: TradingState, opt_delta: float, pending: List[Order]) -> List[Order]:
        pos = state.position.get(VFE, 0)
        net_pending = sum(o.quantity for o in pending if o.symbol == VFE)
        target = -int(round(opt_delta))
        delta = target - pos - net_pending
        if abs(delta) < self.HEDGE_DEAD_BAND: return []
        delta = max(min(delta, self.HEDGE_MAX_PER_TICK), -self.HEDGE_MAX_PER_TICK)
        
        lim = self.LIMITS[VFE]
        max_buy = lim - pos - net_pending
        max_sell = lim + pos + net_pending
        
        b, a = _best_bid_ask(state.order_depths.get(VFE, OrderDepth()))
        if delta > 0 and a is not None:
            q = min(delta, max_buy)
            if q > 0: return [Order(VFE, a, q)]
        elif delta < 0 and b is not None:
            q = min(-delta, max_sell)
            if q > 0: return [Order(VFE, b, -q)]
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

                if a1 < b2: # Arb: Buy K1, Sell K2
                    qty = min(self.LIMITS[sym1] - temp_pos[sym1], self.LIMITS[sym2] + temp_pos[sym2])
                    if qty > 0:
                        orders.extend([Order(sym1, a1, qty), Order(sym2, b2, -qty)])
                        temp_pos[sym1] += qty; temp_pos[sym2] -= qty
                if b1 - a2 > (K2 - K1): # Arb: Vertical spread violation
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
            if o: result[HYDROGEL] = o; all_orders.extend(o)

        opt_delta = 0.0
        if self.ENABLE_VEV_GAMMA:
            vev_orders, opt_delta = self._vev_logic(state)
            for o in vev_orders: result.setdefault(o.symbol, []).append(o)
            all_orders.extend(vev_orders)

        if self.ENABLE_HEDGE:
            o = self._hedge(state, opt_delta, all_orders)
            if o: result.setdefault(VFE, []).extend(o); all_orders.extend(o)

        if self.ENABLE_CROSS_ARBITRAGE:
            o = self._cross_arbitrage(state, all_orders)
            if o:
                for ord in o: result.setdefault(ord.symbol, []).append(ord)
                all_orders.extend(o)

        return result, 0, self._serialise()