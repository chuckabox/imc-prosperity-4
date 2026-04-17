"""
trader_robust_peter_v13.py
==========================
V13 — v12 evolved. Five regime-aware upgrades: same "Aggressive by Default,
Safe by Exception" thesis, just more aware of *what* regime it's in at each
decision point.

Pepper
------
1. ADAPTIVE STOP THRESHOLD by regime. v12 used a flat -12 slope. A -12
   pullback in a STRONG drift is normal noise (whipsaw risk); in WEAK
   it is a real reversal. Now:
       STRONG  -> -16  (resume +7)
       MODERATE/TENTATIVE -> -12  (resume +5)
       WEAK    ->  -8  (resume +4)
   Protects STRONG-regime PnL from noise-trips, tightens WEAK exposure.

2. FAST-TRACK also promotes MODERATE. v12 only fast-tracked STRONG
   (slope >= 0.10). Now a slope between MODERATE and STRONG-fast at the
   fast-track check commits CAP_MODERATE early. Moderate-drift days
   no longer burn the first ~1500 ts at tentative cap 20.

3. INSIDE-SPREAD PASSIVE in STRONG. v12 rested the passive bid entirely
   at `bb+1`. In STRONG regime with spread >= 3, now split 50/50 between
   `bb+1` (safe) and `ba-1` (aggressive pennying). We're confident price
   rises, so pay 1 tick more for double the fill surface.

4. FIRST-TICK FLATTEN bumped 30 -> 40. On the tick the stop fires we
   want max damage-control; 40 clears half the book-depth on most days.

Osmium
------
5. POSITION-ASYMMETRIC TAKE-EDGE. v12 used the same edge for buys and
   sells. Now:
       buy_edge  = base_edge + max(0, pos // 30)
       sell_edge = base_edge + max(0, -pos // 30)
   At pos=+30 we need a 2-tick edge to buy but still only 1 to sell.
   At pos=+60, 3-tick buy edge. Composes with skew and flatten for
   coherent multi-layer unwind pressure.
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
    PEPPER_FASTTRACK_TICKS = 700
    PEPPER_FASTTRACK_SAMPLES = 10
    PEPPER_FASTTRACK_STRONG_SLOPE = 0.10
    PEPPER_FASTTRACK_MODERATE_SLOPE = 0.04
    PEPPER_REEVAL_INTERVAL = 5000
    PEPPER_SMOOTH_N = 15

    PEPPER_SLOPE_STRONG = 0.06
    PEPPER_SLOPE_MODERATE = 0.02
    PEPPER_SLOPE_WEAK = -0.02

    PEPPER_CAP_STRONG = 80
    PEPPER_CAP_MODERATE = 60
    PEPPER_CAP_WEAK = 30
    PEPPER_CAP_NEGATIVE = 0
    PEPPER_CAP_TENTATIVE = 20

    PEPPER_TAKE_PER_TICK = 10
    PEPPER_TAKE_PER_TICK_STRONG = 15
    PEPPER_TAKE_PER_TICK_TENTATIVE = 5
    PEPPER_PASSIVE_CAP = 40

    # --- PEPPER: magnitude stop guard (regime-adaptive) ---
    PEPPER_SLOPE_WINDOW = 20
    PEPPER_STOP_STRONG = -16
    PEPPER_STOP_MODERATE = -12
    PEPPER_STOP_WEAK = -8
    PEPPER_RESUME_STRONG = 7
    PEPPER_RESUME_MODERATE = 5
    PEPPER_RESUME_WEAK = 4
    PEPPER_STOP_HYSTERESIS = 2

    PEPPER_FLATTEN_CHUNK = 15
    PEPPER_FLATTEN_FIRST = 40

    # --- OSMIUM ---
    OSMIUM_ANCHOR = 10_000
    OSMIUM_TAKE_EDGE = 1
    OSMIUM_TAKE_EDGE_UNSAFE = 2
    OSMIUM_EDGE_POS_STEP = 30
    OSMIUM_QUOTE_SIZE = 25
    OSMIUM_SECOND_SIZE = 18
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

    def _stop_params(self, cap):
        if cap == self.PEPPER_CAP_STRONG:
            return self.PEPPER_STOP_STRONG, self.PEPPER_RESUME_STRONG
        if cap == self.PEPPER_CAP_WEAK:
            return self.PEPPER_STOP_WEAK, self.PEPPER_RESUME_WEAK
        return self.PEPPER_STOP_MODERATE, self.PEPPER_RESUME_MODERATE

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
        spread = ba - bb
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

        # Fast-track: commit early if slope is clearly strong or moderate.
        if (
            cap is None
            and (ts - start_ts) >= self.PEPPER_FASTTRACK_TICKS
            and len(start_samples) >= self.PEPPER_FASTTRACK_SAMPLES
        ):
            sm_start = _median(start_samples)
            sm_now = _median(hist[-min(len(hist), self.PEPPER_FASTTRACK_SAMPLES):])
            elapsed = max(1, ts - start_ts)
            slope_early = (sm_now - sm_start) / elapsed * 100.0
            picked = None
            if slope_early >= self.PEPPER_FASTTRACK_STRONG_SLOPE:
                picked = self.PEPPER_CAP_STRONG
            elif slope_early >= self.PEPPER_FASTTRACK_MODERATE_SLOPE:
                picked = self.PEPPER_CAP_MODERATE
            if picked is not None:
                cap = picked
                last_eval_ts = ts
                self.history["pp_cap"] = cap
                self.history["pp_last_eval_ts"] = last_eval_ts
                self.history["pp_measured_slope"] = slope_early

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

        if not confirmed:
            take_per_tick = self.PEPPER_TAKE_PER_TICK_TENTATIVE
        elif cap == self.PEPPER_CAP_STRONG:
            take_per_tick = self.PEPPER_TAKE_PER_TICK_STRONG
        else:
            take_per_tick = self.PEPPER_TAKE_PER_TICK

        stop_th, resume_th = self._stop_params(cap)
        stop_breach = int(self.history.get("pp_breach", 0))
        drift_stopped = bool(self.history.get("pp_stopped", False))
        was_stopped = drift_stopped

        if len(hist) >= self.PEPPER_SLOPE_WINDOW:
            window = hist[-self.PEPPER_SLOPE_WINDOW:]
            slope_w = window[-1] - window[0]
            if slope_w < stop_th:
                stop_breach += 1
            else:
                stop_breach = 0
            if stop_breach >= self.PEPPER_STOP_HYSTERESIS:
                drift_stopped = True
            elif drift_stopped and slope_w > resume_th:
                drift_stopped = False

        self.history["pp_breach"] = stop_breach
        self.history["pp_stopped"] = drift_stopped

        orders: List[Order] = []

        if drift_stopped or effective_cap == 0:
            if pos > 0:
                just_triggered = drift_stopped and not was_stopped
                chunk = (
                    self.PEPPER_FLATTEN_FIRST if just_triggered else self.PEPPER_FLATTEN_CHUNK
                )
                avail = depth.buy_orders.get(bb, 0)
                qty = min(pos, avail, chunk)
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        rem_cap = effective_cap - pos
        if rem_cap <= 0:
            return orders

        take_budget = min(rem_cap, take_per_tick)
        taken = 0

        for ask in sorted(depth.sell_orders.keys()):
            if take_budget <= 0:
                break
            avail = -depth.sell_orders[ask]
            if avail <= 0:
                continue
            if ask <= mid + 1:
                qty = min(take_budget, avail)
                orders.append(Order(product, ask, qty))
                take_budget -= qty
                taken += qty

        rem_cap -= taken
        if rem_cap > 0:
            passive_qty = min(rem_cap, self.PEPPER_PASSIVE_CAP)
            if effective_cap == self.PEPPER_CAP_STRONG and spread >= 3:
                half = passive_qty // 2
                other = passive_qty - half
                if half > 0:
                    orders.append(Order(product, bb + 1, half))
                if other > 0:
                    orders.append(Order(product, ba - 1, other))
            else:
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

        base_edge = (
            self.OSMIUM_TAKE_EDGE_UNSAFE if anchor_off else self.OSMIUM_TAKE_EDGE
        )
        buy_edge = base_edge + max(0, pos // self.OSMIUM_EDGE_POS_STEP)
        sell_edge = base_edge + max(0, (-pos) // self.OSMIUM_EDGE_POS_STEP)

        buy_vol = 0
        sell_vol = 0
        if product in state.market_trades:
            for t in state.market_trades[product]:
                if t.price >= mid:
                    buy_vol += abs(t.quantity)
                else:
                    sell_vol += abs(t.quantity)

        diff = buy_vol - sell_vol
        toxic_skip_buys = diff >= self.OSMIUM_TOXIC_VOLUME
        toxic_skip_sells = -diff >= self.OSMIUM_TOXIC_VOLUME

        orders: List[Order] = []
        rem_buy = self.LIMIT - pos
        rem_sell = self.LIMIT + pos

        if not toxic_skip_buys:
            for ask in sorted(depth.sell_orders.keys()):
                if ask <= fair - buy_edge and rem_buy > 0:
                    avail = -depth.sell_orders[ask]
                    qty = min(rem_buy, avail)
                    if qty > 0:
                        orders.append(Order(product, ask, qty))
                        rem_buy -= qty
                        pos += qty

        if not toxic_skip_sells:
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid >= fair + sell_edge and rem_sell > 0:
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
