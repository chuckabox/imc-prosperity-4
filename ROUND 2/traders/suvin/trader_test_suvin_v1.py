import json
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

def _median(vals: list) -> float:
    n = len(vals)
    if n == 0: return 0.0
    s = sorted(vals)
    mid = n // 2
    return float(s[mid]) if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0

class Trader:
    LIMIT = 80
    OSMIUM_ANCHOR = 10_000

    # THE HYBRID ALPHA CONFIG
    DRIFT_LARGE = 0.012
    DRIFT_SMALL = 0.003
    CRASH_SLOPE = -12          # The 'Robust' Shield
    IMBALANCE_NUDGE = 2.0      # The 'Extreme' Nudge

    def __init__(self):
        self.history: Dict[str, list] = {}

    def _load_state(self, state: TradingState):
        if state.traderData:
            try: self.history = json.loads(state.traderData)
            except: self.history = {}

    def _pepper_logic(self, state: TradingState) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths: return []
        depth = state.order_depths[product]; pos = state.position.get(product, 0)
        if not depth.buy_orders or not depth.sell_orders: return []

        bb = max(depth.buy_orders.keys()); ba = min(depth.sell_orders.keys())
        mid = (bb + ba) / 2.0; ts = state.timestamp

        hist = self.history.setdefault("pp", [])
        hist.append(mid)
        if len(hist) > 80: hist.pop(0)

        base_samples = self.history.setdefault("pp_base", [])
        if len(base_samples) < 15: base_samples.append(mid)
        start_ts = self.history.setdefault("pp_t0", ts)

        # 1. SIGNAL: Drift-Sensitive Momentum (Extreme-Style)
        target_pos = 0
        if len(base_samples) >= 15 and len(hist) >= 15:
            base_mean = _median(base_samples)
            current_mean = _median(hist[-15:])
            drift = (current_mean - base_mean) / max(1, ts - start_ts) * 100.0
            
            if drift > self.DRIFT_LARGE: target_pos = 80
            elif drift < -self.DRIFT_LARGE: target_pos = -80
            elif drift > self.DRIFT_SMALL: target_pos = 60
            elif drift < -self.DRIFT_SMALL: target_pos = -60

        # 2. SHIELD: Slope Stop Loss (Robust-Style)
        stop_breach = int(self.history.get("pp_breach", 0))
        drift_stopped = bool(self.history.get("pp_stopped", False))
        if len(hist) >= 20:
            slope_w = hist[-1] - hist[-20]
            if slope_w < self.CRASH_SLOPE: stop_breach += 1
            else: stop_breach = 0
            if stop_breach >= 2: drift_stopped = True
            elif drift_stopped and slope_w > 5: drift_stopped = False
        self.history["pp_breach"] = stop_breach; self.history["pp_stopped"] = drift_stopped

        orders: List[Order] = []
        rem = target_pos - pos
        if drift_stopped:
            if pos > 0: orders.append(Order(product, bb, -min(pos, 30)))
            return orders

        # 3. EXECUTION: Tier 4 Depth Sweeping
        if rem > 0:
            for ask in sorted(depth.sell_orders.keys()):
                if rem <= 0: break
                if ask <= mid + 5: # Aggressive fill
                    q = min(rem, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, q)); rem -= q
            if rem > 0: orders.append(Order(product, bb + 1, rem))
        elif rem < 0:
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if rem >= 0: break
                if bid >= mid - 5: # Aggressive fill
                    q = min(abs(rem), depth.buy_orders[bid])
                    orders.append(Order(product, bid, -q)); rem += q
            if rem < 0: orders.append(Order(product, ba - 1, rem))

        return orders

    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths: return []
        depth = state.order_depths[product]; pos = state.position.get(product, 0)
        if not depth.buy_orders or not depth.sell_orders: return []

        bb = max(depth.buy_orders.keys()); ba = min(depth.sell_orders.keys())
        fair = float(self.OSMIUM_ANCHOR)

        # 1. ALPHA: Predictive Imbalance Nudge
        bv = sum(depth.buy_orders.values()); av = sum(-v for v in depth.sell_orders.values())
        if bv > av * 1.3: fair += self.IMBALANCE_NUDGE
        elif av > bv * 1.3: fair -= self.IMBALANCE_NUDGE

        # 2. EXECUTION: High-Frequency Bidding
        orders: List[Order] = []; rb = self.LIMIT - pos; rs = self.LIMIT + pos
        
        # Take liquidity near fair
        for ask in sorted(depth.sell_orders.keys()):
            if ask <= fair and rb > 0:
                q = min(rb, -depth.sell_orders[ask]); orders.append(Order(product, ask, q))
                rb -= q; pos += q
        for bid in sorted(depth.buy_orders.keys(), reverse=True):
            if bid >= fair and rs > 0:
                q = min(rs, depth.buy_orders[bid]); orders.append(Order(product, bid, -q))
                rs -= q; pos -= q

        # Quoting: Always at the best price
        bp = max(bb + 1, int(fair - 1)); ap = min(ba - 1, int(fair + 1))
        if bp >= ap: bp = int(fair - 1); ap = int(fair + 1)
        
        if rb > 0: orders.append(Order(product, bp, rb))
        if rs > 0: orders.append(Order(product, ap, -rs))

        return orders

    def run(self, state: TradingState):
        self._load_state(state)
        res = {}
        pep = self._pepper_logic(state); res["INTARIAN_PEPPER_ROOT"] = pep
        osm = self._osmium_logic(state); res["ASH_COATED_OSMIUM"] = osm
        return res, 0, json.dumps(self.history)