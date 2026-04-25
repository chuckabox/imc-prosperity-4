"""trader_ken_v4_vev.py — v3 HYDROGEL OBI-MM + VEV long-gamma + delta hedge.

Why this exists
===============
v3 (HYDROGEL only) backtests at +25k over 3 days. Stable but well short of
the 330k target. The remaining alpha lives in the **VEV options complex**:
implied vol prices at ~1.26%/day, realized vol is ~2.15%/day. Options are
underpriced by ~30-50 XIRECs each.

v3's VEV logic only TAKES when the ask sits below BS-fair by 10+. That
fires rarely (~16 trades/day) for marginal P&L. v4_vev does the harder
thing: **post resting bids inside the option spread** so that the bots
running the option market HIT us, paying us the spread plus the IV/RV
margin.

To prevent the long option position from becoming a directional VFE bet,
we run a **delta hedge** in VFE on a wide dead band — small enough to
neutralize big swings, lazy enough to avoid bleeding to the wide HYDROGEL-
sized hedge spreads.

Module layout
=============
1. HYDROGEL (same engine as v3, parameters TBD from sweep)
2. VEV long-gamma:
     - For each active strike, post resting buys at min(bb+1, fair - buy_edge)
       provided we're below position cap.
     - Optionally take crossing asks if very deeply mispriced.
     - Never sell options (the IV/RV alpha is one-sided).
3. VFE delta hedge:
     - Sum option deltas, target -delta_total in VFE.
     - Only act if |residual| > dead_band, every N ticks.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState


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


HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]
TIMESTAMP_UNITS_PER_DAY = 1_000_000


class Trader:
    # ── Feature flags ──────────────────────────────────────────────────────
    ENABLE_HYDROGEL = True
    ENABLE_VEV = True
    ENABLE_HEDGE = False

    LIMITS: Dict[str, int] = {
        HYDROGEL: 80,
        VFE: 80,
        **{s: 60 for s in VEV_SYMBOLS},
    }

    # ── HYDROGEL knobs (placeholder = v3 defaults; will tune after sweep) ──
    HP_EWMA_ALPHA = 0.20
    HP_TAKE_EDGE = 2
    HP_OBI_THRESHOLD = 0.15
    HP_OBI_STRONG = 0.35
    HP_NEUTRAL_FRONT = 20
    HP_NEUTRAL_SECOND = 12
    HP_LEAN_AGGRESSIVE = 30
    HP_LEAN_DEFENSIVE = 6
    HP_LEAN_OFFSET_DEFENSIVE = 3
    HP_SKEW_SOFT = 25
    HP_SKEW_HARD = 50
    HP_FLATTEN_HARD = 70

    # ── VEV knobs (resting bids inside the spread) ─────────────────────────
    VEV_SIGMA = 0.018                              # conservative vs realized 0.0215
    VEV_ACTIVE_STRIKES = [5100, 5200, 5300, 5400]  # gamma core: fan across the smile
    VEV_BID_EDGE_REQ = 2.0                         # post a bid if (bb+1) < fair-2
    VEV_TAKE_EDGE = 8.0                            # take crossing asks only if generously below
    VEV_PER_STRIKE_CAP = 30                        # max long size per strike
    VEV_BID_SIZE = 8                               # passive bid size per tick

    # ── Hedge knobs (lazy — let small inventory ride) ──────────────────────
    HEDGE_DEAD_BAND = 25                 # only hedge if |residual| > 25 VFE units
    HEDGE_MAX_PER_TICK = 5               # small chunks
    HEDGE_EVERY_N_TICKS = 20

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
        self.history.setdefault("day", 0)
        self.history.setdefault("tick_count", 0)

        ts = state.timestamp
        last = int(self.history["last_ts"])
        if 0 <= ts < last:
            self.history["day"] = int(self.history["day"]) + 1
        self.history["last_ts"] = ts
        self.history["tick_count"] = int(self.history["tick_count"]) + 1

    def _save_state(self) -> str:
        return json.dumps(self.history)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int], int, int]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        bv = depth.buy_orders[bb] if bb is not None else 0
        av = -depth.sell_orders[ba] if ba is not None else 0
        return bb, ba, bv, av

    @staticmethod
    def _mid(depth: OrderDepth) -> Optional[float]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0

    def _tte_days(self, ts: int) -> float:
        day = int(self.history.get("day", 0))
        return max(0.01, (8 - day) - ts / TIMESTAMP_UNITS_PER_DAY)

    # ── MODULE 1: HYDROGEL with OBI (identical engine to v3) ───────────────
    def _hydrogel_logic(self, state: TradingState) -> List[Order]:
        if HYDROGEL not in state.order_depths:
            return []
        depth = state.order_depths[HYDROGEL]
        bb, ba, bv, av = self._top(depth)
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        prev = self.history.get("hp_ewma")
        ewma = mid if prev is None else (1 - self.HP_EWMA_ALPHA) * prev + self.HP_EWMA_ALPHA * mid
        self.history["hp_ewma"] = ewma
        fair = ewma

        obi = (bv - av) / (bv + av) if (bv + av) > 0 else 0.0

        pos = state.position.get(HYDROGEL, 0)
        limit = self.LIMITS[HYDROGEL]
        orders: List[Order] = []

        if ba <= fair - self.HP_TAKE_EDGE and pos < limit:
            sz = min(limit - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(HYDROGEL, ba, sz)); pos += sz
        if bb >= fair + self.HP_TAKE_EDGE and pos > -limit:
            sz = min(limit + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(HYDROGEL, bb, -sz)); pos -= sz

        if obi > self.HP_OBI_THRESHOLD:
            bullish, bearish = True, False
        elif obi < -self.HP_OBI_THRESHOLD:
            bullish, bearish = False, True
        else:
            bullish, bearish = False, False

        room_long = max(0, limit - pos)
        room_short = max(0, limit + pos)

        if pos >= self.HP_FLATTEN_HARD:
            buy_front = buy_second = 0
        else:
            if bullish: buy_front = min(self.HP_LEAN_AGGRESSIVE, room_long)
            elif bearish: buy_front = min(self.HP_LEAN_DEFENSIVE, room_long)
            else: buy_front = min(self.HP_NEUTRAL_FRONT, room_long)
            buy_second = min(self.HP_NEUTRAL_SECOND, max(0, room_long - buy_front))

        if pos <= -self.HP_FLATTEN_HARD:
            sell_front = sell_second = 0
        else:
            if bearish: sell_front = min(self.HP_LEAN_AGGRESSIVE, room_short)
            elif bullish: sell_front = min(self.HP_LEAN_DEFENSIVE, room_short)
            else: sell_front = min(self.HP_NEUTRAL_FRONT, room_short)
            sell_second = min(self.HP_NEUTRAL_SECOND, max(0, room_short - sell_front))

        if pos >= self.HP_SKEW_HARD: price_skew = -2
        elif pos >= self.HP_SKEW_SOFT: price_skew = -1
        elif pos <= -self.HP_SKEW_HARD: price_skew = 2
        elif pos <= -self.HP_SKEW_SOFT: price_skew = 1
        else: price_skew = 0

        if bullish:
            quote_bid = bb + 1 + price_skew
            quote_ask = ba + self.HP_LEAN_OFFSET_DEFENSIVE + price_skew
        elif bearish:
            quote_bid = bb - self.HP_LEAN_OFFSET_DEFENSIVE + price_skew
            quote_ask = ba - 1 + price_skew
        else:
            quote_bid = bb + 1 + price_skew
            quote_ask = ba - 1 + price_skew

        if quote_bid >= quote_ask:
            quote_bid = quote_ask - 1

        quote_bid2 = quote_bid - 2
        quote_ask2 = quote_ask + 2

        if buy_front > 0: orders.append(Order(HYDROGEL, quote_bid, buy_front))
        if sell_front > 0: orders.append(Order(HYDROGEL, quote_ask, -sell_front))
        if buy_second > 0: orders.append(Order(HYDROGEL, quote_bid2, buy_second))
        if sell_second > 0: orders.append(Order(HYDROGEL, quote_ask2, -sell_second))
        return orders

    # ── MODULE 2: VEV — resting bids inside the spread + opportunistic take ─
    def _vev_logic(self, state: TradingState) -> Tuple[List[Order], Dict[str, float]]:
        orders: List[Order] = []
        deltas: Dict[str, float] = {}

        if VFE not in state.order_depths:
            return orders, deltas
        vfe_mid = self._mid(state.order_depths[VFE])
        if vfe_mid is None:
            return orders, deltas

        T = self._tte_days(state.timestamp)
        sigma = self.VEV_SIGMA

        for K in self.VEV_ACTIVE_STRIKES:
            sym = f"VEV_{K}"
            if sym not in state.order_depths:
                continue
            depth = state.order_depths[sym]
            bb, ba, bv, av = self._top(depth)
            if bb is None or ba is None:
                continue

            fair = bs_call(vfe_mid, K, T, sigma)
            delta = bs_delta(vfe_mid, K, T, sigma)
            pos = state.position.get(sym, 0)
            cap = min(self.LIMITS[sym], self.VEV_PER_STRIKE_CAP)

            # ── (a) take if seller crosses generously below fair ──────────
            if ba < fair - self.VEV_TAKE_EDGE and pos < cap:
                ask_size = -depth.sell_orders[ba]
                size = min(cap - pos, ask_size)
                if size > 0:
                    orders.append(Order(sym, ba, size))
                    pos += size

            # ── (b) post a passive bid at bb+1 IF that price is still cheap ─
            quote_bid = bb + 1
            if quote_bid <= fair - self.VEV_BID_EDGE_REQ and pos < cap:
                size = min(self.VEV_BID_SIZE, cap - pos)
                if size > 0:
                    orders.append(Order(sym, quote_bid, size))
                    # Note: we don't pre-credit pos here because it's a resting bid.

            # Track delta exposure for hedger (uses CURRENT pos, not the
            # speculative post-fill pos — the hedger acts on confirmed deltas).
            deltas[sym] = pos * delta

        return orders, deltas

    # ── MODULE 3: VFE delta hedge ──────────────────────────────────────────
    def _hedge_logic(self, state: TradingState, option_deltas: Dict[str, float]) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        if int(self.history.get("tick_count", 0)) % self.HEDGE_EVERY_N_TICKS != 0:
            return []
        depth = state.order_depths[VFE]
        bb, ba, _, _ = self._top(depth)
        if bb is None or ba is None:
            return []

        target = int(round(-sum(option_deltas.values())))
        limit = self.LIMITS[VFE]
        target = max(-limit, min(limit, target))
        vfe_pos = state.position.get(VFE, 0)
        residual = target - vfe_pos
        if abs(residual) <= self.HEDGE_DEAD_BAND:
            return []

        size = max(-self.HEDGE_MAX_PER_TICK, min(self.HEDGE_MAX_PER_TICK, residual))
        # Always passive: post inside the spread, never cross.
        if size > 0:
            return [Order(VFE, bb + 1, size)]
        return [Order(VFE, ba - 1, size)]

    # ── ORCHESTRATION ──────────────────────────────────────────────────────
    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        if self.ENABLE_HYDROGEL:
            for o in self._hydrogel_logic(state):
                result.setdefault(o.symbol, []).append(o)

        option_deltas: Dict[str, float] = {}
        if self.ENABLE_VEV:
            vev_orders, option_deltas = self._vev_logic(state)
            for o in vev_orders:
                result.setdefault(o.symbol, []).append(o)

        if self.ENABLE_HEDGE and option_deltas:
            for o in self._hedge_logic(state, option_deltas):
                result.setdefault(VFE, []).append(o)

        return result, 0, self._save_state()
