"""
trader_robust_suvin_v2.py
Iteration 28: The Golden Restoration
Reverted hyperparameters and quoting logic to Match Champion (v1).
Retained Safety Tech (CUSUM/Z-Stop/JB) but tightened for current-day volatility.
"""

import json
import math
import statistics
from typing import Dict, List, Tuple, Optional
from datamodel import Order, OrderDepth, TradingState, Symbol

# ---------------------------------------------------------------------------
# Tiny logger
# ---------------------------------------------------------------------------
class Logger:
    def __init__(self): self.logs = ""
    def print(self, *o, sep=" ", end="\n"): self.logs += sep.join(map(str, o)) + end
    def flush(self, state, orders, conversions, trader_data): pass

logger = Logger()

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def _median(vals: list) -> float:
    n = len(vals)
    if n == 0: return 0.0
    s = sorted(vals); mid = n // 2
    return float(s[mid]) if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0

def _mean_std(vals: list) -> Tuple[float, float]:
    n = len(vals)
    if n < 2: return (vals[0] if n == 1 else 0.0), 1.0
    m = sum(vals) / n
    var = sum((x - m) ** 2 for x in vals) / (n - 1)
    return m, max(math.sqrt(var), 1e-8)

def _zscore(series: list, window: int) -> float:
    if len(series) < max(window, 2): return 0.0
    w = series[-window:]
    m, sd = _mean_std(w)
    return (series[-1] - m) / sd

def _cusum(series: list, window: int, threshold: float) -> bool:
    if len(series) < window + 2: return False
    w = series[-(window + 1):]
    rets = [math.log(w[i] / w[i - 1]) for i in range(1, len(w)) if w[i] > 0 and w[i - 1] > 0]
    if len(rets) < 4: return False
    m, sd = _mean_std(rets)
    s_pos = s_neg = 0.0
    for r in rets:
        s_pos = max(0.0, s_pos + (r - m) / sd)
        s_neg = max(0.0, s_neg - (r - m) / sd)
    return s_pos > threshold or s_neg > threshold

class Trader:
    LIMIT = 80

    # ---- Pepper (Strict Champion Protocol) ----
    PP_WARMUP        = 1500
    PP_REEVAL        = 5000
    PP_SMOOTH        = 15
    PP_SLOPE_STRONG  = 0.06
    PP_CAP_STRONG    = 80
    PP_CAP_TENTATIVE = 20
    PP_PASSIVE_CAP   = 40

    # ---- Osmium (Champion Fidelity) ----
    OSM_ANCHOR       = 10_000
    OSM_CLAMP        = 4
    OSM_FRONT        = 25
    OSM_SECOND       = 15
    OSM_TAKE_EDGE    = 1
    OSM_TOXIC_VOL    = 40

    # Safety Tech (Iteration 28 Tuning)
    OSM_Z_WINDOW     = 40
    OSM_Z_ENTRY      = 2.0     # Tightened for higher conviction
    OSM_Z_STOP       = 3.2     # Tightened for faster crash exit
    OSM_Z_SIZE       = 15      # Scaled down to match Champion risk profile
    CUSUM_THRESH     = 4.0

    def __init__(self):
        self.history: Dict[str, list] = {}

    def _load_state(self, state: TradingState):
        if state.traderData:
            try: self.history = json.loads(state.traderData)
            except: self.history = {}

    def _pepper_logic(self, state: TradingState, osm_cusum: bool) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths: return []
        depth = state.order_depths[product]; pos = state.position.get(product, 0)
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None: return []
        mid = (bb + ba) / 2.0; ts = state.timestamp
        hist = self.history.get("pp", []); hist.append(mid); hist = hist[-80:]; self.history["pp"] = hist
        ss = self.history.get("pp_ss", []); 
        if len(ss) < self.PP_SMOOTH: ss.append(mid); self.history["pp_ss"] = ss
        if "pp_ts0" not in self.history: self.history["pp_ts0"] = ts
        
        cap = self.history.get("pp_cap")
        if cap is None and (ts - self.history["pp_ts0"]) >= self.PP_WARMUP and len(ss) >= self.PP_SMOOTH:
            slope = (mid - _median(ss)) / max(1, ts - self.history["pp_ts0"]) * 100.0
            cap = self.PP_CAP_STRONG if slope > self.PP_SLOPE_STRONG else 0
            self.history["pp_cap"] = cap

        eff_cap = cap if cap is not None else self.PP_CAP_TENTATIVE
        if osm_cusum: eff_cap = max(0, eff_cap // 2)
        
        orders: List[Order] = []; rem = eff_cap - pos
        if rem > 0:
            if bb is not None: orders.append(Order(product, bb + 1, min(rem, self.PP_PASSIVE_CAP)))
        return orders

    def _osmium_logic(self, state: TradingState) -> Tuple[List[Order], bool]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths: return [], False
        depth = state.order_depths[product]; pos = state.position.get(product, 0)
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None: return [], False
        mid = (bb + ba) / 2.0; fair = self.OSM_ANCHOR
        hist = self.history.get("op", []); hist.append(mid); hist = hist[-100:]; self.history["op"] = hist
        
        cusum_fired = _cusum(hist, 30, self.CUSUM_THRESH)
        z = _zscore(hist, self.OSM_Z_WINDOW)
        orders: List[Order] = []; rem_buy = self.LIMIT - pos; rem_sell = self.LIMIT + pos
        
        if abs(z) >= self.OSM_Z_STOP:
            if pos > 0 and rem_sell > 0: orders.append(Order(product, bb, -min(pos, rem_sell)))
            elif pos < 0 and rem_buy > 0: orders.append(Order(product, ba, min(-pos, rem_buy)))
            return orders, cusum_fired

        scale = 0.5 if cusum_fired else 1.0
        front = max(10, int(self.OSM_FRONT * scale))
        
        buy_v = 0; sell_v = 0
        if product in state.market_trades:
            for t in state.market_trades[product]:
                if t.price >= mid: buy_v += abs(t.quantity)
                else: sell_v += abs(t.quantity)
        
        # --- Champion Takers ---
        if (buy_v - sell_v) < self.OSM_TOXIC_VOL:
            for ask in sorted(depth.sell_orders.keys()):
                if ask <= fair - self.OSM_TAKE_EDGE and rem_buy > 0:
                    qty = min(rem_buy, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, qty)); rem_buy -= qty; pos += qty
        if (sell_v - buy_v) < self.OSM_TOXIC_VOL:
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid >= fair + self.OSM_TAKE_EDGE and rem_sell > 0:
                    qty = min(rem_sell, depth.buy_orders[bid])
                    orders.append(Order(product, bid, -qty)); rem_sell -= qty; pos -= qty

        # --- Alpha Slap (Z-Score Takers Only) ---
        if not cusum_fired:
            if z < -self.OSM_Z_ENTRY and rem_buy > 0:
                q = min(rem_buy, self.OSM_Z_SIZE)
                if ba is not None: orders.append(Order(product, ba, q)); rem_buy -= q; pos += q
            elif z > self.OSM_Z_ENTRY and rem_sell > 0:
                q = min(rem_sell, self.OSM_Z_SIZE)
                if bb is not None: orders.append(Order(product, bb, -q)); rem_sell -= q; pos -= q

        # --- Fixed Anchor Passive (Champion Logic) ---
        skew = int(pos / 20)
        bp = int(max(min(bb + 1, fair - 1) - skew, fair - self.OSM_CLAMP))
        ap = int(min(max(ba - 1, fair + 1) - skew, fair + self.OSM_CLAMP))
        
        if rem_buy > 0:
            q = min(rem_buy, front); orders.append(Order(product, bp, q)); rem_buy -= q
            if rem_buy > 0: orders.append(Order(product, bp - 1, min(rem_buy, self.OSM_SECOND)))
        if rem_sell > 0:
            q = min(rem_sell, front); orders.append(Order(product, ap, -q)); rem_sell -= q
            if rem_sell > 0: orders.append(Order(product, ap + 1, -min(rem_sell, self.OSM_SECOND)))
        return orders, cusum_fired

    def run(self, state: TradingState):
        self._load_state(state)
        osm_orders, cusum_fired = self._osmium_logic(state)
        pep_orders = self._pepper_logic(state, cusum_fired)
        res = {"INTARIAN_PEPPER_ROOT": pep_orders, "ASH_COATED_OSMIUM": osm_orders}
        trader_data = json.dumps(self.history)
        return res, 0, trader_data
