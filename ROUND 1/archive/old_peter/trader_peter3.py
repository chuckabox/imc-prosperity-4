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
        Tape-aware fair price for Osmium.
        Uses mid-price as baseline (not hardcoded 10000) and adjusts
        by recent trade flow to detect short-term momentum.
        Stronger momentum tracking for better spread positioning.
        """
        product = 'ASH_COATED_OSMIUM'
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
        mid = (best_bid + best_ask) / 2.0

        tape_volume = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= mid:
                    tape_volume += trade.quantity
                else:
                    tape_volume -= trade.quantity

        # Use uncapped tape adjustment with stronger multiplier for momentum capture
        tape_adj = tape_volume * 0.25
        return mid + tape_adj

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

        # ── ASH_COATED_OSMIUM: momentum-aware market making ──────────────────
        product = 'ASH_COATED_OSMIUM'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            buy_cap = limit - position    # max additional units we can buy
            sell_cap = limit + position   # max units we can sell

            fair = self.get_osmium_fair(state)

            # Calculate momentum strength from recent trades
            momentum_vol = 0
            if product in state.market_trades:
                for trade in state.market_trades[product]:
                    if trade.price >= fair:
                        momentum_vol += trade.quantity
                    else:
                        momentum_vol -= trade.quantity

            # Dynamic thresholds based on momentum strength
            momentum_strength = abs(momentum_vol) / max(1, len(state.market_trades.get(product, [])))

            # In strong uptrend, buy at fair; in downtrend, sell at fair
            bullish_threshold = 1.0 - (0.5 * min(momentum_vol / 50.0, 1))  # Tighter when bullish
            bearish_threshold = 1.0 + (0.5 * min(-momentum_vol / 50.0, 1))  # Tighter when bearish

            orders: List[Order] = []

            # 1. Aggressive sniping underpriced asks (wider range in uptrend)
            for ask in sorted(depth.sell_orders.keys()):
                if ask < fair - bullish_threshold and buy_cap > 0:
                    qty = min(abs(depth.sell_orders[ask]), buy_cap)
                    orders.append(Order(product, ask, qty))
                    buy_cap -= qty
                else:
                    break

            # 2. Aggressive sniping overpriced bids (wider range in downtrend)
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid > fair + bearish_threshold and sell_cap > 0:
                    qty = min(abs(depth.buy_orders[bid]), sell_cap)
                    orders.append(Order(product, bid, -qty))
                    sell_cap -= qty
                else:
                    break

            # 3. Passive market making with wider spreads for better margins
            #    Increase spread when we have inventory and momentum is weak
            pos_skew = position / limit
            passive_spread = 2 + momentum_strength  # Wider when momentum is weak

            if buy_cap > 0:
                # Adjust based on momentum direction
                if momentum_vol > 0:
                    passive_buy = int(fair - 1)  # Lean in on bullish momentum
                else:
                    passive_buy = int(fair - passive_spread)
                orders.append(Order(product, passive_buy, buy_cap))

            if sell_cap > 0:
                # Adjust based on momentum direction
                if momentum_vol < 0:
                    passive_sell = int(fair + 1)  # Lean in on bearish momentum
                else:
                    passive_sell = int(fair + passive_spread)
                orders.append(Order(product, passive_sell, -sell_cap))

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
