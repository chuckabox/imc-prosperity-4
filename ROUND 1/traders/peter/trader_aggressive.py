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
        """
        Hybrid tape-aware fair price for Osmium.
        Anchors at 10000 with aggressive tape adjustment for momentum capture.
        """
        product = 'ASH_COATED_OSMIUM'
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000

        tape_volume = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                # Only count trades against aggressive buyers/sellers
                if trade.price >= 10000:
                    tape_volume += trade.quantity
                else:
                    tape_volume -= trade.quantity

        # Aggressive tape adjustment with cap for stability
        tape_adj = math.copysign(min(abs(tape_volume) * 0.15, 2.5), tape_volume)
        return 10000.0 + tape_adj

    def get_pepper_fair(self, state: TradingState) -> float:
        """
        Regression + momentum fair price for Pepper Root.
        Predicts next price from 3-lag autoregression, boosted
        when volume momentum confirms the direction.
        """
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
        if len(hist) > 3:
            hist = hist[-3:]
        self.history[product] = hist

        if len(hist) < 3:
            return mid

        prediction = self.sf_intercept
        for i in range(3):
            prediction += self.sf_weights[i] * hist[-(i + 1)]

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
            if direction == pred_direction:  # confluent signal
                prediction += direction * 1.0

        return prediction

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ── ASH_COATED_OSMIUM: Hybrid Sniper + Aggressive Pennying ──────────
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

            # 1. SNIPER MODE: Aggressive taker for mispriced orders
            take_margin = 2.5  # Strong threshold for high-probability fills

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

            # 2. AGGRESSIVE PENNYING: Queue-jump to be #1
            # Softer skew for tighter spreads
            skew_factor = 0.05

            bid_price = math.floor(fair - 0.5 - (position * skew_factor))
            ask_price = math.ceil(fair + 0.5 - (position * skew_factor))

            # Penny the best existing orders: bid +1, ask -1
            final_bid = min(best_bid + 1, bid_price)
            final_ask = max(best_ask - 1, ask_price)

            # Safety: stay reasonably close to fair
            final_bid = min(final_bid, math.floor(fair - 0.5))
            final_ask = max(final_ask, math.ceil(fair + 0.5))

            # Place passive orders with remaining capacity
            if rem_buy > 0:
                orders.append(Order(product, int(final_bid), rem_buy))

            if rem_sell > 0:
                orders.append(Order(product, int(final_ask), -rem_sell))

            result[product] = orders

        # ── INTARIAN_PEPPER_ROOT: aggressive accumulation + spike sales ───
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            buy_cap = limit - position
            sell_cap = limit + position

            fair = self.get_pepper_fair(state)
            orders = []

            # Take ALL available asks greedily — no price filter.
            # The regression edge (~+0.25/tick) is too small to use as a buy
            # threshold; any ask below future price is a good buy in an uptrend.
            for ask in sorted(depth.sell_orders.keys()):
                if buy_cap <= 0:
                    break
                qty = min(abs(depth.sell_orders[ask]), buy_cap)
                orders.append(Order(product, ask, qty))
                buy_cap -= qty

            # If order book was thin, leave a resting bid just above best bid
            # so we get filled as new sellers arrive.
            if buy_cap > 0 and depth.buy_orders:
                best_bid = max(depth.buy_orders.keys())
                orders.append(Order(product, best_bid + 1, buy_cap))

            # Sell only on sharp spikes well above fair (profit-take without
            # fighting the trend). fair + 3 gives a generous buffer.
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid > fair + 3.0 and sell_cap > 0:
                    qty = min(abs(depth.buy_orders[bid]), sell_cap)
                    orders.append(Order(product, bid, -qty))
                    sell_cap -= qty
                else:
                    break

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
