"""
trader_ken_v1.py — Round 3 starter: HYDROGEL MM + VFE hedge + VEV long-gamma.

Design in one page
==================
Three independent modules that each return a list of Orders, composed by
`run()`:

  1. HYDROGEL_PACK market-maker (mean-reversion around 9,995).
     Half-life from capsule ≈ 301 ticks → aggressive skew OK.

  2. VEV option book (long-gamma carry).
     IV in capsule ≈ 1.26%/day, realised ≈ 2.15%/day → options are ~42% cheap.
     We buy any VEV whose ask is below BS(sigma=0.018/day, no-arb haircut),
     size proportional to edge, respecting per-strike limits.

  3. VFE delta hedge.
     Target position = -Σ_K (pos_K * Δ_K). Rebalance when |residual Δ| > band.

All modules are feature-flagged via class constants so backtests can isolate
contribution.

TTE convention
--------------
Options were issued on day 1 with TTE=7 days. So at day D, timestamp t:
    TTE_days = (8 - D) - t / 1_000_000
Live days 3+ continue the decay; TTE never goes negative within the round.

Position limits
---------------
Round 3 limits not yet known — we expose them in `LIMITS` and the live run
should re-detect via empirical tightness. R2 used 80 for top-level symbols.
"""

from __future__ import annotations

import json
import math
from typing import Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState


# ─── Black-Scholes helpers (no scipy — competition env may not have it) ────
_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    # Abramowitz & Stegun 7.1.26 approximation; abs err < 7.5e-8
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


# ─── Product constants ─────────────────────────────────────────────────────
HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]

TIMESTAMP_UNITS_PER_DAY = 1_000_000


class Trader:
    # ── Feature flags (set False to disable a module for A/B backtests) ────
    ENABLE_HYDROGEL = True
    ENABLE_VEV = True
    ENABLE_HEDGE = True

    # ── Position limits (guess; override once round 3 limits are known) ───
    LIMITS: Dict[str, int] = {
        HYDROGEL: 80,
        VFE: 80,
        **{s: 60 for s in VEV_SYMBOLS},
    }

    # ── HYDROGEL market-making parameters ──────────────────────────────────
    HP_ANCHOR = 9995            # capsule mean ≈ 9991; anchor slightly above
    HP_VWAP_WEIGHT = 0.65       # blend live mid (0.65) with static anchor (0.35)
    HP_TAKE_EDGE = 1            # cross the spread when mispriced by ≥ 1
    HP_QUOTE_FRONT_SIZE = 28
    HP_QUOTE_SECOND_SIZE = 20
    HP_SKEW_SOFT = 15
    HP_SKEW_HARD = 35
    HP_FLATTEN_HARD = 58        # flatten aggressively near limit

    # ── VEV pricing / entry parameters ─────────────────────────────────────
    VEV_SIGMA_DAY = 0.018       # model σ (20% haircut on the 0.0215 realised)
    VEV_MIN_EDGE = 4.0          # XIRECs of edge required before entering
    VEV_SIZE_PER_EDGE = 3       # 3 lots per XIREC of edge
    VEV_MAX_SIZE = 40           # per strike (leave room under LIMITS for hedge)
    VEV_ACTIVE_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
    # Ignore: 4000/4500 (delta-1 proxies), 6000/6500 (illiquid, stuck at 0/1)

    # ── Hedge parameters ───────────────────────────────────────────────────
    HEDGE_DEAD_BAND = 10        # only hedge if residual |Δ| > 10 VFE units
    HEDGE_MAX_PER_TICK = 20     # cap churn

    def __init__(self):
        self.history: Dict = {}

    # ── state persistence ──────────────────────────────────────────────────
    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("hp_mid_ewma", None)
        self.history.setdefault("vfe_mid_ewma", None)
        self.history.setdefault("day_guess", 0)

    def _save_state(self) -> str:
        return json.dumps(self.history)

    # ── market-data helpers ────────────────────────────────────────────────
    @staticmethod
    def _best_bid_ask(depth: OrderDepth) -> Tuple[int | None, int | None]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    @staticmethod
    def _mid(depth: OrderDepth) -> float | None:
        bb, ba = (
            max(depth.buy_orders.keys()) if depth.buy_orders else None,
            min(depth.sell_orders.keys()) if depth.sell_orders else None,
        )
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0

    # ── TTE calculation ────────────────────────────────────────────────────
    def _tte_days(self, timestamp: int) -> float:
        # Live days 3+: day index increments across capsule roll-over.
        # For the backtest (3 capsule days concatenated), the harness resets
        # timestamp each day, so we infer day from a counter in traderData.
        day = int(self.history.get("day_guess", 0))
        return max(0.01, (8 - day) - timestamp / TIMESTAMP_UNITS_PER_DAY)

    # ── MODULE 1: HYDROGEL_PACK market maker ───────────────────────────────
    def _hydrogel_logic(self, state: TradingState) -> List[Order]:
        if HYDROGEL not in state.order_depths:
            return []
        depth = state.order_depths[HYDROGEL]
        bb, ba = self._best_bid_ask(depth)
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        prev_ewma = self.history.get("hp_mid_ewma") or mid
        ewma = 0.95 * prev_ewma + 0.05 * mid
        self.history["hp_mid_ewma"] = ewma

        fair = self.HP_VWAP_WEIGHT * ewma + (1 - self.HP_VWAP_WEIGHT) * self.HP_ANCHOR
        pos = state.position.get(HYDROGEL, 0)
        limit = self.LIMITS[HYDROGEL]
        orders: List[Order] = []

        # -- take mispriced liquidity at the touch --
        if ba <= fair - self.HP_TAKE_EDGE and pos < limit:
            size = min(limit - pos, -depth.sell_orders[ba])
            if size > 0:
                orders.append(Order(HYDROGEL, ba, size))
                pos += size

        if bb >= fair + self.HP_TAKE_EDGE and pos > -limit:
            size = min(limit + pos, depth.buy_orders[bb])
            if size > 0:
                orders.append(Order(HYDROGEL, bb, -size))
                pos -= size

        # -- skew quotes around fair based on current inventory --
        if abs(pos) >= self.HP_FLATTEN_HARD:
            # flatten: lean hard in the unwinding direction
            skew = -int(math.copysign(3, pos))
        elif abs(pos) >= self.HP_SKEW_HARD:
            skew = -int(math.copysign(2, pos))
        elif abs(pos) >= self.HP_SKEW_SOFT:
            skew = -int(math.copysign(1, pos))
        else:
            skew = 0

        quote_bid = int(round(fair + skew)) - 1
        quote_ask = int(round(fair + skew)) + 1
        quote_bid2 = quote_bid - 2
        quote_ask2 = quote_ask + 2

        room_long = max(0, limit - pos)
        room_short = max(0, limit + pos)

        front_buy = min(self.HP_QUOTE_FRONT_SIZE, room_long)
        front_sell = min(self.HP_QUOTE_FRONT_SIZE, room_short)
        second_buy = min(self.HP_QUOTE_SECOND_SIZE, max(0, room_long - front_buy))
        second_sell = min(self.HP_QUOTE_SECOND_SIZE, max(0, room_short - front_sell))

        if front_buy > 0:
            orders.append(Order(HYDROGEL, quote_bid, front_buy))
        if front_sell > 0:
            orders.append(Order(HYDROGEL, quote_ask, -front_sell))
        if second_buy > 0:
            orders.append(Order(HYDROGEL, quote_bid2, second_buy))
        if second_sell > 0:
            orders.append(Order(HYDROGEL, quote_ask2, -second_sell))

        return orders

    # ── MODULE 2: VEV option book ──────────────────────────────────────────
    def _vev_logic(self, state: TradingState) -> Tuple[List[Order], Dict[str, float]]:
        """Returns (orders, deltas_by_symbol) where deltas are post-trade."""
        orders: List[Order] = []
        deltas: Dict[str, float] = {}

        if VFE not in state.order_depths:
            return orders, deltas
        vfe_mid = self._mid(state.order_depths[VFE])
        if vfe_mid is None:
            return orders, deltas

        T = self._tte_days(state.timestamp)
        sigma = self.VEV_SIGMA_DAY

        for K in self.VEV_ACTIVE_STRIKES:
            sym = f"VEV_{K}"
            if sym not in state.order_depths:
                continue
            depth = state.order_depths[sym]
            bb, ba = self._best_bid_ask(depth)
            if bb is None or ba is None:
                continue

            fair = bs_call(vfe_mid, K, T, sigma)
            delta = bs_delta(vfe_mid, K, T, sigma)
            pos = state.position.get(sym, 0)
            limit = min(self.LIMITS[sym], self.VEV_MAX_SIZE)

            # buy if ask < fair - min_edge
            if ba < fair - self.VEV_MIN_EDGE and pos < limit:
                edge = fair - ba
                room = limit - pos
                target = min(room, int(edge * self.VEV_SIZE_PER_EDGE))
                avail = -depth.sell_orders[ba]
                size = min(target, avail)
                if size > 0:
                    orders.append(Order(sym, ba, size))
                    pos += size

            # sell if bid > fair + min_edge (symmetric safety)
            if bb > fair + self.VEV_MIN_EDGE and pos > -limit:
                edge = bb - fair
                room = limit + pos
                target = min(room, int(edge * self.VEV_SIZE_PER_EDGE))
                avail = depth.buy_orders[bb]
                size = min(target, avail)
                if size > 0:
                    orders.append(Order(sym, bb, -size))
                    pos -= size

            deltas[sym] = pos * delta

        return orders, deltas

    # ── MODULE 3: VFE delta hedge ─────────────────────────────────────────
    def _hedge_logic(self, state: TradingState, option_deltas: Dict[str, float]) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        depth = state.order_depths[VFE]
        bb, ba = self._best_bid_ask(depth)
        if bb is None or ba is None:
            return []

        portfolio_delta = sum(option_deltas.values())
        target_vfe = int(round(-portfolio_delta))

        vfe_pos = state.position.get(VFE, 0)
        limit = self.LIMITS[VFE]
        target_vfe = max(-limit, min(limit, target_vfe))

        residual = target_vfe - vfe_pos
        if abs(residual) <= self.HEDGE_DEAD_BAND:
            return []

        size = max(-self.HEDGE_MAX_PER_TICK, min(self.HEDGE_MAX_PER_TICK, residual))
        if size > 0:
            # buy at ask
            return [Order(VFE, ba, size)]
        else:
            return [Order(VFE, bb, size)]

    # ── ORCHESTRATION ──────────────────────────────────────────────────────
    def run(self, state: TradingState):
        self._load_state(state)

        result: Dict[str, List[Order]] = {}

        if self.ENABLE_HYDROGEL:
            hp_orders = self._hydrogel_logic(state)
            if hp_orders:
                result[HYDROGEL] = hp_orders

        option_deltas: Dict[str, float] = {}
        if self.ENABLE_VEV:
            vev_orders, option_deltas = self._vev_logic(state)
            # Group by symbol
            for o in vev_orders:
                result.setdefault(o.symbol, []).append(o)

        if self.ENABLE_HEDGE and option_deltas:
            hedge_orders = self._hedge_logic(state, option_deltas)
            if hedge_orders:
                result.setdefault(VFE, []).extend(hedge_orders)

        return result, 0, self._save_state()
