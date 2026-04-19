"""
trader_peter_v5.py (Round 2 Alpha Upgrade)
=========================================
V5 — Integrated analytical insights for Pepper Root and Osmium.

Pepper Root
-----------
1. SPREAD MOMENTUM: If spread is increasing (current > prev), it signals an imminent downward break
   (avg move -15.8). We now halt aggressive buys and favor selling when spread widens.
2. ROBUST TREND: Uses 100-timestep window for cleaner linear slope detection.
3. ADAPTIVE REGIME: Maintains v2 stop/resume logic but adds spread-delta gating.

Osmium
------
4. VWAP DENOISING: Uses Volume-Weighted Mid Price across level 1 as a lead signal (0.7 correlation).
5. LEAD FAIR: Fair value is derived from VWAP_Mid, not just a static anchor.
6. GAP HANDLING: Robust forward-filling for empty book states.
"""

import json
from typing import Dict, List
import collections

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
    PEPPER_SLOPE_WINDOW = 100  # Increased for stability
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
    PEPPER_STOP_HYSTERESIS = 2

    # --- OSMIUM constants ---
    OSMIUM_ANCHOR = 10_000
    OSMIUM_TAKE_EDGE = 1
    OSMIUM_EDGE_POS_STEP = 30
    OSMIUM_QUOTE_SIZE = 25
    OSMIUM_SKEW_SOFT = 22
    OSMIUM_SKEW_HARD = 45
    OSMIUM_FLATTEN = 55
    OSMIUM_CLAMP = 5  # Allow spread capture within 5 ticks of fair

    def __init__(self):
        self.history: Dict[str, any] = {}

    def _load_state(self, state: TradingState):
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        # Ensure collections are initialized
        if "pp_hist" not in self.history: self.history["pp_hist"] = []
        if "op_hist" not in self.history: self.history["op_hist"] = []

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

    def bid(self):
        return 50 # Market access fee

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

        # Track history
        hist = self.history["pp_hist"]
        hist.append(mid)
        if len(hist) > 200: hist = hist[-200:]
        self.history["pp_hist"] = hist

        # Spread Momentum Alpha
        prev_spread = self.history.get("pp_prev_spread", spread)
        spread_increasing = spread > prev_spread
        self.history["pp_prev_spread"] = spread

        # Trend detection (Rolling linear regression proxy)
        start_ts = self.history.get("pp_start_ts", ts)
        if "pp_start_ts" not in self.history: self.history["pp_start_ts"] = ts
        
        warmed_up = (ts - start_ts) >= self.PEPPER_WARMUP_TICKS
        cap = self.history.get("pp_cap", None)
        
        if len(hist) >= 50: # Minimum for reasonably stable slope
            s_now = _median(hist[-15:])
            s_start = _median(hist[:15]) if len(hist) < 100 else _median(hist[-100:-85])
            dt = 15 if len(hist) < 100 else 85
            slope = (s_now - s_start) / dt * 10.0 # Normalized
            
            if warmed_up or cap is None:
                new_cap = self._pick_pepper_cap(slope)
                if cap is None or new_cap > cap: # Aggressive upgrade
                    cap = new_cap
                    self.history["pp_cap"] = cap

        effective_cap = cap if cap is not None else self.PEPPER_CAP_TENTATIVE
        
        # STOP Guard
        stop_th, resume_th = self._stop_params(effective_cap)
        drift_stopped = self.history.get("pp_stopped", False)
        if len(hist) >= 20:
            local_slope = hist[-1] - hist[-20]
            if local_slope < stop_th: drift_stopped = True
            elif drift_stopped and local_slope > resume_th: drift_stopped = False
        self.history["pp_stopped"] = drift_stopped

        orders: List[Order] = []
        
        # Action logic
        if drift_stopped or effective_cap == 0:
            if pos > 0:
                # Dump inventory into the bid
                orders.append(Order(product, bb, -pos))
            return orders

        # Buy logic (Gated by Spread Momentum)
        rem_cap = effective_cap - pos
        if rem_cap > 0 and not spread_increasing:
            take_budget = min(rem_cap, self.PEPPER_TAKE_PER_TICK_STRONG if cap == self.PEPPER_CAP_STRONG else self.PEPPER_TAKE_PER_TICK)
            for ask in sorted(depth.sell_orders.keys()):
                if take_budget <= 0: break
                if ask <= mid + 1:
                    qty = min(take_budget, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, qty))
                    take_budget -= qty
                    rem_cap -= qty
            
            if rem_cap > 0:
                orders.append(Order(product, bb + 1, min(rem_cap, self.PEPPER_PASSIVE_CAP)))

        # Sell Logic (Aggressive if spread increasing)
        if spread_increasing and pos > 0:
            # Sell partial to de-risk
            sell_qty = min(pos, 20)
            orders.append(Order(product, ba - 1, -sell_qty))

        return orders

    # ------------------------------------------------------------------
    # OSMIUM
    # ------------------------------------------------------------------
    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths: return []
        
        depth = state.order_depths[product]
        pos = state.position.get(product, 0)
        
        # 1. Denoised VWAP Mid
        b1 = max(depth.buy_orders.keys()) if depth.buy_orders else None
        a1 = min(depth.sell_orders.keys()) if depth.sell_orders else None
        
        if b1 is None or a1 is None:
            # Handle gaps using historical fair
            fair = self.history.get("op_last_vwap", self.OSMIUM_ANCHOR)
        else:
            bv1 = depth.buy_orders[b1]
            av1 = -depth.sell_orders[a1]
            vwap_mid = (b1 * av1 + a1 * bv1) / (bv1 + av1)
            self.history["op_last_vwap"] = vwap_mid
            fair = vwap_mid

        # 2. Fair Value Drift Adjustment
        hist = self.history["op_hist"]
        hist.append(fair)
        if len(hist) > 50: hist = hist[-50:]
        self.history["op_hist"] = hist
        
        # Adjust fair towards historical local mean if it drifts significantly from anchor
        avg_vwap = sum(hist) / len(hist)
        # Use a blend of current VWAP and local average for the 'fair'
        fair = 0.7 * fair + 0.3 * avg_vwap

        # 3. Quoting Mix
        orders: List[Order] = []
        rem_buy = self.LIMIT - pos
        rem_sell = self.LIMIT + pos
        
        # Take logic (Mean Reversion)
        buy_edge = self.OSMIUM_TAKE_EDGE + max(0, pos // self.OSMIUM_EDGE_POS_STEP)
        sell_edge = self.OSMIUM_TAKE_EDGE + max(0, (-pos) // self.OSMIUM_EDGE_POS_STEP)
        
        if depth.sell_orders:
            for ask in sorted(depth.sell_orders.keys()):
                if ask <= fair - buy_edge and rem_buy > 0:
                    qty = min(rem_buy, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty
                    pos += qty
        
        if depth.buy_orders:
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid >= fair + sell_edge and rem_sell > 0:
                    qty = min(rem_sell, depth.buy_orders[bid])
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty
                    pos -= qty

        # MM logic (Market Making)
        # Quote around the denoised fair
        bid_price = int(fair - 1)
        ask_price = int(fair + 1)
        
        if pos > self.OSMIUM_SKEW_SOFT: bid_price -= 1
        if pos < -self.OSMIUM_SKEW_SOFT: ask_price += 1
        
        # Final check to avoid self-crossing or negative spreads
        if bid_price >= ask_price:
            ask_price = bid_price + 1
        
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
