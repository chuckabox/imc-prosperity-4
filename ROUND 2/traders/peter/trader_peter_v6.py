"""
trader_peter_v6.py (Round 2 — Safe Play + Refined Alpha)
========================================================
Baseline: trader_peter_v5.py

Design goals for v6
-------------------
* NO MAF bid. We opt out of extra market access (`bid()` returns 0) to
  guarantee zero fee drag on realized PnL — playing it safe.
* Reinforced pepper spread-momentum alpha (per pepper_analysis.png /
  analyze_spread.py): increasing spread precedes a downward drift, so
  we halt buys AND actively lean short into the bid while spread widens.
* Proper least-squares slope over a 100-tick window (matches the
  analysis script) for cleaner trend detection on pepper.
* Full-book VWAP mid for Osmium using up to 3 levels on each side.
* Gap handling: backfill mid/VWAP from history when book is one-sided
  or empty; skip trading rather than guessing a price when nothing
  sensible is known.
* Strict guards against the Round 2 post-mortem mistakes:
    - All order sizes are clamped positive via max(0, ...).
    - MM quotes always satisfy bid_price < ask_price.
    - Remaining capacity is recomputed after every fill intent.
    - Directional signs verified (buy = +, sell = -).
    - No crossing of own bid/ask in MM quoting.
"""

import json
from typing import Dict, List, Optional

from datamodel import Order, OrderDepth, TradingState


def _median(vals: list) -> float:
    n = len(vals)
    if n == 0:
        return 0.0
    s = sorted(vals)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def _ls_slope(vals: list) -> float:
    """Least-squares slope over integer x=0..n-1. Matches analyze_spread.fast_slope."""
    n = len(vals)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(vals) / n
    num = 0.0
    den = 0.0
    for i, y in enumerate(vals):
        dx = i - x_mean
        num += dx * (y - y_mean)
        den += dx * dx
    if den == 0.0:
        return 0.0
    return num / den


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

    # Spread-momentum alpha sizing. Rising spread => expected -15.8 drift.
    PEPPER_SPREAD_SELL_WHEN_LONG = 25
    PEPPER_SPREAD_SHORT_LEAN = 12   # lean short even when flat on strong widening
    PEPPER_SPREAD_WIDE_ABS = 15     # "wide" spread threshold from analysis avg ~14

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

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def _load_state(self, state: TradingState):
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        else:
            self.history = self.history or {}
        if "pp_hist" not in self.history:
            self.history["pp_hist"] = []
        if "op_hist" not in self.history:
            self.history["op_hist"] = []
        if "pp_spread_hist" not in self.history:
            self.history["pp_spread_hist"] = []

    def _save_state(self) -> str:
        return json.dumps(self.history)

    # ------------------------------------------------------------------
    # MAF bid — explicit opt-out. Safe play.
    # ------------------------------------------------------------------
    def bid(self) -> int:
        return 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _vwap_mid_full(self, depth: OrderDepth) -> Optional[float]:
        """VWAP mid using up to 3 best levels each side. None if one side empty."""
        if not depth.buy_orders or not depth.sell_orders:
            return None
        bids = sorted(depth.buy_orders.items(), reverse=True)[:3]
        asks = sorted(depth.sell_orders.items())[:3]
        b_px = sum(p * v for p, v in bids)
        b_vol = sum(v for _, v in bids)
        a_px = sum(p * (-v) for p, v in asks)
        a_vol = sum(-v for _, v in asks)
        if b_vol <= 0 or a_vol <= 0:
            return None
        # Cross-weight: weight each side's price by the OPPOSITE side's volume.
        # That pulls the mid toward the heavier side's price (pressure).
        num = (b_px / b_vol) * a_vol + (a_px / a_vol) * b_vol
        den = b_vol + a_vol
        return num / den

    def _pick_pepper_cap(self, slope: float) -> int:
        if slope > self.PEPPER_SLOPE_STRONG:
            return self.PEPPER_CAP_STRONG
        if slope > self.PEPPER_SLOPE_MODERATE:
            return self.PEPPER_CAP_MODERATE
        if slope > self.PEPPER_SLOPE_WEAK:
            return self.PEPPER_CAP_WEAK
        return self.PEPPER_CAP_NEGATIVE

    def _stop_params(self, cap: int):
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
        pos = int(state.position.get(product, 0))

        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None

        # Gap handling: need both sides to act safely.
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        spread = ba - bb
        ts = state.timestamp

        hist: List[float] = self.history["pp_hist"]
        hist.append(mid)
        if len(hist) > 200:
            hist = hist[-200:]
        self.history["pp_hist"] = hist

        sp_hist: List[float] = self.history["pp_spread_hist"]
        sp_hist.append(spread)
        if len(sp_hist) > 30:
            sp_hist = sp_hist[-30:]
        self.history["pp_spread_hist"] = sp_hist

        # Smoothed spread delta (reduce single-tick noise).
        prev_spread = self.history.get("pp_prev_spread", spread)
        self.history["pp_prev_spread"] = spread
        spread_delta = spread - prev_spread
        recent_sp_avg = sum(sp_hist[-5:]) / max(1, len(sp_hist[-5:]))
        spread_wide = recent_sp_avg >= self.PEPPER_SPREAD_WIDE_ABS
        spread_increasing = spread_delta > 0 or spread_wide

        # Trend: proper LS slope over last window.
        if "pp_start_ts" not in self.history:
            self.history["pp_start_ts"] = ts
        warmed_up = (ts - self.history["pp_start_ts"]) >= self.PEPPER_WARMUP_TICKS

        cap = self.history.get("pp_cap", None)
        if len(hist) >= 50:
            window = hist[-self.PEPPER_SLOPE_WINDOW:] if len(hist) >= self.PEPPER_SLOPE_WINDOW else hist[:]
            slope = _ls_slope(window)
            if warmed_up or cap is None:
                new_cap = self._pick_pepper_cap(slope)
                if cap is None or new_cap > cap:
                    cap = new_cap
                    self.history["pp_cap"] = cap

        effective_cap = cap if cap is not None else self.PEPPER_CAP_TENTATIVE

        # Stop guard
        stop_th, resume_th = self._stop_params(effective_cap)
        drift_stopped = self.history.get("pp_stopped", False)
        if len(hist) >= 20:
            local_slope = hist[-1] - hist[-20]
            if local_slope < stop_th:
                drift_stopped = True
            elif drift_stopped and local_slope > resume_th:
                drift_stopped = False
        self.history["pp_stopped"] = drift_stopped

        orders: List[Order] = []

        # --- Defensive dump path ---
        if drift_stopped or effective_cap == 0:
            if pos > 0:
                qty = max(0, min(pos, depth.buy_orders.get(bb, 0)))
                # If best-bid volume is thin, still post at best bid for full pos.
                qty_to_sell = max(0, pos)
                if qty_to_sell > 0:
                    orders.append(Order(product, bb, -qty_to_sell))
            return orders

        # --- Spread-widening alpha: bias short ---
        if spread_increasing:
            if pos > 0:
                sell_qty = max(0, min(pos, self.PEPPER_SPREAD_SELL_WHEN_LONG))
                if sell_qty > 0:
                    orders.append(Order(product, bb, -sell_qty))
            else:
                # Flat / short: lean further short at the ask-1 (passive short).
                room_short = self.LIMIT + pos  # how much more short we can add
                short_qty = max(0, min(room_short, self.PEPPER_SPREAD_SHORT_LEAN))
                if short_qty > 0:
                    orders.append(Order(product, ba - 1, -short_qty))
            # Suppress buys this tick when spread is widening.
            return orders

        # --- Normal buy path ---
        rem_cap = max(0, effective_cap - pos)
        if rem_cap > 0:
            take_budget = min(
                rem_cap,
                self.PEPPER_TAKE_PER_TICK_STRONG if cap == self.PEPPER_CAP_STRONG
                else self.PEPPER_TAKE_PER_TICK,
            )
            for ask in sorted(depth.sell_orders.keys()):
                if take_budget <= 0 or rem_cap <= 0:
                    break
                if ask <= mid + 1:
                    avail = -depth.sell_orders[ask]
                    qty = max(0, min(take_budget, avail, rem_cap))
                    if qty > 0:
                        orders.append(Order(product, ask, qty))
                        take_budget -= qty
                        rem_cap -= qty

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
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos = int(state.position.get(product, 0))

        vwap = self._vwap_mid_full(depth)
        if vwap is None:
            # Gap: backfill from last known VWAP. If none, skip — safer than guessing.
            fair = self.history.get("op_last_vwap")
            if fair is None:
                return []
        else:
            self.history["op_last_vwap"] = vwap
            fair = vwap

        hist: List[float] = self.history["op_hist"]
        hist.append(fair)
        if len(hist) > 50:
            hist = hist[-50:]
        self.history["op_hist"] = hist

        avg_vwap = sum(hist) / len(hist)
        fair = 0.7 * fair + 0.3 * avg_vwap

        orders: List[Order] = []
        rem_buy = max(0, self.LIMIT - pos)
        rem_sell = max(0, self.LIMIT + pos)

        # Position-aware take edges.
        buy_edge = self.OSMIUM_TAKE_EDGE + max(0, pos // self.OSMIUM_EDGE_POS_STEP)
        sell_edge = self.OSMIUM_TAKE_EDGE + max(0, (-pos) // self.OSMIUM_EDGE_POS_STEP)

        # Mean-reversion takes
        if depth.sell_orders and rem_buy > 0:
            for ask in sorted(depth.sell_orders.keys()):
                if rem_buy <= 0:
                    break
                if ask <= fair - buy_edge:
                    avail = -depth.sell_orders[ask]
                    qty = max(0, min(rem_buy, avail))
                    if qty > 0:
                        orders.append(Order(product, ask, qty))
                        rem_buy -= qty
                        pos += qty

        if depth.buy_orders and rem_sell > 0:
            for bid_px in sorted(depth.buy_orders.keys(), reverse=True):
                if rem_sell <= 0:
                    break
                if bid_px >= fair + sell_edge:
                    avail = depth.buy_orders[bid_px]
                    qty = max(0, min(rem_sell, avail))
                    if qty > 0:
                        orders.append(Order(product, bid_px, -qty))
                        rem_sell -= qty
                        pos -= qty

        # --- Inventory flatten at hard skew ---
        if pos > self.OSMIUM_FLATTEN and depth.buy_orders:
            best_bid = max(depth.buy_orders.keys())
            flatten_qty = max(0, min(pos - self.OSMIUM_SKEW_SOFT, rem_sell))
            if flatten_qty > 0:
                orders.append(Order(product, best_bid, -flatten_qty))
                rem_sell -= flatten_qty
                pos -= flatten_qty
        elif pos < -self.OSMIUM_FLATTEN and depth.sell_orders:
            best_ask = min(depth.sell_orders.keys())
            flatten_qty = max(0, min((-pos) - self.OSMIUM_SKEW_SOFT, rem_buy))
            if flatten_qty > 0:
                orders.append(Order(product, best_ask, flatten_qty))
                rem_buy -= flatten_qty
                pos += flatten_qty

        # --- MM quotes around denoised fair ---
        bid_price = int(fair) - 1
        ask_price = int(fair) + 1

        if pos > self.OSMIUM_SKEW_SOFT:
            bid_price -= 1
        if pos > self.OSMIUM_SKEW_HARD:
            bid_price -= 1
        if pos < -self.OSMIUM_SKEW_SOFT:
            ask_price += 1
        if pos < -self.OSMIUM_SKEW_HARD:
            ask_price += 1

        # Never cross our own quotes.
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # Never quote into the book in a way that crosses the real opposite side.
        if depth.sell_orders:
            best_ask = min(depth.sell_orders.keys())
            if bid_price >= best_ask:
                bid_price = best_ask - 1
        if depth.buy_orders:
            best_bid = max(depth.buy_orders.keys())
            if ask_price <= best_bid:
                ask_price = best_bid + 1

        if rem_buy > 0 and bid_price > 0:
            q = max(0, min(rem_buy, self.OSMIUM_QUOTE_SIZE))
            if q > 0:
                orders.append(Order(product, bid_price, q))
        if rem_sell > 0 and ask_price > 0:
            q = max(0, min(rem_sell, self.OSMIUM_QUOTE_SIZE))
            if q > 0:
                orders.append(Order(product, ask_price, -q))

        return orders

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        try:
            pep = self._pepper_logic(state)
            if pep:
                result["INTARIAN_PEPPER_ROOT"] = pep
        except Exception:
            # Fail-safe: never crash the round over one product.
            pass

        try:
            osm = self._osmium_logic(state)
            if osm:
                result["ASH_COATED_OSMIUM"] = osm
        except Exception:
            pass

        return result, 0, self._save_state()
