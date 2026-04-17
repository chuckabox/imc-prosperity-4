"""
trader_robust_peter_v6d.py
==========================
V6d — drift-adaptive, robust: ken_v6c's regime-picking + v10_safe's guardrails.

ken_v6c's core innovation (kept): measure realized drift during a warmup
window, then pick the Pepper cap that matches the regime. Strong drift -> 80,
moderate -> 60, weak -> 30, negative -> 0.

Five fragilities in v6c, each fixed here:

  (F1) Slope is raw first-mid vs current-mid. One noisy tick at warmup
       start/end biases the regime decision permanently.
       FIX: smooth both endpoints (median of first 30 samples vs median
       of last 30). Keeps the warmup length short but removes spike risk.

  (F2) Warmup locks the cap forever. If a weak-drift morning turns into
       a strong-drift afternoon, we stay at cap 30 and leave money on
       the table.
       FIX: re-evaluate the cap every PEPPER_REEVAL_INTERVAL ticks after
       warmup. Only *upgrade* — never silently downgrade (the magnitude
       stop handles adverse reversals cleanly).

  (F3) Streak-based slope guard (5 consecutive negative 20-tick slopes).
       Noise patterns trigger it; once stopped we never recover.
       FIX: magnitude stop (slope < -8 over 20 ticks) with 2-tick
       hysteresis + recovery (slope > +5 re-enables). Same logic as
       v6_safe / v10_safe — field-proven pattern.

  (F4) Take `ask <= mid + 1` + uncapped passive bid -> negative-edge
       entries + large adverse fills on downspikes.
       FIX: take only at `ask <= mid`; passive bid capped at 10.

  (F5) Osmium: TAKE_EDGE 1 with 25-lot quotes and binary skew is fast
       bleed if the anchor drifts or flow is toxically one-sided. No
       price clamp lets the skew push quotes outside the natural zone.
       FIX: toxic-flow gate (skip takes when last-tick tape >= 40 lots
       one-sided); anchor-sanity (halve sizes if 20-tick median drifts
       > 6 from 10,000); 3-tier graduated skew at |pos| > 22/45; hard
       clamp ±4 from anchor; quotes 22/15 (pulled in from 25/18);
       flatten at 55 (was 60).
"""

import json
from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState, Symbol


def _median(vals: list) -> float:
    n = len(vals)
    if n == 0:
        return 0.0
    s = sorted(vals)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


class Trader:
    LIMIT = 80

    # --- PEPPER: regime detection ---
    PEPPER_WARMUP_TICKS = 1500
    PEPPER_REEVAL_INTERVAL = 5000
    PEPPER_SMOOTH_N = 30

    PEPPER_SLOPE_STRONG = 0.06
    PEPPER_SLOPE_MODERATE = 0.02
    PEPPER_SLOPE_WEAK = -0.02

    PEPPER_CAP_STRONG = 80
    PEPPER_CAP_MODERATE = 60
    PEPPER_CAP_WEAK = 30
    PEPPER_CAP_NEGATIVE = 0
    PEPPER_CAP_TENTATIVE = 20

    PEPPER_ADD_PER_TICK = 10
    PEPPER_ADD_PER_TICK_TENTATIVE = 5

    # --- PEPPER: magnitude stop guard ---
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

    def _pick_pepper_cap(self, slope: float) -> int:
        if slope > self.PEPPER_SLOPE_STRONG:
            return self.PEPPER_CAP_STRONG
        if slope > self.PEPPER_SLOPE_MODERATE:
            return self.PEPPER_CAP_MODERATE
        if slope > self.PEPPER_SLOPE_WEAK:
            return self.PEPPER_CAP_WEAK
        return self.PEPPER_CAP_NEGATIVE

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
        ts = state.timestamp

        hist = self.history.get("pp", [])
        hist.append(mid)
        if len(hist) > 80:
            hist = hist[-80:]
        self.history["pp"] = hist

        start_samples = self.history.get("pp_start_samples", [])
        if len(start_samples) < self.PEPPER_SMOOTH_N:
            start_samples.append(mid)
            self.history["pp_start_samples"] = start_samples

        if "pp_start_ts" not in self.history:
            self.history["pp_start_ts"] = ts

        start_ts = self.history.get("pp_start_ts", ts)
        cap = self.history.get("pp_cap", None)
        last_eval_ts = self.history.get("pp_last_eval_ts", None)

        warmed_up = (ts - start_ts) >= self.PEPPER_WARMUP_TICKS

        if warmed_up and len(start_samples) >= self.PEPPER_SMOOTH_N:
            smoothed_start = _median(start_samples)
            smoothed_now = _median(hist[-self.PEPPER_SMOOTH_N:])
            elapsed = max(1, ts - start_ts)
            slope = (smoothed_now - smoothed_start) / elapsed * 100.0

            if cap is None:
                cap = self._pick_pepper_cap(slope)
                last_eval_ts = ts
                self.history["pp_cap"] = cap
                self.history["pp_last_eval_ts"] = last_eval_ts
                self.history["pp_measured_slope"] = slope
            elif (
                last_eval_ts is not None
                and (ts - last_eval_ts) >= self.PEPPER_REEVAL_INTERVAL
            ):
                fresh = self._pick_pepper_cap(slope)
                if fresh > cap:
                    cap = fresh
                    self.history["pp_cap"] = cap
                    self.history["pp_measured_slope"] = slope
                last_eval_ts = ts
                self.history["pp_last_eval_ts"] = last_eval_ts

        confirmed = cap is not None
        effective_cap = cap if confirmed else self.PEPPER_CAP_TENTATIVE
        add_per_tick = (
            self.PEPPER_ADD_PER_TICK if confirmed else self.PEPPER_ADD_PER_TICK_TENTATIVE
        )

        stop_breach = int(self.history.get("pp_breach", 0))
        drift_stopped = bool(self.history.get("pp_stopped", False))

        if len(hist) >= self.PEPPER_SLOPE_WINDOW:
            window = hist[-self.PEPPER_SLOPE_WINDOW:]
            slope_w = window[-1] - window[0]
            if slope_w < self.PEPPER_STOP_THRESHOLD:
                stop_breach += 1
            else:
                stop_breach = 0
            if stop_breach >= self.PEPPER_STOP_HYSTERESIS:
                drift_stopped = True
            elif drift_stopped and slope_w > self.PEPPER_RESUME_THRESHOLD:
                drift_stopped = False

        self.history["pp_breach"] = stop_breach
        self.history["pp_stopped"] = drift_stopped

        orders: List[Order] = []

        if drift_stopped or effective_cap == 0:
            if pos > 0:
                avail = depth.buy_orders.get(bb, 0)
                qty = min(pos, avail, self.PEPPER_FLATTEN_CHUNK)
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        rem_cap = effective_cap - pos
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
