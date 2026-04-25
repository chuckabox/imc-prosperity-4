"""
trader_ken_v4_hp_tuned.py — v3 with sweep-tuned HYDROGEL knobs.

Identical to v3 except HP_OBI_THRESHOLD=0.10 (was 0.15) and
HP_LEAN_OFFSET_DEFENSIVE=2 (was 3). Sweep over 108 combos showed those two
tweaks lift 3-day total from +25,111 to +25,248. Marginal but free.

Original v3 docstring follows ──────────────────────────────────────────
trader_ken_v3.py — OBI-aware market making on HYDROGEL.

Why this exists
===============
v1 bled (peak +1.5k → -5.5k). v2 was flat (± 3k, net 0). Both failed
because HYDROGEL's market has two features we hadn't modelled:

  (A) The market spread is 15-16 wide but bid_vol_1 ≈ 15, ask_vol_1 ≈ 15.
      There is essentially **no MM competition inside that spread**.
      Naïvely quoting inside captures a fat spread **but also eats the
      directional flow** that's about to swing mid by ±4.

  (B) Top-of-book **order-book imbalance (OBI)** predicts the next move
      with extreme consistency:
          OBI = (bid_vol_1 - ask_vol_1) / (bid_vol_1 + ask_vol_1)
          OBI >  0.15 → mid moves +3 to +4 over next 1-10 ticks
          OBI < -0.15 → mid moves -3 to -4 over next 1-10 ticks
      Holds on all 3 capsule days, ~280 signals/day total.

Isolation-test on day-0 capsule:
  • 78 events with OBI > 0.3 → passive-buy-at-bb+1, exit-next-mid: +516 (~6.6/trade)
  • 65 events with OBI < -0.3 → passive-sell-at-ba-1, exit-next-mid: +463 (~7.1/trade)
  • 9,682 neutral ticks with avg inside-spread room of **14 XIRECs**.

Strategy
========
Three states per tick, based on OBI of the top-of-book:

  1. BULLISH (obi > +0.15):
        Quote an aggressive bid at bb+1 with big size, **skip the ask**
        (or quote far out). We want inventory going into the up-move,
        not to sell before it.

  2. BEARISH (obi < -0.15):
        Quote an aggressive ask at ba-1 with big size, **skip the bid**.
        Sell into the pre-move for a short position.

  3. NEUTRAL (|obi| ≤ 0.15):
        Symmetric MM at bb+1 / ba-1, inside the fat spread. This is
        where the 14-unit spread gets captured.

Layered on top:
  • Fair value from EWMA of mid (not an anchor — v1's mistake).
  • Inventory skew pulls quotes toward flat when position is large.
  • Take-when-crossed logic for rare mispricings (take_edge=2).
  • VEV / HEDGE modules disabled by default (their alpha is real but
    marginal vs hedge costs at our sizes — return in v4).
"""

from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState


# ─── helpers ───────────────────────────────────────────────────────────────
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
    ENABLE_VEV = False
    ENABLE_HEDGE = False

    LIMITS: Dict[str, int] = {
        HYDROGEL: 80,
        VFE: 80,
        **{s: 60 for s in VEV_SYMBOLS},
    }

    # ── HYDROGEL v3: OBI-aware MM ──────────────────────────────────────────
    HP_EWMA_ALPHA = 0.20            # fast-reacting fair
    HP_TAKE_EDGE = 2
    HP_OBI_THRESHOLD = 0.10         # tuned (was 0.15) — sweep top-10 all use 0.10
    HP_OBI_STRONG = 0.35            # extra-aggressive tier

    # Passive sizing when OBI is neutral
    HP_NEUTRAL_FRONT = 20           # bid & ask @ inside-spread
    HP_NEUTRAL_SECOND = 12          # bid-2 & ask+2

    # Lean sizing when OBI is directional
    HP_LEAN_AGGRESSIVE = 30         # favoured side
    HP_LEAN_DEFENSIVE = 6           # opposite side (still quote a little to avoid 0 P&L)
    HP_LEAN_OFFSET_DEFENSIVE = 2    # tuned (was 3)

    # Inventory management
    HP_SKEW_SOFT = 25               # start skewing quotes toward flat
    HP_SKEW_HARD = 50
    HP_FLATTEN_HARD = 70            # cancel the inventory-adding side entirely

    # ── VEV params (unused by default) ─────────────────────────────────────
    VEV_SIGMA_DAY = 0.015
    VEV_MIN_EDGE = 10.0
    VEV_SIZE_PER_EDGE = 1
    VEV_MAX_SIZE = 15
    VEV_ACTIVE_STRIKES = [5300]

    # ── Hedge params (unused by default) ───────────────────────────────────
    HEDGE_DEAD_BAND = 30
    HEDGE_MAX_PER_TICK = 10
    HEDGE_EVERY_N_TICKS = 10

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

    # ── helpers ────────────────────────────────────────────────────────────
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

    def _tte_days(self, timestamp: int) -> float:
        day = int(self.history.get("day", 0))
        return max(0.01, (8 - day) - timestamp / TIMESTAMP_UNITS_PER_DAY)

    # ── MODULE 1: HYDROGEL with OBI ────────────────────────────────────────
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

        # ── 1. TAKE mispriced liquidity (rare but pure alpha) ──────────────
        if ba <= fair - self.HP_TAKE_EDGE and pos < limit:
            sz = min(limit - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(HYDROGEL, ba, sz))
                pos += sz
        if bb >= fair + self.HP_TAKE_EDGE and pos > -limit:
            sz = min(limit + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(HYDROGEL, bb, -sz))
                pos -= sz

        # ── 2. Decide OBI regime and corresponding quote shape ─────────────
        if obi > self.HP_OBI_THRESHOLD:
            # Bullish — want inventory
            bullish = True; bearish = False
        elif obi < -self.HP_OBI_THRESHOLD:
            bullish = False; bearish = True
        else:
            bullish = False; bearish = False

        # ── 3. Per-side sizing ─────────────────────────────────────────────
        room_long = max(0, limit - pos)
        room_short = max(0, limit + pos)

        # inventory gate: if very long, cut bid entirely (avoid adding)
        if pos >= self.HP_FLATTEN_HARD:
            buy_front = 0
            buy_second = 0
        else:
            if bullish:
                buy_front = min(self.HP_LEAN_AGGRESSIVE, room_long)
            elif bearish:
                buy_front = min(self.HP_LEAN_DEFENSIVE, room_long)
            else:
                buy_front = min(self.HP_NEUTRAL_FRONT, room_long)
            buy_second = min(self.HP_NEUTRAL_SECOND, max(0, room_long - buy_front))

        if pos <= -self.HP_FLATTEN_HARD:
            sell_front = 0
            sell_second = 0
        else:
            if bearish:
                sell_front = min(self.HP_LEAN_AGGRESSIVE, room_short)
            elif bullish:
                sell_front = min(self.HP_LEAN_DEFENSIVE, room_short)
            else:
                sell_front = min(self.HP_NEUTRAL_FRONT, room_short)
            sell_second = min(self.HP_NEUTRAL_SECOND, max(0, room_short - sell_front))

        # ── 4. Inventory skew of the passive prices ────────────────────────
        # pos > 0 → skew quotes DOWN (sell more, buy higher-priced)
        if pos >= self.HP_SKEW_HARD:
            price_skew = -2
        elif pos >= self.HP_SKEW_SOFT:
            price_skew = -1
        elif pos <= -self.HP_SKEW_HARD:
            price_skew = 2
        elif pos <= -self.HP_SKEW_SOFT:
            price_skew = 1
        else:
            price_skew = 0

        # ── 5. Quote prices ────────────────────────────────────────────────
        # Neutral: bb+1 / ba-1.
        # Bullish (want long): bid at bb+1 (or even bb+2 if tight), ask one tick above ba (defensive).
        # Bearish: ask at ba-1 (or ba-2), bid one tick below bb (defensive).
        if bullish:
            quote_bid = bb + 1 + price_skew
            quote_ask = ba + self.HP_LEAN_OFFSET_DEFENSIVE + price_skew
        elif bearish:
            quote_bid = bb - self.HP_LEAN_OFFSET_DEFENSIVE + price_skew
            quote_ask = ba - 1 + price_skew
        else:
            quote_bid = bb + 1 + price_skew
            quote_ask = ba - 1 + price_skew

        # Safety clamps: never cross ourselves
        if quote_bid >= quote_ask:
            quote_bid = quote_ask - 1

        quote_bid2 = quote_bid - 2
        quote_ask2 = quote_ask + 2

        # ── 6. Emit orders ─────────────────────────────────────────────────
        if buy_front > 0:
            orders.append(Order(HYDROGEL, quote_bid, buy_front))
        if sell_front > 0:
            orders.append(Order(HYDROGEL, quote_ask, -sell_front))
        if buy_second > 0:
            orders.append(Order(HYDROGEL, quote_bid2, buy_second))
        if sell_second > 0:
            orders.append(Order(HYDROGEL, quote_ask2, -sell_second))

        return orders

    # ── MODULE 2 & 3 are unchanged from v2 (disabled by default) ───────────
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
            bb, ba, _, _ = self._top(depth)
            if bb is None or ba is None:
                continue
            fair = bs_call(vfe_mid, K, T, sigma)
            delta = bs_delta(vfe_mid, K, T, sigma)
            pos = state.position.get(sym, 0)
            limit = min(self.LIMITS[sym], self.VEV_MAX_SIZE)
            if ba < fair - self.VEV_MIN_EDGE and pos < limit:
                edge = fair - ba
                size = min(limit - pos, int(edge * self.VEV_SIZE_PER_EDGE),
                           -depth.sell_orders[ba])
                if size > 0:
                    orders.append(Order(sym, ba, size))
                    pos += size
            if bb > fair + self.VEV_MIN_EDGE and pos > -limit:
                edge = bb - fair
                size = min(limit + pos, int(edge * self.VEV_SIZE_PER_EDGE),
                           depth.buy_orders[bb])
                if size > 0:
                    orders.append(Order(sym, bb, -size))
                    pos -= size
            deltas[sym] = pos * delta
        return orders, deltas

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
        # always passive: join inside the spread, never cross
        if size > 0:
            return [Order(VFE, bb + 1, size)]
        return [Order(VFE, ba - 1, size)]

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
            for o in self._hedge_logic(state, option_deltas):
                result.setdefault(VFE, []).append(o)

        return result, 0, self._save_state()
