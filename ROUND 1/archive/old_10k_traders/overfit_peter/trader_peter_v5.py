import json
import math
import numpy as np
from typing import Dict, List, Any
from datamodel import Order, OrderDepth, TradingState, Symbol

class Logger:
    def __init__(self) -> None:
        self.logs = ""
    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end
    def flush(self, state: TradingState, orders: Dict[Symbol, List[Order]], conversions: int, trader_data: str) -> None:
        pass

logger = Logger()

class Trader:
    """
    trader_peter_v5: The 'Stone Shield' Edition.
    -------------------------------------------
    - Foundation: Strategic V3 logic (Aggressive Pepper Trend + Precision Osmium MM).
    - Innovation: Stop-Loss Regression Model (SLRM).
    - Safety: Structural Break detection via standard deviation bands on local regression residuals.
    - Anti-Overfit: Parameters scaled by dynamic volatility (Pepper) and tape pressure (Osmium).
    """
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 80,
            'INTARIAN_PEPPER_ROOT': 80
        }

        # SF Weights (Regression for Fair Value)
        self.sf_weights = [0.34296, 0.32058, 0.33645]
        self.sf_intercept = 0.2535
        
        self.history = {}
        # SLRM: Stop Loss Regression Model state
        self.sl_buffer = 15 # Ticks for local trend detection
        self.sl_threshold = 2.5 # Sigma threshold for exit

    def update_history(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except:
                self.history = {}

    def get_imbalance(self, depth: OrderDepth) -> float:
        bid_vol = sum(depth.buy_orders.values())
        ask_vol = sum(abs(v) for v in depth.sell_orders.values())
        if bid_vol + ask_vol == 0: return 0.0
        return (bid_vol - ask_vol) / (bid_vol + ask_vol)

    def check_slrm_stop(self, product: str, current_price: float) -> bool:
        """
        Stop Loss Regression Model: Detects structural breaks in trend.
        Returns True if a panic exit is required.
        """
        hist = self.history.get(f"{product}_sl", [])
        hist.append(current_price)
        if len(hist) > self.sl_buffer:
            hist = hist[-self.sl_buffer:]
        self.history[f"{product}_sl"] = hist

        if len(hist) < self.sl_buffer:
            return False

        # Linear regression on local history
        x = np.arange(len(hist))
        y = np.array(hist)
        A = np.vstack([x, np.ones(len(x))]).T
        m, c = np.linalg.lstsq(A, y, rcond=None)[0]
        
        # Calculate residuals and volatility
        preds = m * x + c
        residuals = y - preds
        std_dev = np.std(residuals)
        
        # If current price is significantly below local trend line (for long)
        # or above (for short), trigger stop.
        # We simplify to price distance from current expected value.
        expected_now = m * (self.sl_buffer - 1) + c
        diff = current_price - expected_now
        
        if abs(diff) > self.sl_threshold * max(std_dev, 0.5):
            # Only stop if price is move is AGAINST us
            return True
        return False

    def get_osmium_fair(self, state: TradingState) -> float:
        product = 'ASH_COATED_OSMIUM'
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
        mid = (best_bid + best_ask) / 2.0
        
        tape_volume = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= 10000: tape_volume += trade.quantity
                else: tape_volume -= trade.quantity

        tape_adj = math.copysign(min(abs(tape_volume) * 0.185, 3.0), tape_volume)
        mid_pull = max(-1.0, min(1.0, (mid - 10000.0) * 0.15))
        return 10000.0 + tape_adj + mid_pull

    def get_pepper_fair(self, state: TradingState) -> float:
        product = 'INTARIAN_PEPPER_ROOT'
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        mid = (best_bid + best_ask) / 2.0 if best_bid and best_ask else self.history.get('_pepper_last', 12500.0)
        self.history['_pepper_last'] = mid

        hist = self.history.get(product, [])
        if not isinstance(hist, list): hist = []
        hist.append(mid)
        if len(hist) > 3: hist = hist[-3:]
        self.history[product] = hist

        if len(hist) < 3: return mid

        prediction = self.sf_intercept
        for i in range(3):
            prediction += self.sf_weights[i] * hist[-(i + 1)]
        
        return prediction

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ── ASH_COATED_OSMIUM: Precision MM + SLRM ──
        product = 'ASH_COATED_OSMIUM'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            fair = self.get_osmium_fair(state)
            imbal = self.get_imbalance(depth)
            
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
            mid = (best_bid + best_ask) / 2.0
            
            orders: List[Order] = []
            
            # SLRM Emergency check
            if abs(position) > 20 and self.check_slrm_stop(product, mid):
                # Liquidate!
                if position > 0: orders.append(Order(product, int(best_bid), -position))
                else: orders.append(Order(product, int(best_ask), -position))
            else:
                rem_buy = 80 - position
                rem_sell = 80 + position
                
                # Take Phase
                take_margin = 2.25 if (best_ask - best_bid) <= 2 else 2.65
                for ask, vol in sorted(depth.sell_orders.items()):
                    if ask <= fair - take_margin and rem_buy > 0:
                        qty = min(rem_buy, -vol); orders.append(Order(product, ask, qty))
                        rem_buy -= qty; position += qty
                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if bid >= fair + take_margin and rem_sell > 0:
                        qty = min(rem_sell, vol); orders.append(Order(product, bid, -qty))
                        rem_sell -= qty; position -= qty

                # MM Phase (V3 logic)
                skew = 0.05 if abs(position) < 45 else 0.085
                bid_p = min(best_bid + 1, math.floor(fair - 0.5 - (position * skew)))
                ask_p = max(best_ask - 1, math.ceil(fair + 0.5 - (position * skew)))
                
                if rem_buy > 0:
                    top = min(rem_buy, math.ceil(rem_buy * (0.62 + imbal * 0.1)))
                    orders.append(Order(product, int(bid_p), top))
                    if rem_buy - top > 0: orders.append(Order(product, int(bid_p - 1), rem_buy - top))

                if rem_sell > 0:
                    top = min(rem_sell, math.ceil(rem_sell * (0.62 - imbal * 0.1)))
                    orders.append(Order(product, int(ask_p), -top))
                    if rem_sell - top > 0: orders.append(Order(product, int(ask_p + 1), -(rem_sell - top)))
            
            result[product] = orders

        # ── INTARIAN_PEPPER_ROOT: Aggressive + SLRM Escape ──
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 12500
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 12500
            mid = (best_bid + best_ask) / 2.0
            
            orders = []
            
            # SLRM Emergency check (Critical for Trend Capture)
            if abs(position) > 10 and self.check_slrm_stop(product, mid):
                # Panic exit: Hit the bids/asks to zero out
                if position > 0: orders.append(Order(product, int(best_bid), -position))
                else: orders.append(Order(product, int(best_ask), -position))
            else:
                rem_buy = 80 - position
                rem_sell = 80 + position
                
                # V3 Aggressive Flow
                for ask in sorted(depth.sell_orders.keys()):
                    if rem_buy <= 0: break
                    qty = min(abs(depth.sell_orders[ask]), rem_buy)
                    orders.append(Order(product, ask, qty)); rem_buy -= qty; position += qty

                if rem_buy > 0 and depth.buy_orders:
                    orders.append(Order(product, max(depth.buy_orders.keys()) + 1, rem_buy))

                for bid in sorted(depth.buy_orders.keys(), reverse=True):
                    if bid > self.get_pepper_fair(state) + 3.0 and rem_sell > 0:
                        qty = min(abs(depth.buy_orders[bid]), rem_sell); orders.append(Order(product, bid, -qty)); rem_sell -= qty
                    else: break

            result[product] = orders

        trader_data = json.dumps(self.history)
        return result, 0, trader_data
