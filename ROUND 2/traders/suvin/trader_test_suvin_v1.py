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

    def _logic(self, p: str, state: TradingState) -> List[Order]:
        depth = state.order_depths[p]; pos = state.position.get(p, 0); ts = state.timestamp
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None; ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if not bb or not ba: return []
        mid = (bb + ba) / 2.0
        
        # 1. PnL TRACKING
        if f"{p}_lm" in self.history:
            diff = (mid - self.history[f"{p}_lm"]) * self.history[f"{p}_lp"]
            self.history[f"{p}_cpnl"] = self.history.get(f"{p}_cpnl", 0.0) + diff
            self.history["gl_pnl"] = self.history.get("gl_pnl", 0.0) + diff
        self.history[f"{p}_lm"] = mid; self.history[f"{p}_lp"] = pos
        
        cpnl = self.history.get(f"{p}_cpnl", 0.0); gl_pnl = self.history.get("gl_pnl", 0.0)
        hwm = max(self.history.get(f"{p}_hwm", -999999.0), cpnl); self.history[f"{p}_hwm"] = hwm
        
        # 2. TITAN SHIELD (Exchange Cap 80)
        gl_stop = -5000.0; asset_trail = 2500.0 
        
        if (gl_pnl < gl_stop or cpnl < hwm - asset_trail or self.history.get(f"{p}_killed", False) or self.history.get("gl_killed", False)):
            if gl_pnl < gl_stop: self.history["gl_killed"] = True
            self.history[f"{p}_killed"] = True
            if pos > 0: return [Order(p, bb - 5, -pos)]
            elif pos < 0: return [Order(p, ba + 5, abs(pos))]
            return []

        # ----------------------------------------------------------------
        # A. PEPPER: TITAN ALPHA (Extreme Frequency - 300k Target)
        # ----------------------------------------------------------------
        if p == "INTARIAN_PEPPER_ROOT":
            limit = 80; h = self.history.setdefault("pp_h", []); h.append(mid)
            if len(h) > 60: h.pop(0)
            target = 0
            if len(h) >= 45:
                # Lowered drift threshold (0.3) to compensate for 80-unit cap
                drift = (sum(h[-10:]) / 10.0 - sum(h[-45:]) / 45.0)
                if drift > 0.30: target = limit
                elif drift < -0.30: target = -limit
                elif drift > 0.10: target = limit // 2
                elif drift < -0.10: target = -(limit // 2)

            if len(h) >= 15 and h[-1] - h[-15] < -12:
                if pos > 0: return [Order(p, bb, -min(pos, 50))]
                
            orders: List[Order] = []; rem = target - pos
            if rem > 0:
                for k in sorted(depth.sell_orders.keys()):
                    if rem <= 0: break
                    if k <= mid + 8: 
                        q = min(rem, -depth.sell_orders[k]); orders.append(Order(p, k, q)); rem -= q
                if rem > 0: orders.append(Order(p, bb + 1, rem)) 
            elif rem < 0:
                for k in sorted(depth.buy_orders.keys(), reverse=True):
                    if rem >= 0: break
                    if k >= mid - 8:
                        q = min(abs(rem), depth.buy_orders[k]); orders.append(Order(p, k, -q)); rem += q
                if rem < 0: orders.append(Order(p, ba - 1, rem))
            return orders

        # ----------------------------------------------------------------
        # B. OSMIUM: TITAN ALPHA (Capacity 80)
        # ----------------------------------------------------------------
        elif p == "ASH_COATED_OSMIUM":
            limit = 80; fair = 10000.0
            bv = sum(depth.buy_orders.values()); av = sum(-v for v in depth.sell_orders.values())
            if bv > av * 1.3: fair += 3.0
            elif av > bv * 1.3: fair -= 3.0
            
            skew = int(pos / 20); bp = max(bb + 1, int(fair - 1) - skew); ap = min(ba - 1, int(fair + 1) - skew)
            if bp >= ap: bp = int(fair - 1) - skew; ap = int(fair + 1) - skew
            
            orders = []; rb = limit - pos; rs = limit + pos
            if rb > 0: orders.append(Order(p, bp, rb))
            if rs > 0: orders.append(Order(p, ap, -rs))
            
            if mid < fair - 2 and rb > 0:
                for k in sorted(depth.sell_orders.keys()):
                    if k < fair:
                        q = min(rb, -depth.sell_orders[k]); orders.append(Order(p, k, q)); rb -= q
            elif mid > fair + 2 and rs > 0:
                for k in sorted(depth.buy_orders.keys(), reverse=True):
                    if k > fair:
                        q = min(rs, depth.buy_orders[k]); orders.append(Order(p, k, -q)); rs -= q
            return orders
            
        # ----------------------------------------------------------------
        # C. GENERIC: ALPHA HARVESTER (Capacity 80)
        # ----------------------------------------------------------------
        else:
            limit = 80; gh = self.history.setdefault(f"{p}_gh", []); gh.append(mid)
            if len(gh) > 60: gh.pop(0)
            if len(gh) < 20: return []
            m = sum(gh)/len(gh); std = math.sqrt(sum((x-m)**2 for x in gh)/len(gh)) if len(gh)>1 else 1.0
            z = (mid - m) / std if std > 0 else 0
            orders = []; rem = 0
            if z < -2.0: rem = limit - pos
            elif z > 2.0: rem = -(limit + pos)
            elif abs(z) < 1.0 and abs(pos) > 0: rem = -pos
            if pos < limit: orders.append(Order(p, bb + 1, limit // 4))
            if pos > -limit: orders.append(Order(p, ba - 1, -limit // 4))
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

    def run(self, state: TradingState):
        self._load_state(state)
        res = {}
        for p in state.order_depths:
            orders = self._logic(p, state)
            if orders: res[p] = orders
        return res, 0, json.dumps(self.history)
