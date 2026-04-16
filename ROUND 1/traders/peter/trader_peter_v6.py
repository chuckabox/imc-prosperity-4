import json
import math
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
    trader_peter_v6: The 'Tape-Feeder' Edition.
    -------------------------------------------
    - Insight: Osmium Mean Reversion is WEAK.
    - Pivot: De-weighted anchor logic; Heavy weight on Order Book Imbalance & Tape Flow.
    - Logic: Use 'Micro-Imbalance' to shift fair value rather than static distance-from-10k.
    - Style: Adaptive Market Maker.
    """
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 80,
            'INTARIAN_PEPPER_ROOT': 80
        }
        self.history = {}
        # V6 Parameters
        self.os_tape_mult = 0.25 # Increased from 0.185
        self.os_pull_mult = 0.05 # Decreased from 0.15 (De-anchor)
        self.imbal_lookback = 5

    def update_history(self, trader_data: str):
        if trader_data:
            try: self.history = json.loads(trader_data)
            except: self.history = {}

    def get_imbalance(self, depth: OrderDepth) -> float:
        # Micro-discrepancy detection
        bids = depth.buy_orders
        asks = depth.sell_orders
        if not bids or not asks: return 0.0
        
        # Focus on top 2 levels (where the 'small discrepancies' live)
        b1_v = list(bids.values())[0] if bids else 0
        a1_v = abs(list(asks.values())[0]) if asks else 0
        
        total = b1_v + a1_v
        if total == 0: return 0.0
        return (b1_v - a1_v) / total

    def get_osmium_fair(self, state: TradingState) -> float:
        product = 'ASH_COATED_OSMIUM'
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
        mid = (best_bid + best_ask) / 2.0
        
        # 1. Tape Flow (Aggressive pressure)
        tape_volume = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                # Dynamic Volume Weighting
                if trade.price >= mid: tape_volume += trade.quantity
                else: tape_volume -= trade.quantity
        
        tape_adj = math.copysign(min(abs(tape_volume) * self.os_tape_mult, 4.0), tape_volume)
        
        # 2. Imbalance Shift (The 'Small Discrepancy' Alpha)
        imbal = self.get_imbalance(depth)
        imbal_adj = imbal * 1.5 # Shift fair value towards the heavier side
        
        # 3. Weak Mean Reversion (De-weighted)
        mid_pull = (mid - 10000.0) * self.os_pull_mult
        mid_pull = max(-0.8, min(0.8, mid_pull))
        
        return 10000.0 + tape_adj + imbal_adj + mid_pull

    def get_pepper_fair(self, state: TradingState) -> float:
        product = 'INTARIAN_PEPPER_ROOT'
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 12500
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 12500
        mid = (best_bid + best_ask) / 2.0
        
        # Stick to V3 Regression for Pepper (It works)
        hist = self.history.get(product, [])
        hist.append(mid)
        if len(hist) > 3: hist = hist[-3:]
        self.history[product] = hist
        
        if len(hist) < 3: return mid
        # Simplified V3 weights
        return 0.2535 + (0.34 * hist[-1]) + (0.32 * hist[-2]) + (0.33 * hist[-3])

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ── ASH_COATED_OSMIUM: Imbalance-Aware MM ──
        product = 'ASH_COATED_OSMIUM'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            fair = self.get_osmium_fair(state)
            imbal = self.get_imbalance(depth)
            
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
            
            orders = []
            rem_buy = 80 - position
            rem_sell = 80 + position
            
            # Use Imbalance to widen/narrow the 'Take' threshold
            # If imbal > 0 (bullish), we are more willing to buy closer to fair
            take_margin = 2.4 - (imbal * 0.4) 
            
            # Phase 1: Selective Taking
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - take_margin and rem_buy > 0:
                    qty = min(rem_buy, -vol); orders.append(Order(product, ask, qty))
                    rem_buy -= qty; position += qty
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + take_margin and rem_sell > 0:
                    qty = min(rem_sell, vol); orders.append(Order(product, bid, -qty))
                    rem_sell -= qty; position -= qty

            # Phase 2: Dynamic MM Skew
            # Heavily skew quotes based on current inventory to fight 'Weak Reversion'
            skew = 0.08 if abs(position) < 40 else 0.12
            bid_p = math.floor(fair - 0.5 - (position * skew))
            ask_p = math.ceil(fair + 0.5 - (position * skew))
            
            # Top-of-Book pennying only if it doesn't cross fair
            bid_p = min(bid_p, best_bid + 1, math.floor(fair - 0.5))
            ask_p = max(ask_p, best_ask - 1, math.ceil(fair + 0.5))

            if rem_buy > 0:
                orders.append(Order(product, int(bid_p), rem_buy))
            if rem_sell > 0:
                orders.append(Order(product, int(ask_p), -rem_sell))
            
            result[product] = orders

        # ── INTARIAN_PEPPER_ROOT: V3 Trend Follower ──
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            # Consistent V3 logic as it outperformed all others in audit
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            rem_buy = 80 - position; rem_sell = 80 + position
            fair = self.get_pepper_fair(state)
            orders = []
            for ask in sorted(depth.sell_orders.keys()):
                if rem_buy <= 0: break
                qty = min(abs(depth.sell_orders[ask]), rem_buy)
                orders.append(Order(product, ask, qty)); rem_buy -= qty
            if rem_buy > 0 and depth.buy_orders:
                orders.append(Order(product, max(depth.buy_orders.keys()) + 1, rem_buy))
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid > fair + 3.0 and rem_sell > 0:
                    qty = min(abs(depth.buy_orders[bid]), rem_sell); orders.append(Order(product, bid, -qty)); rem_sell -= qty
                else: break
            result[product] = orders

        trader_data = json.dumps(self.history)
        return result, 0, trader_data
