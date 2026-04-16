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
    trader_peter_v3: The Ultra-Precision Champion (Rev 2).
    Refined after historical validation:
    - Retains Peter's aggressive Pepper Trend-Capture (Winner logic)
    - Incorporates Ken's Osmium Microstructure (Adaptive Anchor + Split Levels)
    - Adds Imbalance-Aware Dynamic Quote Sizing
    - Adds Spread Clamping (Preserves Maker Spread)
    """
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 80,
            'INTARIAN_PEPPER_ROOT': 80
        }

        self.sf_weights = [0.34296, 0.32058, 0.33645]
        self.sf_intercept = 0.2535
        self.OSMIUM_ANCHOR = 10000.0
        self.history = {}

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
        
        # Confluence Boost
        momentum = 0
        if product in state.market_trades and state.market_trades[product]:
            for trade in state.market_trades[product]:
                if trade.price >= mid: momentum += trade.quantity
                else: momentum -= trade.quantity
        if momentum != 0:
            direction = 1 if momentum > 0 else -1
            if (prediction > mid and direction == 1) or (prediction < mid and direction == -1):
                prediction += direction * 1.0
                
        return prediction

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ── ASH_COATED_OSMIUM: Ken-Architecture Optimized ──
        product = 'ASH_COATED_OSMIUM'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            fair = self.get_osmium_fair(state)
            imbal = self.get_imbalance(depth)
            
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
            spread = max(1, best_ask - best_bid)

            orders: List[Order] = []
            rem_buy = 80 - position
            rem_sell = 80 + position
            
            # Adaptive Thresholds
            take_margin = 2.25 if spread <= 2 else 2.65
            if abs(position) >= 50: take_margin += 0.15
            
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - take_margin and rem_buy > 0:
                    qty = min(rem_buy, -vol)
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty
                    position += qty
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + take_margin and rem_sell > 0:
                    qty = min(rem_sell, vol)
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty
                    position -= qty

            # MM Phase: Dynamic Skew & Layering
            skew = 0.05 if abs(position) < 45 else 0.085
            bid_p = math.floor(fair - 0.5 - (position * skew))
            ask_p = math.ceil(fair + 0.5 - (position * skew))
            
            # Spread Clamping
            final_bid = min(best_bid + 1, bid_p) if spread > 1 else min(best_bid, bid_p)
            final_ask = max(best_ask - 1, ask_p) if spread > 1 else max(best_ask, ask_p)
            
            final_bid = min(final_bid, math.floor(fair - 0.5))
            final_ask = max(final_ask, math.ceil(fair + 0.5))
            
            # Imbalance-Aware Sizing (Split levels)
            buy_split = 0.62 + (imbal * 0.1) # Up to 72% at TOB if bullish
            if rem_buy > 0:
                top = min(rem_buy, math.ceil(rem_buy * buy_split))
                orders.append(Order(product, int(final_bid), top))
                if rem_buy - top > 0: orders.append(Order(product, int(final_bid - 1), rem_buy - top))

            sell_split = 0.62 - (imbal * 0.1) # Up to 72% at TOB if bearish
            if rem_sell > 0:
                top = min(rem_sell, math.ceil(rem_sell * sell_split))
                orders.append(Order(product, int(final_ask), -top))
                if rem_sell - top > 0: orders.append(Order(product, int(final_ask + 1), -(rem_sell - top)))
            
            result[product] = orders

        # ── INTARIAN_PEPPER_ROOT: Peter-Series Gold Logic ──
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            rem_buy = 80 - position
            rem_sell = 80 + position
            fair = self.get_pepper_fair(state)
            orders = []

            # 1. Take ALL available asks (Aggressive Trend Capture)
            for ask in sorted(depth.sell_orders.keys()):
                if rem_buy <= 0: break
                qty = min(abs(depth.sell_orders[ask]), rem_buy)
                orders.append(Order(product, ask, qty))
                rem_buy -= qty
                position += qty

            # 2. Resting Bid (Queue priority)
            if rem_buy > 0 and depth.buy_orders:
                orders.append(Order(product, max(depth.buy_orders.keys()) + 1, rem_buy))

            # 3. Profit-Take only on sharp spikes
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid > fair + 3.0 and rem_sell > 0:
                    qty = min(abs(depth.buy_orders[bid]), rem_sell)
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty
                else: break

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
