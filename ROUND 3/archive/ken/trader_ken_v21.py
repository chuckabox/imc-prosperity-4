"""trader_ken_v21.py — Long Gamma Engine with Delta Hedging

Core insight: Market IV (1.26%/day) << Realized Vol (2.15%/day).
VEV options are structurally CHEAP relative to actual VFE volatility.

Strategy:
  1. HYDROGEL: keep market-making as stable base (~2-3k/session)
  2. VEV options: aggressively BUY calls on 5100/5200/5300 when
     market ask < BS-fair(RV) - 5 ticks. The BS edge is ~35-45 ticks/contract.
  3. VFE: delta-hedge accumulated call positions each tick to stay
     directional-neutral. Gamma P&L accrues from VFE volatility exceeding IV.

Expected gamma P&L for 48 ATM VEV_5200 contracts:
  ≈ 0.5 × Γ × σ²_real × S² × 48 ≈ 16,000/day → 48K over 3 days (theoretical max)
  With partial fills and hedging costs, target is 15-30K.

Strikes 5100/5200/5300 only: highest gamma, and full-limit deltas fit within
the VFE-80 hedge budget (44×0.73 + 48×0.58 + 44×0.43 ≈ 79 VFE short).
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"

# High-gamma strikes only — their full-limit delta fits within VFE limit 80
VEV_ACTIVE = [5100, 5200, 5300]
VEV_LIMITS  = {5100: 44, 5200: 48, 5300: 44}


# ── Black-Scholes helpers (standard-library only) ─────────────────────────

def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_fair(S: float, K: int, sigma: float, T: float) -> float:
    """European call price via Black-Scholes."""
    if T <= 0.0:
        return max(S - K, 0.0)
    sq = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sq)
    d2 = d1 - sigma * sq
    return S * _ncdf(d1) - K * _ncdf(d2)


def _bs_delta(S: float, K: int, sigma: float, T: float) -> float:
    """Delta of a European call."""
    if T <= 0.0:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return _ncdf(d1)


# ─────────────────────────────────────────────────────────────────────────

class Trader:
    ENABLE_HYDROGEL  = True
    ENABLE_VEV_GAMMA = True
    ENABLE_VFE_HEDGE = True

    # ── HYDROGEL (unchanged from v20) ────────────────────────────────────
    HP_LIMIT      = 80
    HP_ANCHOR     = 9993.0
    HP_EWMA_ALPHA = 0.20
    HP_TAKER_EDGE = 2.0
    HP_MAKER_EDGE = 2.0
    HP_TAKER_MAX  = 20
    HP_MAKER_SIZE = 15

    # ── VEV long-gamma taker ─────────────────────────────────────────────
    VEV_SIGMA     = 0.0215   # realized vol per day (2.15%)
    VEV_TTE_INIT  = 7.0      # days to expiry at start of Round 3
    VEV_BUY_EDGE  = 5.0      # buy when ask ≤ BS_fair - 5  (edge is ~40 ticks, always fires)
    VEV_BUY_SIZE  = 15       # max contracts per taker hit

    # ── VFE delta hedge ───────────────────────────────────────────────────
    VFE_LIMIT     = 80
    VFE_DEADBAND  = 3        # skip rebalance if off by ≤ 3 units (cuts churn cost)

    # ─────────────────────────────────────────────────────────────────────

    def __init__(self):
        self.history: Dict = {}

    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("ticks", 0)

    def _save_state(self) -> str:
        return json.dumps(self.history)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders)  if depth.buy_orders  else None
        ba = min(depth.sell_orders) if depth.sell_orders else None
        return bb, ba

    # ── Guarded maker (passive quotes, never crosses book) ───────────────

    def _guarded_maker(
        self,
        symbol: str,
        depth: OrderDepth,
        pos: int,
        fair: float,
        limit: int,
        edge: float,
        max_qty: Optional[int] = None,
    ) -> List[Order]:
        orders = []
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []
        qbid = int(round(fair - edge))
        qask = int(round(fair + edge))
        if qbid >= ba:  qbid = ba - 1
        if qask <= bb:  qask = bb + 1
        if qbid >= qask: qbid = qask - 1
        rl = limit - pos
        rs = limit + pos
        if max_qty is not None:
            rl = min(rl, max_qty)
            rs = min(rs, max_qty)
        if rl > 0: orders.append(Order(symbol, qbid,  rl))
        if rs > 0: orders.append(Order(symbol, qask, -rs))
        return orders

    # ── HYDROGEL market-making ───────────────────────────────────────────

    def _hydrogel_logic(self, state: TradingState) -> List[Order]:
        depth = state.order_depths.get(HYDROGEL)
        if depth is None:
            return []
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []

        mid  = (bb + ba) / 2.0
        prev = self.history.get("hp_ewma")
        ewma = mid if prev is None else (1 - self.HP_EWMA_ALPHA) * prev + self.HP_EWMA_ALPHA * mid
        self.history["hp_ewma"] = ewma
        fair = 0.6 * ewma + 0.4 * self.HP_ANCHOR

        pos = state.position.get(HYDROGEL, 0)
        lim = self.HP_LIMIT
        orders: List[Order] = []

        if ba <= fair - self.HP_TAKER_EDGE and pos < lim:
            sz = min(self.HP_TAKER_MAX, lim - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(HYDROGEL, ba, sz))
                pos += sz
        if bb >= fair + self.HP_TAKER_EDGE and pos > -lim:
            sz = min(self.HP_TAKER_MAX, lim + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(HYDROGEL, bb, -sz))
                pos -= sz

        orders.extend(
            self._guarded_maker(HYDROGEL, depth, pos, fair, lim, self.HP_MAKER_EDGE, max_qty=self.HP_MAKER_SIZE)
        )
        return orders

    # ── VEV long-gamma accumulation ──────────────────────────────────────

    def _vev_gamma_logic(self, state: TradingState, vfe_mid: float, tte: float) -> List[Order]:
        orders: List[Order] = []
        for strike in VEV_ACTIVE:
            sym = f"VEV_{strike}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            _, ba = self._top(depth)
            if ba is None:
                continue

            fair_bs = _bs_fair(vfe_mid, strike, self.VEV_SIGMA, tte)
            pos = state.position.get(sym, 0)
            lim = VEV_LIMITS[strike]

            # Taker: buy when market ask is significantly below BS fair value
            if ba <= fair_bs - self.VEV_BUY_EDGE and pos < lim:
                sz = min(self.VEV_BUY_SIZE, lim - pos, -depth.sell_orders[ba])
                if sz > 0:
                    orders.append(Order(sym, ba, sz))

        return orders

    # ── VFE delta hedge ───────────────────────────────────────────────────

    def _vfe_hedge_logic(self, state: TradingState, vfe_mid: float, tte: float) -> List[Order]:
        # Sum delta across all active VEV positions
        total_delta = sum(
            state.position.get(f"VEV_{k}", 0) * _bs_delta(vfe_mid, k, self.VEV_SIGMA, tte)
            for k in VEV_ACTIVE
        )

        # Target VFE position is negative delta to offset long call exposure
        target  = int(round(-total_delta))
        target  = max(-self.VFE_LIMIT, min(self.VFE_LIMIT, target))
        current = state.position.get(VFE, 0)
        diff    = target - current

        if abs(diff) <= self.VFE_DEADBAND:
            return []

        depth = state.order_depths.get(VFE)
        if depth is None:
            return []
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []

        orders: List[Order] = []
        if diff > 0:   # need more VFE long (delta rose — options went more OTM)
            sz = min(diff, self.VFE_LIMIT - current, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(VFE, ba, sz))
        else:          # need more VFE short (delta rose from option going ITM)
            sz = min(-diff, self.VFE_LIMIT + current, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(VFE, bb, -sz))

        return orders

    # ── Main entry point ──────────────────────────────────────────────────

    def run(self, state: TradingState):
        self._load_state(state)
        self.history["ticks"] += 1
        # TTE decreases by 1 day every 10,000 ticks (one competition day)
        tte = max(0.1, self.VEV_TTE_INIT - self.history["ticks"] / 10000.0)

        result: Dict[str, List[Order]] = {}

        if self.ENABLE_HYDROGEL:
            for o in self._hydrogel_logic(state):
                result.setdefault(o.symbol, []).append(o)

        # VFE mid price needed for BS calculations
        vfe_mid = None
        if VFE in state.order_depths:
            bb, ba = self._top(state.order_depths[VFE])
            if bb is not None and ba is not None:
                vfe_mid = (bb + ba) / 2.0

        if vfe_mid is not None:
            if self.ENABLE_VEV_GAMMA:
                for o in self._vev_gamma_logic(state, vfe_mid, tte):
                    result.setdefault(o.symbol, []).append(o)

            if self.ENABLE_VFE_HEDGE:
                for o in self._vfe_hedge_logic(state, vfe_mid, tte):
                    result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save_state()
