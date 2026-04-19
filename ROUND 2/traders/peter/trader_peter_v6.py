"""
trader_peter_v6.py (Round 2 — Spread Alpha)
============================================
Key changes from v5:
- bid() = 0 (no MAF bid)
- Pepper Root: sqrt(spread) momentum as primary alpha signal
  When sqrt(spread) rising → price reverting down → sell entire long position
- Stronger sell response: unwind full position (not just 20) on spread expansion
- max(0, qty) guards everywhere (lesson: negative volumes cause self-crossing)
- Osmium unchanged from v5
"""

import json
import math
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

    # --- PEPPER constants ---
    PEPPER_WARMUP_TICKS = 1500
    PEPPER_SLOPE_WINDOW = 100
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
    PEPPER_PASSIVE_CAP = 40

    PEPPER_STOP_STRONG = -16
    PEPPER_STOP_MODERATE = -12
    PEPPER_STOP_WEAK = -8
    PEPPER_RESUME_STRONG = 7
    PEPPER_RESUME_MODERATE = 5
    PEPPER_RESUME_WEAK = 4

    # Spread momentum: number of ticks to track sqrt(spread) history
    SPREAD_HIST_LEN = 10
    # If avg sqrt(spread) over recent window > baseline by this threshold → expanding
    SPREAD_SQRT_THRESHOLD = 0.15

    # --- OSMIUM constants ---
    OSMIUM_ANCHOR = 10_000
    OSMIUM_TAKE_EDGE = 1
    OSMIUM_EDGE_POS_STEP = 30
    OSMIUM_QUOTE_SIZE = 25
    OSMIUM_SKEW_SOFT = 22
    OSMIUM_SKEW_HARD = 45
    OSMIUM_FLATTEN = 55

    def __init__(self):
        self.history: Dict[str, any] = {}

    def bid(self):
        return 0  # Not bidding for MAF

    def _load_state(self, state: TradingState):
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        if "pp_hist" not in self.history: self.history["pp_hist"] = []
        if "op_hist" not in self.history: self.history["op_hist"] = []
        if "pp_spread_sqrt_hist" not in self.history: self.history["pp_spread_sqrt_hist"] = []

    def _save_state(self):
        return json.dumps(self.history)

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
        if product not in state.order_depths: return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)

        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None: return []

        mid = (bb + ba) / 2.0
        spread = ba - bb
        ts = state.timestamp

        # --- Mid price history ---
        hist = self.history["pp_hist"]
        hist.append(mid)
        if len(hist) > 200: hist = hist[-200:]
        self.history["pp_hist"] = hist

        # --- sqrt(spread) momentum alpha ---
        # sqrt normalizes large spread jumps; rising sqrt(spread) = widening = downward pressure
        sqrt_spread = math.sqrt(max(spread, 1))
        spread_sqrt_hist = self.history["pp_spread_sqrt_hist"]
        spread_sqrt_hist.append(sqrt_spread)
        if len(spread_sqrt_hist) > self.SPREAD_HIST_LEN * 2:
            spread_sqrt_hist = spread_sqrt_hist[-(self.SPREAD_HIST_LEN * 2):]
        self.history["pp_spread_sqrt_hist"] = spread_sqrt_hist

        spread_expanding = False
        if len(spread_sqrt_hist) >= self.SPREAD_HIST_LEN + 1:
            recent_avg = sum(spread_sqrt_hist[-self.SPREAD_HIST_LEN:]) / self.SPREAD_HIST_LEN
            baseline_avg = sum(spread_sqrt_hist[-self.SPREAD_HIST_LEN * 2:-self.SPREAD_HIST_LEN]) / self.SPREAD_HIST_LEN
            spread_expanding = recent_avg > baseline_avg + self.SPREAD_SQRT_THRESHOLD
        else:
            # Fallback: single-tick comparison
            if len(spread_sqrt_hist) >= 2:
                spread_expanding = spread_sqrt_hist[-1] > spread_sqrt_hist[-2] + self.SPREAD_SQRT_THRESHOLD

        # --- Trend slope ---
        start_ts = self.history.get("pp_start_ts", ts)
        if "pp_start_ts" not in self.history: self.history["pp_start_ts"] = ts
        warmed_up = (ts - start_ts) >= self.PEPPER_WARMUP_TICKS
        cap = self.history.get("pp_cap", None)

        if len(hist) >= 50:
            s_now = _median(hist[-15:])
            s_start = _median(hist[:15]) if len(hist) < 100 else _median(hist[-100:-85])
            dt = 15 if len(hist) < 100 else 85
            slope = (s_now - s_start) / dt * 10.0

            if warmed_up or cap is None:
                new_cap = self._pick_pepper_cap(slope)
                if cap is None or new_cap > cap:
                    cap = new_cap
                    self.history["pp_cap"] = cap

        effective_cap = cap if cap is not None else self.PEPPER_CAP_TENTATIVE

        # --- Stop guard ---
        stop_th, resume_th = self._stop_params(effective_cap)
        drift_stopped = self.history.get("pp_stopped", False)
        if len(hist) >= 20:
            local_slope = hist[-1] - hist[-20]
            if local_slope < stop_th: drift_stopped = True
            elif drift_stopped and local_slope > resume_th: drift_stopped = False
        self.history["pp_stopped"] = drift_stopped

        orders: List[Order] = []

        # --- Spread expanding: liquidate entire long position aggressively ---
        if spread_expanding and pos > 0:
            # Sell all into bid (guaranteed fill, de-risk now)
            sell_qty = max(0, pos)
            if sell_qty > 0:
                orders.append(Order(product, bb, -sell_qty))
            return orders

        # --- Stopped or no-go regime ---
        if drift_stopped or effective_cap == 0:
            if pos > 0:
                orders.append(Order(product, bb, -pos))
            return orders

        # --- Normal buy logic (only when spread NOT expanding) ---
        rem_cap = max(0, effective_cap - pos)
        if rem_cap > 0:
            take_budget = min(rem_cap, self.PEPPER_TAKE_PER_TICK_STRONG if cap == self.PEPPER_CAP_STRONG else self.PEPPER_TAKE_PER_TICK)
            for ask in sorted(depth.sell_orders.keys()):
                if take_budget <= 0: break
                if ask <= mid + 1:
                    qty = max(0, min(take_budget, -depth.sell_orders[ask]))
                    if qty > 0:
                        orders.append(Order(product, ask, qty))
                        take_budget -= qty
                        rem_cap -= qty

            rem_cap = max(0, rem_cap)
            if rem_cap > 0:
                passive_qty = max(0, min(rem_cap, self.PEPPER_PASSIVE_CAP))
                if passive_qty > 0:
                    orders.append(Order(product, bb + 1, passive_qty))

        return orders

    # ------------------------------------------------------------------
    # OSMIUM
    # ------------------------------------------------------------------
    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths: return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)

        b1 = max(depth.buy_orders.keys()) if depth.buy_orders else None
        a1 = min(depth.sell_orders.keys()) if depth.sell_orders else None

        if b1 is None or a1 is None:
            fair = self.history.get("op_last_vwap", self.OSMIUM_ANCHOR)
        else:
            bv1 = depth.buy_orders[b1]
            av1 = -depth.sell_orders[a1]
            vwap_mid = (b1 * av1 + a1 * bv1) / (bv1 + av1)
            self.history["op_last_vwap"] = vwap_mid
            fair = vwap_mid

        hist = self.history["op_hist"]
        hist.append(fair)
        if len(hist) > 50: hist = hist[-50:]
        self.history["op_hist"] = hist

        avg_vwap = sum(hist) / len(hist)
        fair = 0.7 * fair + 0.3 * avg_vwap

        orders: List[Order] = []
        rem_buy = max(0, self.LIMIT - pos)
        rem_sell = max(0, self.LIMIT + pos)

        buy_edge = self.OSMIUM_TAKE_EDGE + max(0, pos // self.OSMIUM_EDGE_POS_STEP)
        sell_edge = self.OSMIUM_TAKE_EDGE + max(0, (-pos) // self.OSMIUM_EDGE_POS_STEP)

        if depth.sell_orders:
            for ask in sorted(depth.sell_orders.keys()):
                if ask <= fair - buy_edge and rem_buy > 0:
                    qty = max(0, min(rem_buy, -depth.sell_orders[ask]))
                    if qty > 0:
                        orders.append(Order(product, ask, qty))
                        rem_buy -= qty
                        pos += qty

        if depth.buy_orders:
            for bid_p in sorted(depth.buy_orders.keys(), reverse=True):
                if bid_p >= fair + sell_edge and rem_sell > 0:
                    qty = max(0, min(rem_sell, depth.buy_orders[bid_p]))
                    if qty > 0:
                        orders.append(Order(product, bid_p, -qty))
                        rem_sell -= qty
                        pos -= qty

        bid_price = int(fair - 1)
        ask_price = int(fair + 1)

        if pos > self.OSMIUM_SKEW_SOFT: bid_price -= 1
        if pos < -self.OSMIUM_SKEW_SOFT: ask_price += 1

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        rem_buy = max(0, self.LIMIT - pos)
        rem_sell = max(0, self.LIMIT + pos)

        if rem_buy > 0:
            orders.append(Order(product, bid_price, min(rem_buy, self.OSMIUM_QUOTE_SIZE)))
        if rem_sell > 0:
            orders.append(Order(product, ask_price, -min(rem_sell, self.OSMIUM_QUOTE_SIZE)))

        return orders

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        pep = self._pepper_logic(state)
        if pep: result["INTARIAN_PEPPER_ROOT"] = pep

        osm = self._osmium_logic(state)
        if osm: result["ASH_COATED_OSMIUM"] = osm

        return result, 0, self._save_state()
