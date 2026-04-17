"""
trader_robust_peter_v10_safe.py
===============================
V10 SAFE — ken_v6b's upside mechanics, peter_v6_safe's guardrails.

ken_v6b raised mean PnL over v6_safe by:
  (a) gradual pepper accumulation (PEPPER_ADD_PER_TICK): spreads entry
      cost across ~12 ticks instead of 1, saving ~$500 of spread-cross.
  (b) tighter osmium take-edge (1 tick) + larger quotes (25/18): more
      fills inside the 16-tick resting spread.

But v6b's winrate dropped because of three fragilities — kept intact:
  (F1) consecutive-negative-slope stop trips on normal drift noise
       (1-up-1-down patterns) and is permanent (never recovers).
  (F2) TAKE_EDGE=1 with size 25 bleeds fast if the anchor is wrong
       or flow is toxically one-sided.
  (F3) binary skew: no graduated response to extreme positions.

v10_safe preserves (a) and (b) — and replaces each fragility:

  PEPPER
  ------
  1. KEEP gradual accumulation (tick-budget) — v6b's main PnL unlock.
  2. Adaptive tick-budget: start at 5/tick, ramp to 10/tick only after
     20 ticks of confirmed positive drift (reduce early-noise entry cost).
  3. Adaptive cap: 30 until drift confirmed, then 60 (v6b's full cap).
  4. Magnitude-based stop (slope < -8 over 20-tick window) + hysteresis
     (requires 2 consecutive magnitude breaches) — fixes (F1) false trips.
  5. Recovery: if slope > +5 after stop, re-enable — fixes (F1) permanence.
  6. Chunked flatten (15/tick) when stopped, not a market dump.
  7. Take only at ask <= mid (tighter than v6b's mid+1): no negative-edge
     entries; gradual accumulation already handles the missed fills.
  8. Passive bid capped at 10 to limit per-tick adverse fills.

  OSMIUM
  ------
  1. KEEP take-edge 1 — v6b's ambition, still sound under stable anchor.
  2. NEW toxic-flow gate: skip taking this tick if last-tick tape shows
     40+ lots of one-sided aggression — fixes (F2) adverse-fill bleed.
  3. NEW anchor-sanity: if 20-tick mid median drifts > 6 from 10,000,
     halve quote sizes (defensive degrade, not abandonment) — fixes (F2)
     on anchor-drift regimes.
  4. Graduated 3-tier skew (0 / 1 / 2 ticks at |pos| > 22 / 45) —
     fixes (F3) by increasing the unwinding pressure continuously.
  5. Quote sizes 22/15 (between v6_safe 20/15 and v6b 25/18): keeps most
     of v6b's edge capture while reducing per-fill inventory shock.
  6. Earlier flatten (55 vs 60): smaller tail on adverse mean reversion.
  7. Hard clamp: quotes never more than ±4 from anchor (avoids runaway
     skew quoting outside the natural 9996..10004 zone).
"""

import json
from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState, Symbol


class Trader:
    LIMIT = 80

    # --- PEPPER ---
    PEPPER_MAX_LONG_INIT = 30
    PEPPER_MAX_LONG_FULL = 60
    PEPPER_ADD_PER_TICK_INIT = 5
    PEPPER_ADD_PER_TICK_FULL = 10
    PEPPER_DRIFT_CONFIRM_TICKS = 20
    PEPPER_SLOPE_WINDOW = 20
    PEPPER_STOP_THRESHOLD = -8
    PEPPER_STOP_HYSTERESIS = 2
    PEPPER_RESUME_THRESHOLD = 5
    PEPPER_PASSIVE_CAP = 10
    PEPPER_FLATTEN_CHUNK = 15

    # --- OSMIUM ---
    OSMIUM_ANCHOR = 10_000
    OSMIUM_TAKE_EDGE = 1
    OSMIUM_QUOTE_SIZE = 22
    OSMIUM_SECOND_SIZE = 15
    OSMIUM_SKEW_SOFT = 22
    OSMIUM_SKEW_HARD = 45
    OSMIUM_FLATTEN = 55
    OSMIUM_ANCHOR_DRIFT_THRESHOLD = 6
    OSMIUM_ANCHOR_DRIFT_TICKS = 20
    OSMIUM_TOXIC_VOLUME = 40
    OSMIUM_CLAMP = 4

    def __init__(self):
        self.history: Dict[str, list] = {}

    def _load_state(self, state: TradingState):
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}

    # ------------------------------------------------------------------
    # PEPPER_ROOT — gradual accumulator with magnitude guard + recovery
    # ------------------------------------------------------------------
    def _pepper_logic(self, state: TradingState) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)

        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0

        hist = self.history.get("pp", [])
        hist.append(mid)
        if len(hist) > 80:
            hist = hist[-80:]
        self.history["pp"] = hist

        stop_breach = int(self.history.get("pp_breach", 0))
        drift_stopped = bool(self.history.get("pp_stopped", False))
        drift_confirm = int(self.history.get("pp_confirm", 0))

        slope = 0.0
        if len(hist) >= self.PEPPER_SLOPE_WINDOW:
            window = hist[-self.PEPPER_SLOPE_WINDOW:]
            slope = window[-1] - window[0]
            if slope < self.PEPPER_STOP_THRESHOLD:
                stop_breach += 1
            else:
                stop_breach = 0
            if stop_breach >= self.PEPPER_STOP_HYSTERESIS:
                drift_stopped = True
            elif drift_stopped and slope > self.PEPPER_RESUME_THRESHOLD:
                drift_stopped = False

        if slope > 0:
            drift_confirm = min(drift_confirm + 1, self.PEPPER_DRIFT_CONFIRM_TICKS)

        confirmed = drift_confirm >= self.PEPPER_DRIFT_CONFIRM_TICKS
        max_long = self.PEPPER_MAX_LONG_FULL if confirmed else self.PEPPER_MAX_LONG_INIT
        add_per_tick = (
            self.PEPPER_ADD_PER_TICK_FULL if confirmed else self.PEPPER_ADD_PER_TICK_INIT
        )

        self.history["pp_breach"] = stop_breach
        self.history["pp_stopped"] = drift_stopped
        self.history["pp_confirm"] = drift_confirm

        orders: List[Order] = []

        if drift_stopped:
            if pos > 0:
                avail = depth.buy_orders.get(bb, 0)
                qty = min(pos, avail, self.PEPPER_FLATTEN_CHUNK)
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        rem_cap = max_long - pos
        if rem_cap <= 0:
            return orders

        tick_budget = min(rem_cap, add_per_tick)

        for ask in sorted(depth.sell_orders.keys()):
            if tick_budget <= 0:
                break
            avail = -depth.sell_orders[ask]
            if avail <= 0:
                continue
            if ask <= mid:
                qty = min(tick_budget, avail)
                orders.append(Order(product, ask, qty))
                tick_budget -= qty

        if tick_budget > 0:
            passive_qty = min(tick_budget, self.PEPPER_PASSIVE_CAP)
            orders.append(Order(product, bb + 1, passive_qty))

        return orders

    # ------------------------------------------------------------------
    # OSMIUM — Resin MM with toxic-flow + anchor-sanity guards
    # ------------------------------------------------------------------
    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)

        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        fair = self.OSMIUM_ANCHOR

        hist = self.history.get("op", [])
        hist.append(mid)
        if len(hist) > 60:
            hist = hist[-60:]
        self.history["op"] = hist

        anchor_off = False
        if len(hist) >= self.OSMIUM_ANCHOR_DRIFT_TICKS:
            recent = hist[-self.OSMIUM_ANCHOR_DRIFT_TICKS:]
            avg = sum(recent) / len(recent)
            if abs(avg - fair) > self.OSMIUM_ANCHOR_DRIFT_THRESHOLD:
                anchor_off = True

        size_scale = 0.5 if anchor_off else 1.0
        front_qty = max(6, int(self.OSMIUM_QUOTE_SIZE * size_scale))
        second_qty = max(4, int(self.OSMIUM_SECOND_SIZE * size_scale))

        toxic_skip = False
        if product in state.market_trades:
            buy_vol = sum(
                abs(t.quantity) for t in state.market_trades[product] if t.price >= mid
            )
            sell_vol = sum(
                abs(t.quantity) for t in state.market_trades[product] if t.price < mid
            )
            if (
                max(buy_vol, sell_vol) >= self.OSMIUM_TOXIC_VOLUME
                and abs(buy_vol - sell_vol) >= self.OSMIUM_TOXIC_VOLUME
            ):
                toxic_skip = True

        orders: List[Order] = []
        rem_buy = self.LIMIT - pos
        rem_sell = self.LIMIT + pos

        if not toxic_skip:
            for ask in sorted(depth.sell_orders.keys()):
                if ask <= fair - self.OSMIUM_TAKE_EDGE and rem_buy > 0:
                    avail = -depth.sell_orders[ask]
                    qty = min(rem_buy, avail)
                    if qty > 0:
                        orders.append(Order(product, ask, qty))
                        rem_buy -= qty
                        pos += qty

            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid >= fair + self.OSMIUM_TAKE_EDGE and rem_sell > 0:
                    avail = depth.buy_orders[bid]
                    qty = min(rem_sell, avail)
                    if qty > 0:
                        orders.append(Order(product, bid, -qty))
                        rem_sell -= qty
                        pos -= qty

        if pos > self.OSMIUM_FLATTEN and rem_sell > 0:
            qty = min(pos - self.OSMIUM_FLATTEN + 5, rem_sell)
            if qty > 0:
                orders.append(Order(product, fair, -qty))
                rem_sell -= qty
        elif pos < -self.OSMIUM_FLATTEN and rem_buy > 0:
            qty = min(-pos - self.OSMIUM_FLATTEN + 5, rem_buy)
            if qty > 0:
                orders.append(Order(product, fair, qty))
                rem_buy -= qty

        abs_pos = abs(pos)
        if abs_pos > self.OSMIUM_SKEW_HARD:
            skew = 2
        elif abs_pos > self.OSMIUM_SKEW_SOFT:
            skew = 1
        else:
            skew = 0
        skew_dir = 1 if pos > 0 else -1

        bid_price = min(bb + 1, fair - 1) - skew * skew_dir
        ask_price = max(ba - 1, fair + 1) - skew * skew_dir

        bid_price = max(int(bid_price), fair - self.OSMIUM_CLAMP)
        ask_price = min(int(ask_price), fair + self.OSMIUM_CLAMP)

        if bid_price >= ask_price:
            bid_price = fair - 1
            ask_price = fair + 1

        if rem_buy > 0:
            front = min(rem_buy, front_qty)
            orders.append(Order(product, int(bid_price), front))
            rem_buy -= front
            if rem_buy > 0:
                orders.append(
                    Order(product, int(bid_price - 1), min(rem_buy, second_qty))
                )

        if rem_sell > 0:
            front = min(rem_sell, front_qty)
            orders.append(Order(product, int(ask_price), -front))
            rem_sell -= front
            if rem_sell > 0:
                orders.append(
                    Order(product, int(ask_price + 1), -min(rem_sell, second_qty))
                )

        return orders

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        pep = self._pepper_logic(state)
        if pep:
            result["INTARIAN_PEPPER_ROOT"] = pep

        osm = self._osmium_logic(state)
        if osm:
            result["ASH_COATED_OSMIUM"] = osm

        return result, 0, json.dumps(self.history)
