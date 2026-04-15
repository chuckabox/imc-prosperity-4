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
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 80,
            'INTARIAN_PEPPER_ROOT': 80
        }

        # 3-lag regression weights for Pepper Root
        self.sf_weights = [0.34296, 0.32058, 0.33645]
        self.sf_intercept = 0.2535

        self.history = {}

    def update_history(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except:
                self.history = {}

    def get_osmium_fair(self, state: TradingState) -> float:
        product = 'ASH_COATED_OSMIUM'
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000

        tape_volume = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= 10000:
                    tape_volume += trade.quantity
                else:
                    tape_volume -= trade.quantity

        tape_adj = math.copysign(min(abs(tape_volume) * 0.15, 2.5), tape_volume)
        return 10000.0 + tape_adj

    def get_pepper_fair(self, state: TradingState) -> float:
        product = 'INTARIAN_PEPPER_ROOT'
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None

        if best_bid is None and best_ask is None:
            return self.history.get('_pepper_last', 0.0)

        mid = ((best_bid or best_ask) + (best_ask or best_bid)) / 2.0
        self.history['_pepper_last'] = mid

        hist = self.history.get(product, [])
        if not isinstance(hist, list):
            hist = []

        hist.append(mid)
        if len(hist) > 20: 
            hist = hist[-20:]
        self.history[product] = hist

        if len(hist) < 3:
            return mid

        prediction = self.sf_intercept
        regression_hist = hist[-3:]
        for i in range(3):
            prediction += self.sf_weights[i] * regression_hist[-(i + 1)]

        momentum = 0
        if product in state.market_trades and state.market_trades[product]:
            for trade in state.market_trades[product]:
                if trade.price >= mid:
                    momentum += trade.quantity
                else:
                    momentum -= trade.quantity

        if momentum != 0:
            direction = 1 if momentum > 0 else -1
            pred_direction = 1 if prediction > mid else -1
            if direction == pred_direction:
                prediction += direction * 1.0

        return prediction

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ── ASH_COATED_OSMIUM ──────────────────
        product = 'ASH_COATED_OSMIUM'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
            fair = self.get_osmium_fair(state)
            orders: List[Order] = []
            rem_buy = limit - position
            rem_sell = limit + position
            
            take_margin = 2.5
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

            skew_factor = 0.05
            bid_price = math.floor(fair - 0.5 - (position * skew_factor))
            ask_price = math.ceil(fair + 0.5 - (position * skew_factor))
            final_bid = min(best_bid + 1, bid_price)
            final_ask = max(best_ask - 1, ask_price)
            final_bid = min(final_bid, math.floor(fair - 0.5))
            final_ask = max(final_ask, math.ceil(fair + 0.5))
            if rem_buy > 0:
                orders.append(Order(product, int(final_bid), rem_buy))
            if rem_sell > 0:
                orders.append(Order(product, int(final_ask), -rem_sell))
            result[product] = orders

        # ── INTARIAN_PEPPER_ROOT: Safe & Time-Aware ────────────────
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            
            fair = self.get_pepper_fair(state)
            mid = self.history.get('_pepper_last', fair)
            
            # Phase Detection: 100k timestamp dip expected
            # 100k = active trend region, >100k = caution region
            is_growth_phase = (state.timestamp < 100000)
            
            # Trend Detection (SMA 20)
            hist = self.history.get(product, [])
            sma = sum(hist) / len(hist) if hist else mid
            is_bullish = (mid >= sma - 0.5)

            orders = []
            
            # SCALED AGGRESSION
            if is_growth_phase and is_bullish:
                # Max growth: take all asks up to fair + 1
                buy_cap = limit - position
                for ask in sorted(depth.sell_orders.keys()):
                    if buy_cap <= 0: break
                    if ask > fair + 1.0: break # Tighter than before to avoid taker loss
                    qty = min(abs(depth.sell_orders[ask]), buy_cap)
                    orders.append(Order(product, ask, qty))
                    buy_cap -= qty
                    position += qty
            
            # Passive Bidding (Always present, but price varies)
            rem_buy = limit - position
            if rem_buy > 0:
                # Before 100k: Pay up for liquidity. After 100k: Only deep value.
                bid_margin = 1.0 if is_growth_phase else 3.0
                best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else mid
                bid_price = min(best_bid + 1, math.floor(fair - bid_margin))
                orders.append(Order(product, int(bid_price), rem_buy))

            # SELLING: Profit take + Emergency Stop
            sell_cap = limit + position
            
            # Emergency Stop: If broke SMA during growth, or just cautious after 100k
            needs_exit = (not is_bullish and position > 0) or (state.timestamp >= 100000 and position > limit * 0.5)
            
            if needs_exit:
                # Exit at best bid immediately (taker)
                for bid in sorted(depth.buy_orders.keys(), reverse=True):
                    if position <= 0: break
                    if bid < fair - 2.0 and is_growth_phase: break # Don't dump if too cheap unless panic
                    qty = min(position, abs(depth.buy_orders[bid]))
                    orders.append(Order(product, bid, -qty))
                    position -= qty
                    sell_cap -= qty

            # Normal passive sells (resting orders)
            if sell_cap > 0:
                best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else mid
                ask_margin = 2.0 if is_growth_phase else 0.5 # Sell faster after 100k
                ask_price = max(best_ask - 1, math.ceil(fair + ask_margin))
                orders.append(Order(product, int(ask_price), -sell_cap))

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
