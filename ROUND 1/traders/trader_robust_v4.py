import json
import math
import collections
from typing import Dict, List, Any
from datamodel import Order, OrderDepth, TradingState, Symbol

class Logger:
    def __init__(self) -> None:
        pass
    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        pass
    def flush(self, state: TradingState, orders: Dict[Symbol, List[Order]], conversions: int, trader_data: str) -> None:
        pass

class Trader:
    def __init__(self):
        self.limits = {'ASH_COATED_OSMIUM': 80, 'INTARIAN_PEPPER_ROOT': 80}
        
        # Online AR(3) parameters (Osmium Hidden Pattern)
        self.ar_weights = {'ASH_COATED_OSMIUM': [0.3616, 0.3148, 0.2925]}
        self.ar_intercept = {'ASH_COATED_OSMIUM': 309.9}
        
        # State tracking (Aggregated from Michael Okon strategy patterns)
        self.history = collections.defaultdict(list)
        self.residuals = collections.defaultdict(list)
        self.emas = {}
        self.vwma_history = collections.defaultdict(list)

    def run(self, state: TradingState):
        if state.traderData:
            try:
                data = json.loads(state.traderData)
                # Recover histories
                for k, v in data.get("history", {}).items(): self.history[k] = v
                for k, v in data.get("residuals", {}).items(): self.residuals[k] = v
                for k, v in data.get("vwma", {}).items(): self.vwma_history[k] = v
                
                self.ar_weights = data.get("ar_weights", self.ar_weights)
                self.ar_intercept = data.get("ar_intercept", self.ar_intercept)
                self.emas = data.get("emas", {})
            except:
                pass
                
        result = {}
        for product in self.limits.keys():
            if product not in state.order_depths: continue
            
            depth = state.order_depths[product]
            pos = state.position.get(product, 0)
            lim = self.limits[product]
            
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 0
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 0
            if not best_bid or not best_ask: continue
            
            mid = (best_bid + best_ask) / 2.0
            
            # --- FEATURE 1: MICHAEL OKON VWMA FILTER ---
            # Compute Volume Weighted Mid to filter spoofing
            v_sum = sum(depth.buy_orders.values()) + sum(abs(v) for v in depth.sell_orders.values())
            pv_sum = sum(p * v for p, v in depth.buy_orders.items()) + sum(p * abs(v) for p, v in depth.sell_orders.items())
            vw_mid = pv_sum / v_sum if v_sum > 0 else mid
            
            # --- FEATURE 2: AR(3) ADAPTIVE FAIR VALUE ---
            phist = self.history[product]
            rhist = self.residuals[product]
            
            if product not in self.emas: self.emas[product] = {'fast': mid, 'slow': mid}
            self.emas[product]['fast'] = self.emas[product]['fast'] * 0.8 + mid * 0.2
            self.emas[product]['slow'] = self.emas[product]['slow'] * 0.95 + mid * 0.05
            
            fair = mid
            target = 0
            spread_bps = max(1.5, mid * 0.00015)

            if product == 'ASH_COATED_OSMIUM' and len(phist) >= 4:
                w1, w2, w3 = self.ar_weights[product]
                intercept = self.ar_intercept[product]
                
                # Predict
                ar_pred = intercept + (w1 * phist[-1]) + (w2 * phist[-2]) + (w3 * phist[-3])
                
                # LMS Adaptation (LR slightly higher for responsiveness)
                lr = 2e-9 
                err = mid - (intercept + w1*phist[-2] + w2*phist[-3] + w3*phist[-4])
                self.ar_weights[product] = [w1 + lr*err*phist[-2], w2 + lr*err*phist[-3], w3 + lr*err*phist[-4]]
                self.ar_intercept[product] += lr*err
                
                # Z-Score Reversion
                rhist.append(mid - ar_pred)
                if len(rhist) > 40: rhist.pop(0)
                
                if len(rhist) > 15:
                    std = math.sqrt(sum((r - (sum(rhist)/len(rhist)))**2 for r in rhist) / len(rhist)) + 1e-6
                    z = (mid - ar_pred) / std
                    
                    # Confidence threshold
                    if z < -1.6: target = lim
                    elif z > 1.6: target = -lim
                
                fair = (ar_pred + vw_mid) / 2.0 # Blend AR with Volume-Weighted Truth
            
            else:
                # PEPPER: Momentum + Mean Reversion Blend
                fast = self.emas[product]['fast']
                slow = self.emas[product]['slow']
                
                # REVERSION DIFF (from michael_okon diff_strategy):
                diff = fast - slow
                if diff < -spread_bps: target = lim
                elif diff > spread_bps: target = -lim
                
                fair = fast

            # Save histories
            phist.append(mid)
            if len(phist) > 10: phist.pop(0)
            self.history[product] = phist
            
            # --- EXECUTION ---
            # Combine Z-Score target with Order Flow Imbalance
            v_b, v_a = depth.buy_orders[best_bid], abs(depth.sell_orders[best_ask])
            imb = (v_b - v_a) / (v_b + v_a)
            fair += imb * (spread_bps * 0.4)
            
            # Robust Dynamic Skew
            skew = (pos - target) * (spread_bps / lim) * 2.2
            
            buy_p = int(math.floor(fair - spread_bps - skew))
            sell_p = int(math.ceil(fair + spread_bps - skew))
            
            # Position Barrier Protection
            if pos >= lim * 0.85: buy_p -= 1
            if pos <= -lim * 0.85: sell_p += 1
            
            orders = [Order(product, buy_p, lim - pos), Order(product, sell_p, -(lim + pos))]
            result[product] = orders

        return result, 0, json.dumps({
            "history": self.history, "residuals": self.residuals, "vwma": self.vwma_history,
            "ar_weights": self.ar_weights, "ar_intercept": self.ar_intercept, "emas": self.emas
        })
