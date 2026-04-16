import json
import math
from typing import Dict, List, Any
from datamodel import Order, OrderDepth, TradingState, Symbol

class Trader:
    def __init__(self):
        self.limits = {'ASH_COATED_OSMIUM': 80, 'INTARIAN_PEPPER_ROOT': 80}
        
        # Online AR(3) parameters
        self.ar_weights = {'ASH_COATED_OSMIUM': [0.3616, 0.3148, 0.2925]}
        self.ar_intercept = {'ASH_COATED_OSMIUM': 309.9}
        
        # State tracking
        self.history = {}
        self.residuals = {}
        self.emas = {}

    def run(self, state: TradingState):
        if state.traderData:
            try:
                data = json.loads(state.traderData)
                self.history = data.get("history", {})
                self.ar_weights = data.get("ar_weights", self.ar_weights)
                self.ar_intercept = data.get("ar_intercept", self.ar_intercept)
                self.residuals = data.get("residuals", {})
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
            
            # Sub-state tracking
            phist = self.history.get(product, [])
            rhist = self.residuals.get(product, [])
            
            # Initialize EMA
            if product not in self.emas:
                self.emas[product] = {'fast': mid, 'slow': mid}
            
            # Update EMAs
            fast_ema = self.emas[product]['fast'] * 0.8 + mid * 0.2
            slow_ema = self.emas[product]['slow'] * 0.95 + mid * 0.05
            self.emas[product]['fast'] = fast_ema
            self.emas[product]['slow'] = slow_ema

            fair = mid
            target = 0
            
            # Rolling parameters and memory sizes
            PHIST_LEN = 5
            RHIST_LEN = 40
            
            # --- AR(3) NOISY ESTIMATOR & LMS ADAPTATION ---
            if product == 'ASH_COATED_OSMIUM' and len(phist) >= 4:
                w1, w2, w3 = self.ar_weights[product]
                intercept = self.ar_intercept[product]
                
                # Predict Current Fair Value (Based on lag 1, 2, 3)
                ar_pred = intercept + (w1 * phist[-1]) + (w2 * phist[-2]) + (w3 * phist[-3])
                
                # Evaluate error on current mid vs previous prediction
                # Wait, the prediction for current mid was made yesterday using phist[-2], phist[-3], phist[-4]
                ar_pred_last = intercept + (w1 * phist[-2]) + (w2 * phist[-3]) + (w3 * phist[-4])
                error = mid - ar_pred_last
                
                # Online LMS Coefficient Adaptation
                lr = 1e-9 # Micro learning rate to avoid exploding gradients
                w1 += lr * error * phist[-2]
                w2 += lr * error * phist[-3]
                w3 += lr * error * phist[-4]
                intercept += lr * error
                
                self.ar_weights[product] = [w1, w2, w3]
                self.ar_intercept[product] = intercept
                
                # Store Residuals
                residual = mid - ar_pred
                rhist.append(residual)
                if len(rhist) > RHIST_LEN: rhist.pop(0)
                
                # --- Z-SCORE SIGNIFICANT MISPRICING ---
                if len(rhist) > 10:
                    mean_res = sum(rhist) / len(rhist)
                    var_res = sum((r - mean_res)**2 for r in rhist) / len(rhist)
                    std_res = math.sqrt(var_res) if var_res > 0 else 1.0
                    
                    z_score = (residual - mean_res) / std_res
                    
                    # Volatility-Based Regime Filtering
                    # Filter if volatility (std_res) explodes. 
                    baseline_vol = 5.0
                    vol_penalty = max(1.0, std_res / baseline_vol)
                    
                    # Trade only on statistically significant mispricing (Z-score > 1.5)
                    # Expand Z requirement dynamically if volatility is high
                    z_threshold = 1.5 * vol_penalty
                    
                    if z_score < -z_threshold:
                        target = lim # Severely underpriced
                    elif z_score > z_threshold:
                        target = -lim # Severely overpriced
                    
                    # Fair shifts towards AR predictor
                    fair = ar_pred
                else:
                    fair = ar_pred

            else:
                # Fallback / Robust Momentum Validation for unknown or external products
                threshold_bps = mid * 0.00005 
                if fast_ema > slow_ema + threshold_bps:
                    target = lim
                elif fast_ema < slow_ema - threshold_bps:
                    target = -lim
                    
                fair = fast_ema
                
            # History append after calculation
            phist.append(mid)
            if len(phist) > PHIST_LEN: phist.pop(0)
            
            self.history[product] = phist
            self.residuals[product] = rhist
            
            # --- STRICT INVENTORY LIMITS & MARKET MAKING ---
            # Order Imbalance Microstructure
            v_b = depth.buy_orders[best_bid]
            v_a = abs(depth.sell_orders[best_ask])
            imb = (v_b - v_a) / (v_b + v_a)
            
            # Spread Base (BPS for external scaling robustness)
            spread_bps = max(1.5, mid * 0.00015)
            fair += imb * (spread_bps * 0.5)
            
            # Strict inventory skew (aggressively return to target)
            skew = (pos - target) * (spread_bps / lim) * 2.0 
            
            buy_price = math.floor(fair - spread_bps - skew)
            sell_price = math.ceil(fair + spread_bps - skew)
            
            # Prevent bad quotes near limit bounds
            if pos >= lim * 0.9: buy_price = math.floor(fair - spread_bps * 5) # Drop bid
            if pos <= -lim * 0.9: sell_price = math.ceil(fair + spread_bps * 5) # Raise ask
            
            orders = []
            block = 20
            
            buy_rem = lim - pos
            if buy_rem > 0:
                for i in range(4):
                    if buy_rem <= 0: break
                    p = int(buy_price - i)
                    q = min(buy_rem, block)
                    orders.append(Order(product, p, q))
                    buy_rem -= q
                    
            sell_rem = lim + pos
            if sell_rem > 0:
                for i in range(4):
                    if sell_rem <= 0: break
                    p = int(sell_price + i)
                    q = min(sell_rem, block)
                    orders.append(Order(product, p, -q))
                    sell_rem -= q
                    
            result[product] = orders
            
        trader_state = {
            "history": self.history,
            "ar_weights": self.ar_weights,
            "ar_intercept": self.ar_intercept,
            "residuals": self.residuals,
            "emas": self.emas
        }
        return result, 0, json.dumps(trader_state)
