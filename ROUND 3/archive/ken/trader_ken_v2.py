"""
trader_ken_v2.py — Round 3 attempt #2.

What changed from v1 (and why)
==============================
v1 bled from +1.5k to -5.5k on a short live backtest. Four concrete leaks:

  L1: HYDROGEL fair was 0.65*EWMA + 0.35*anchor(9995). When live mid was
      above/below the anchor the fair was off by 5-15 XIRECs — we sold too
      cheap into rallies and bought too rich into dips.
          FIX: fair = EWMA of mid only. Anchor used only as a safety clamp.

  L2: HYDROGEL quotes were placed at fair±1 inside a natural market spread
      of ~16. We became the fastest wall and ate toxic flow.
          FIX: join the touch (fair±1 but clamped to bb+1 / ba-1), not
          inside the touch. Also widen take_edge to 2.

  L3: day_guess in traderData never incremented → TTE always computed as
      if day=0, inflating VEV fair by ~20% on day 2. Phantom edge.
          FIX: track cumulative timestamp across ticks, derive day from it.

  L4: Delta hedge was take-and-go with dead band 10, max per tick 20. ~50
      hedges/day × ~60 XIRECs spread cost = >3k/day of pure carry drag,
      more than the gamma we capture at 40-lot option positions.
          FIX: dead band 30, max per tick 15, passive hedges when possible.

Module gates
------------
ENABLE_HYDROGEL = True   (safe; the R1/R2 pattern)
ENABLE_VEV      = False  (needs a clean HYDROGEL baseline first)
ENABLE_HEDGE    = False  (off until VEV is on)

Turn VEV + HEDGE on together after confirming HYDROGEL alone prints
~80-100k on the capsule.
"""

from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState


# ─── Black-Scholes (no scipy, pure stdlib) ─────────────────────────────────
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


# ─── Product constants ─────────────────────────────────────────────────────
HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]
TIMESTAMP_UNITS_PER_DAY = 1_000_000


class Trader:
    # ── Feature flags ──────────────────────────────────────────────────────
    ENABLE_HYDROGEL = True
    ENABLE_VEV = False
    ENABLE_HEDGE = False

    # ── Position limits (guess; tune empirically) ──────────────────────────
    LIMITS: Dict[str, int] = {
        HYDROGEL: 80,
        VFE: 80,
        **{s: 60 for s in VEV_SYMBOLS},
    }

    # ── HYDROGEL v2 params ─────────────────────────────────────────────────
    HP_SAFETY_ANCHOR = 9995
    HP_SAFETY_CLAMP = 40            # clamp fair to anchor ± 40
    HP_EWMA_ALPHA = 0.15            # faster adaptation than v1's 0.05
    HP_TAKE_EDGE = 2                # was 1 → was taking everything
    HP_QUOTE_FRONT_SIZE = 25
    HP_QUOTE_SECOND_SIZE = 15
    HP_SKEW_SOFT = 20
    HP_SKEW_HARD = 45
    HP_FLATTEN_HARD = 65
    HP_MIN_QUOTE_EDGE = 1           # minimum distance from fair for passive quotes

    # ── VEV params (deliberately timid v2) ─────────────────────────────────
    VEV_SIGMA_DAY = 0.015           # more conservative than v1's 0.018
    VEV_MIN_EDGE = 8.0              # was 4 → much stricter
    VEV_SIZE_PER_EDGE = 1           # was 3 → much smaller
    VEV_MAX_SIZE = 20               # was 40
    VEV_ACTIVE_STRIKES = [5200, 5300]  # just the cleanest two to start

    # ── Hedge params (calmer) ──────────────────────────────────────────────
    HEDGE_DEAD_BAND = 30
    HEDGE_MAX_PER_TICK = 15
    HEDGE_EVERY_N_TICKS = 5

    def __init__(self):
        self.history: Dict = {}

    # ── state ──────────────────────────────────────────────────────────────
    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("last_ts", -1)
        self.history.setdefault("cum_ts", 0)
        self.history.setdefault("day", 0)
        self.history.setdefault("tick_count", 0)

        # Day roll-over detection: in the harness, timestamp resets at each
        # day. If current < last_ts, a day boundary was crossed.
        ts = state.timestamp
        last = int(self.history["last_ts"])
        if 0 <= ts < last:
            self.history["day"] = int(self.history["day"]) + 1
        self.history["cum_ts"] = int(self.history["day"]) * TIMESTAMP_UNITS_PER_DAY + ts
        self.history["last_ts"] = ts
        self.history["tick_count"] = int(self.history["tick_count"]) + 1

    def _save_state(self) -> str:
        return json.dumps(self.history)

    # ── helpers ────────────────────────────────────────────────────────────
    @staticmethod
    def _best_bid_ask(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    @staticmethod
    def _mid(depth: OrderDepth) -> Optional[float]:
        bb, ba = (
            max(depth.buy_orders.keys()) if depth.buy_orders else None,
            min(depth.sell_orders.keys()) if depth.sell_orders else None,
        )
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0

    def _tte_days(self, timestamp: int) -> float:
        # TTE = 7 starting from day 1, so at day D t=0 TTE = 8 - D days.
        day = int(self.history.get("day", 0))
        return max(0.01, (8 - day) - timestamp / TIMESTAMP_UNITS_PER_DAY)

    # ── MODULE 1: HYDROGEL_PACK ────────────────────────────────────────────
    def _hydrogel_logic(self, state: TradingState) -> List[Order]:
        if HYDROGEL not in state.order_depths:
            return []
        depth = state.order_depths[HYDROGEL]
        bb, ba = self._best_bid_ask(depth)
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0

        # Fair = EWMA of mid, clamped to safety anchor ± HP_SAFETY_CLAMP
        prev = self.history.get("hp_ewma")
        ewma = mid if prev is None else (1 - self.HP_EWMA_ALPHA) * prev + self.HP_EWMA_ALPHA * mid
        clamp_lo = self.HP_SAFETY_ANCHOR - self.HP_SAFETY_CLAMP
        clamp_hi = self.HP_SAFETY_ANCHOR + self.HP_SAFETY_CLAMP
        fair = max(clamp_lo, min(clamp_hi, ewma))
        self.history["hp_ewma"] = ewma

        pos = state.position.get(HYDROGEL, 0)
        limit = self.LIMITS[HYDROGEL]
        orders: List[Order] = []

        # -- take mispriced liquidity (only at wider edge than v1) --
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

        # -- inventory-based skew --
        if abs(pos) >= self.HP_FLATTEN_HARD:
            skew = -int(math.copysign(3, pos))
        elif abs(pos) >= self.HP_SKEW_HARD:
            skew = -int(math.copysign(2, pos))
        elif abs(pos) >= self.HP_SKEW_SOFT:
            skew = -int(math.copysign(1, pos))
        else:
            skew = 0

        # -- passive quotes: clamp to one tick INSIDE the touch, not inside --
        # i.e. if market is 9992/10008, don't quote 9999/10001 (inside both sides
        # of the natural spread); quote at bb+1 max on bid, ba-1 min on ask.
        desired_bid = int(round(fair + skew - self.HP_MIN_QUOTE_EDGE))
        desired_ask = int(round(fair + skew + self.HP_MIN_QUOTE_EDGE))
        quote_bid = min(desired_bid, bb + 1)     # never quote above market best bid + 1
        quote_ask = max(desired_ask, ba - 1)     # never quote below market best ask - 1
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

            if ba < fair - self.VEV_MIN_EDGE and pos < limit:
                edge = fair - ba
                room = limit - pos
                target = min(room, int(edge * self.VEV_SIZE_PER_EDGE))
                avail = -depth.sell_orders[ba]
                size = min(target, avail)
                if size > 0:
                    orders.append(Order(sym, ba, size))
                    pos += size

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

    # ── MODULE 3: VFE hedge (calmer) ───────────────────────────────────────
    def _hedge_logic(self, state: TradingState, option_deltas: Dict[str, float]) -> List[Order]:
        if VFE not in state.order_depths:
            return []

        # Throttle hedge frequency
        if int(self.history.get("tick_count", 0)) % self.HEDGE_EVERY_N_TICKS != 0:
            return []

        depth = state.order_depths[VFE]
        bb, ba = self._best_bid_ask(depth)
        if bb is None or ba is None:
            return []

        portfolio_delta = sum(option_deltas.values())
        target_vfe = int(round(-portfolio_delta))
        limit = self.LIMITS[VFE]
        target_vfe = max(-limit, min(limit, target_vfe))

        vfe_pos = state.position.get(VFE, 0)
        residual = target_vfe - vfe_pos
        if abs(residual) <= self.HEDGE_DEAD_BAND:
            return []

        size = max(-self.HEDGE_MAX_PER_TICK, min(self.HEDGE_MAX_PER_TICK, residual))
        # Passive hedge when residual is modest: join the touch, don't cross
        if abs(residual) <= self.HEDGE_DEAD_BAND * 2:
            if size > 0:
                return [Order(VFE, bb + 1, size)]   # passive bid just above best
            return [Order(VFE, ba - 1, size)]       # passive ask just below best
        # Aggressive hedge when we are well off delta
        if size > 0:
            return [Order(VFE, ba, size)]
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
            for o in vev_orders:
                result.setdefault(o.symbol, []).append(o)

        if self.ENABLE_HEDGE and option_deltas:
            hedge_orders = self._hedge_logic(state, option_deltas)
            if hedge_orders:
                result.setdefault(VFE, []).extend(hedge_orders)

        return result, 0, self._save_state()
