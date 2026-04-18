import json
from typing import Dict, List
from datamodel import Order, TradingState

def _median(vals: list) -> float:
    n = len(vals)
    if n == 0: return 0.0
    s = sorted(vals); mid = n // 2
    return float(s[mid]) if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0

class Trader:
    LIMIT = 80
    OSMIUM_ANCHOR = 10_000
    
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
        self.history["pp"] = hist
        
        base_samples = self.history.setdefault("pp_base", [])
        if len(base_samples) < 10: 
            base_samples.append(mid)
        
        start_ts = self.history.setdefault("pp_t0", ts)
        
        orders: List[Order] = []
        
        warmed_up = (ts - start_ts) >= 1200
        fast_track = (ts - start_ts) >= 500
        
        cap = 0
        if len(base_samples) >= 10 and len(hist) >= 10:
            base_mean = _median(base_samples)
            current_mean = _median(hist[-10:])
            drift = (current_mean - base_mean) / max(1, ts - start_ts) * 100.0
            
            if fast_track and drift >= 0.08:
                cap = 80
            elif warmed_up:
                if drift > 0.04: cap = 80
                elif drift > 0.01: cap = 60
                elif drift > -0.01: cap = 30
        
        stop_breach = int(self.history.get("pp_breach", 0))
        drift_stopped = bool(self.history.get("pp_stopped", False))
        was_stopped = drift_stopped

        if len(hist) >= 20:
            slope_w = hist[-1] - hist[-20]
            if slope_w < -12:
                stop_breach += 1
            else:
                stop_breach = 0
                
            if stop_breach >= 2: drift_stopped = True
            elif drift_stopped and slope_w > 5: drift_stopped = False

        self.history["pp_breach"] = stop_breach
        self.history["pp_stopped"] = drift_stopped

        rem_cap = cap - pos
        if drift_stopped or cap == 0:
            if pos > 0:
                chunk = 30 if (drift_stopped and not was_stopped) else 15
                avail = depth.buy_orders.get(bb, 0)
                qty = min(pos, avail, chunk)
                if qty > 0: orders.append(Order(product, bb, -qty))
            return orders
            
        # V4 Normalized Edge: Optimal liquidity draw
        take_budget = min(rem_cap, 15 if cap == 80 else 10)
        taken = 0
        
        for ask in sorted(depth.sell_orders.keys()):
            if take_budget <= 0: break
            avail = -depth.sell_orders[ask]
            if avail <= 0: continue
            if ask <= mid + 1:
                qty = min(take_budget, avail)
                orders.append(Order(product, ask, qty))
                take_budget -= qty
                taken += qty
                
        rem_cap -= taken
        if rem_cap > 0:
            passive_qty = min(rem_cap, 40)
            orders.append(Order(product, bb + 1, passive_qty))
            
        return orders

    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths: return []
        
        depth = state.order_depths[product]; pos = state.position.get(product, 0)
        if not depth.buy_orders or not depth.sell_orders: return []
        
        bb = max(depth.buy_orders.keys()); ba = min(depth.sell_orders.keys())
        mid = (bb + ba) / 2.0; fair = self.OSMIUM_ANCHOR
        
        op = self.history.setdefault("op", [])
        op.append(mid)
        if len(op) > 20: op.pop(0)
        
        # Drift Penalty: Reduces size manually if average deviates from 10k
        size_scale = 1.0
        if len(op) == 20:
            avg = sum(op) / 20.0
            if abs(avg - fair) > 6:
                size_scale = 0.5
        
        # V2 Edge: Tighter Toxicity Filter
        buy_vol = 0; sell_vol = 0
        if product in state.market_trades:
            for t in state.market_trades[product]:
                if t.price >= mid: buy_vol += abs(t.quantity)
                else: sell_vol += abs(t.quantity)
        
        diff = buy_vol - sell_vol
        toxic_buys = diff >= 40
        toxic_sells = -diff >= 40
        
        orders: List[Order] = []; rb = self.LIMIT - pos; rs = self.LIMIT + pos
        
        # Only take liquidity if NOT toxic
        if not toxic_buys:
            for ask in sorted(depth.sell_orders.keys()):
                if ask <= fair - 1 and rb > 0:
                    q = min(rb, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, q)); rb -= q; pos += q
                    
        if not toxic_sells:
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid >= fair + 1 and rs > 0:
                    q = min(rs, depth.buy_orders[bid])
                    orders.append(Order(product, bid, -q)); rs -= q; pos -= q
                    
        # Flattening sequence optimized for 10k anchor
        flatten_bound = 55
        if pos > flatten_bound and rs > 0:
            q = min(pos - flatten_bound + 5, rs)
            orders.append(Order(product, fair, -q)); rs -= q
        elif pos < -flatten_bound and rb > 0:
            q = min(-pos - flatten_bound + 5, rb)
            orders.append(Order(product, fair, q)); rb -= q
                
        # Skew Logic
        skew = int(pos / 22)
        bp = max(int(min(bb + 1, fair - 1) - skew), fair - 4)
        ap = min(int(max(ba - 1, fair + 1) - skew), fair + 4)
        if bp >= ap: bp = fair - 1; ap = fair + 1
        
        front = max(6, int(28 * size_scale))
        second = max(4, int(22 * size_scale))
        
        if rb > 0:
            q = min(rb, front); orders.append(Order(product, bp, q)); rb -= q
            if rb > 0: orders.append(Order(product, bp - 1, min(rb, second)))
        if rs > 0:
            q = min(rs, front); orders.append(Order(product, ap, -q)); rs -= q
            if rs > 0: orders.append(Order(product, ap + 1, -min(rs, second)))
            
        return orders

    def run(self, state: TradingState):
        self._load_state(state)
        res = {}
        pep = self._pepper_logic(state)
        if pep: res["INTARIAN_PEPPER_ROOT"] = pep
        osm = self._osmium_logic(state)
        if osm: res["ASH_COATED_OSMIUM"] = osm
        return res, 0, json.dumps(self.history)
