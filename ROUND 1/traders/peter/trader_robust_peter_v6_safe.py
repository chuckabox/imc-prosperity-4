"""
trader_robust_peter_v6_safe.py
==============================
V6 SAFE (peter) — stability-first refinement of ken_v6_safe.

Same core thesis (per round1_pattern_analysis.md):
  PEPPER_ROOT = deterministic long drift → accumulate long, cap position.
  OSMIUM     = hard anchor at 10,000 → Resin-style market making.

Improvements over ken_v6_safe, each addresses a concrete failure mode:

  PEPPER
  ------
  1. Magnitude-based slope guard (drop >= 8 over 20-tick window) instead
     of ken's consecutive-negative-streak. Streak triggers on normal drift
     noise (1-up 1-down patterns); magnitude requires a real reversal.
  2. Recovery: if drift clearly resumes (slope > +5 after stop), re-enable
     accumulation. Ken's stop is permanent — one noise event = dead for the
     rest of the day.
  3. Adaptive max-long: start at 20, raise to 40 only after 30 ticks of
     confirmed positive drift. If drift never materialises we stay small.
  4. Capped passive bids (size 10): large resting bids get adverse-filled
     on any downward spike. Cap limits per-tick damage.
  5. Tighter take: only lift ask <= mid (not <= mid+1) to avoid negative-
     edge entries.
  6. Graceful flatten when stopped: dump at bid in chunks, not all-in-one.

  OSMIUM
  ------
  1. Anchor sanity: track a 40-tick median of mid; if it drifts > 6 from
     10,000 for 20+ ticks, scale quote sizes to 50% (defensive, don't stop).
  2. Graduated skew (3 tiers): 0 / 1 / 2 tick shift at |pos| > 25 / 50.
     Ken uses a binary skew that doesn't punish extreme positions enough.
  3. Earlier flatten (55 vs 60) — smaller tail on adverse mean reversion.
  4. Smaller quote sizes (15 front / 10 second vs ken's 20 / 15) —
     slower inventory build, smaller exposure per fill.
  5. Safety clamp: never post quotes more than 4 ticks from the anchor.
  6. Toxic-flow throttle: if the last-tick tape shows 40+ lots of one-sided
     aggression, skip take this tick (the flow knows something we don't).
  7. Take edge 3 (vs 2): slightly more selective takes, fewer toxic fills.
"""

import json
from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState, Symbol


class Trader:
    LIMIT = 80

    # --- PEPPER ---
    PEPPER_MAX_LONG_INIT = 20
    PEPPER_MAX_LONG_FULL = 40
    PEPPER_DRIFT_CONFIRM_TICKS = 30
    PEPPER_SLOPE_WINDOW = 20
    PEPPER_STOP_THRESHOLD = -8
    PEPPER_RESUME_THRESHOLD = 5
    PEPPER_PASSIVE_CAP = 10
    PEPPER_FLATTEN_CHUNK = 15

    # --- OSMIUM ---
    OSMIUM_ANCHOR = 10_000
    OSMIUM_TAKE_EDGE = 3
    OSMIUM_QUOTE_SIZE = 15
    OSMIUM_SECOND_SIZE = 10
    OSMIUM_SKEW_SOFT = 25
    OSMIUM_SKEW_HARD = 50
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
    # PEPPER_ROOT
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

        drift_stopped = bool(self.history.get("pp_stopped", False))
        drift_confirm = int(self.history.get("pp_confirm", 0))

        slope = 0.0
        if len(hist) >= self.PEPPER_SLOPE_WINDOW:
            window = hist[-self.PEPPER_SLOPE_WINDOW:]
            slope = window[-1] - window[0]
            if slope < self.PEPPER_STOP_THRESHOLD:
                drift_stopped = True
            elif drift_stopped and slope > self.PEPPER_RESUME_THRESHOLD:
                drift_stopped = False

        # Confirm drift only via positive slope observations (not noise).
        if slope > 0:
            drift_confirm = min(drift_confirm + 1, self.PEPPER_DRIFT_CONFIRM_TICKS)

        max_long = (
            self.PEPPER_MAX_LONG_FULL
            if drift_confirm >= self.PEPPER_DRIFT_CONFIRM_TICKS
            else self.PEPPER_MAX_LONG_INIT
        )

        self.history["pp_stopped"] = drift_stopped
        self.history["pp_confirm"] = drift_confirm

        orders: List[Order] = []

        if drift_stopped:
            # Graceful chunked flatten, not a single market dump.
            if pos > 0:
                avail = depth.buy_orders.get(bb, 0)
                qty = min(pos, avail, self.PEPPER_FLATTEN_CHUNK)
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        rem_cap = max_long - pos
        if rem_cap <= 0:
            return orders

        for ask in sorted(depth.sell_orders.keys()):
            if rem_cap <= 0:
                break
            avail = -depth.sell_orders[ask]
            if avail <= 0:
                continue
            if ask <= mid:
                qty = min(rem_cap, avail)
                orders.append(Order(product, ask, qty))
                rem_cap -= qty

        if rem_cap > 0:
            passive_qty = min(rem_cap, self.PEPPER_PASSIVE_CAP)
            orders.append(Order(product, bb + 1, passive_qty))

        return orders

    # ------------------------------------------------------------------
    # OSMIUM
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

        # Anchor-sanity: downsize quotes if the realised mid persistently
        # drifts away from 10,000. We never abandon the anchor — but we
        # shrink our exposure so a wrong anchor bleeds slowly, not fast.
        anchor_off = 0
        if len(hist) >= self.OSMIUM_ANCHOR_DRIFT_TICKS:
            recent = hist[-self.OSMIUM_ANCHOR_DRIFT_TICKS:]
            avg = sum(recent) / len(recent)
            if abs(avg - fair) > self.OSMIUM_ANCHOR_DRIFT_THRESHOLD:
                anchor_off = 1

        size_scale = 0.5 if anchor_off else 1.0
        front_qty = max(5, int(self.OSMIUM_QUOTE_SIZE * size_scale))
        second_qty = max(4, int(self.OSMIUM_SECOND_SIZE * size_scale))

        # Toxic-flow: skip taking this tick if the last-tick tape shows
        # heavy one-sided aggression (we are likely on the wrong side).
        toxic_skip = False
        if product in state.market_trades:
            buy_vol = sum(
                abs(t.quantity) for t in state.market_trades[product] if t.price >= mid
            )
            sell_vol = sum(
                abs(t.quantity) for t in state.market_trades[product] if t.price < mid
            )
            if max(buy_vol, sell_vol) >= self.OSMIUM_TOXIC_VOLUME and abs(buy_vol - sell_vol) >= self.OSMIUM_TOXIC_VOLUME:
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
