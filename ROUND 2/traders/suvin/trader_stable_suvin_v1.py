import json
from typing import Dict, List, Tuple
import math
from datamodel import Order, TradingState

class Trader:
    def __init__(self):
        self.history: Dict[str, list] = {}

    def _load_state(self, state: TradingState):
        if state.traderData:
            try: self.history = json.loads(state.traderData)
            except: self.history = {}

    def _logic(self, p, state: TradingState) -> List[Order]:
        depth = state.order_depths[p]; pos = state.position.get(p, 0); ts = state.timestamp
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None; ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if not bb or not ba: return []
        mid = (bb + ba) / 2.0
        
        if f"{p}_lm" in self.history:
            diff = (mid - self.history[f"{p}_lm"]) * self.history[f"{p}_lp"]
            self.history[f"{p}_cpnl"] = self.history.get(f"{p}_cpnl", 0.0) + diff
        self.history[f"{p}_lm"] = mid; self.history[f"{p}_lp"] = pos
        cpnl = self.history.get(f"{p}_cpnl", 0.0)
        
        is_core = p in ["INTARIAN_PEPPER_ROOT", "ASH_COATED_OSMIUM"]
        
        # Expanded downside protection to accommodate 100-lot swings 
        abs_limit = -5500 if is_core else -3500
        
        if cpnl < abs_limit or self.history.get(f"{p}_killed", False):
            self.history[f"{p}_killed"] = True
            if pos > 0: return [Order(p, bb - 2, -pos)]
            elif pos < 0: return [Order(p, ba + 2, abs(pos))]
            return []

        # ----------------------------------------------------------------
        # A. PEPPER 
        # ----------------------------------------------------------------
        if p == "INTARIAN_PEPPER_ROOT":
            limit = 100; h = self.history.setdefault("pp_h", []); h.append(mid)
            if len(h) > 60: h.pop(0)
            target = 0; bh = self.history.setdefault("pp_bh", [])
            if len(bh) < 15: bh.append(mid)
            if "pp_t0" not in self.history: self.history["pp_t0"] = ts
            
            if len(bh) >= 15 and len(h) >= 15:
                drift = (sum(h[-15:])/15.0 - sum(bh)/15.0) / max(1, ts - self.history["pp_t0"]) * 100.0
                if drift > 0.008: target = limit
                elif drift < -0.008: target = -limit
                elif drift > 0.002: target = 65
                elif drift < -0.002: target = -65

            if len(h) >= 15 and h[-1] - h[-15] < -12:
                if pos > 0: return [Order(p, bb, -min(pos, 50))]
                
            orders: List[Order] = []; rem = target - pos
            if rem > 0:
                for k in sorted(depth.sell_orders.keys()):
                    if rem <= 0: break
                    if k <= mid + 5: 
                        q = min(rem, -depth.sell_orders[k]); orders.append(Order(p, k, q)); rem -= q
            elif rem < 0:
                for k in sorted(depth.buy_orders.keys(), reverse=True):
                    if rem >= 0: break
                    if k >= mid - 5:
                        q = min(abs(rem), depth.buy_orders[k]); orders.append(Order(p, k, -q)); rem += q
            return orders

        # ----------------------------------------------------------------
        # B. OSMIUM
        # ----------------------------------------------------------------
        elif p == "ASH_COATED_OSMIUM":
            fair = 10000.0; bv = sum(depth.buy_orders.values()); av = sum(-v for v in depth.sell_orders.values())
            if bv > av * 1.5: fair += 2.0
            elif av > bv * 1.5: fair -= 2.0
            
            skew = int(pos / 25); bp = max(bb + 1, int(fair - 1) - skew); ap = min(ba - 1, int(fair + 1) - skew)
            if bp >= ap: bp = int(fair - 1) - skew; ap = int(fair + 1) - skew
            
            orders = []; rb = 100 - pos; rs = 100 + pos
            if rb > 0: orders.append(Order(p, bp, rb))
            if rs > 0: orders.append(Order(p, ap, -rs))
            return orders
            
        return []

    def run(self, state: TradingState):
        self._load_state(state)
        res = {}
        for p in state.order_depths:
            orders = self._logic(p, state)
            if orders: res[p] = orders
        return res, 0, json.dumps(self.history)