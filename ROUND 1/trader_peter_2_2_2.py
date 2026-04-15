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
    2-Regime Dual-Strategy System (trader_peter_2_2_2)
    ===================================================

    CORE LOGIC:
    - INTARIAN_PEPPER_ROOT: Pure mean reversion (stable PnL engine)
    - ASH_COATED_OSMIUM: Momentum/Reversal regime detection (directional alpha)

    Regimes for Osmium:
    1. UPTREND: short_mom > 0 AND long_mom >= 0 → hold small long, buy dips
    2. DOWNTREND: short_mom < 0 AND long_mom <= 0 → hold small short, sell rallies
    3. NEUTRAL: unclear signal → market make only, no directional exposure

    Position Targets:
    - Working position: 20-40 units
    - Max position: 80 units
    - Reduce when regime unclear
    """

    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 80,
            'INTARIAN_PEPPER_ROOT': 80
        }

        # Pepper Root: Regression weights (3-lag)
        self.sf_weights = [0.34296, 0.32058, 0.33645]
        self.sf_intercept = 0.2535

        self.history = {
            'ASH_COATED_OSMIUM': [],
            'INTARIAN_PEPPER_ROOT': []
        }
        self.regime = 'NEUTRAL'
        self.traderData = ""

    def update_history(self, trader_data: str):
        if trader_data:
            try:
                data = json.loads(trader_data)
                self.history = data.get('history', self.history)
                self.regime = data.get('regime', 'NEUTRAL')
            except:
                pass

    def detect_regime(self, product: str) -> str:
        """
        Detect regime for Osmium using momentum analysis.
        Returns: 'UPTREND', 'DOWNTREND', or 'NEUTRAL'
        """
        if product != 'ASH_COATED_OSMIUM':
            return 'NEUTRAL'

        hist = self.history.get(product, [])
        if len(hist) < 8:
            return 'NEUTRAL'

        # short momentum: mid[-1] - mid[-3]
        short_mom = hist[-1] - hist[-3] if len(hist) >= 3 else 0
        # long momentum: mid[-3] - mid[-8]
        long_mom = hist[-3] - hist[-8] if len(hist) >= 8 else 0

        # Regime detection
        if short_mom > 0 and long_mom >= 0:
            return 'UPTREND'
        elif short_mom < 0 and long_mom <= 0:
            return 'DOWNTREND'
        else:
            return 'NEUTRAL'

    def get_fair_price_roots(self, state: TradingState) -> float:
        """
        INTARIAN_PEPPER_ROOT: Mean reversion fair price.
        Uses 3-lag regression.
        """
        product = 'INTARIAN_PEPPER_ROOT'
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
        mid_price = (best_bid + best_ask) / 2.0

        hist = self.history.get(product, [])
        if not isinstance(hist, list):
            hist = []

        hist.append(mid_price)
        if len(hist) > 3:
            hist = hist[-3:]
        self.history[product] = hist

        if len(hist) < 3:
            return mid_price

        # Regression prediction
        prediction = self.sf_intercept
        for i in range(3):
            prediction += self.sf_weights[i] * hist[-(i + 1)]

        return prediction

    def get_fair_price_osmium(self, state: TradingState) -> float:
        """
        ASH_COATED_OSMIUM: Regime-aware fair price.
        Base: 10000 with tape reading adjustment.
        """
        product = 'ASH_COATED_OSMIUM'
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
        mid_price = (best_bid + best_ask) / 2.0

        # Update history for regime detection
        hist = self.history.get(product, [])
        if not isinstance(hist, list):
            hist = []
        hist.append(mid_price)
        if len(hist) > 8:
            hist = hist[-8:]
        self.history[product] = hist

        # Tape reading adjustment
        tape_volume = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= mid_price:
                    tape_volume += trade.quantity
                else:
                    tape_volume -= trade.quantity

        tape_adj = math.copysign(min(abs(tape_volume) * 0.15, 2.5), tape_volume)

        return 10000.0 + tape_adj

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # Process both products
        for product in self.limits.keys():
            if product not in state.order_depths:
                continue

            depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            position = state.position.get(product, 0)
            limit = self.limits[product]

            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 0
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 0
            if not best_bid or not best_ask:
                continue

            if product == 'INTARIAN_PEPPER_ROOT':
                # ============= PEPPER ROOT: PURE MEAN REVERSION =============
                fair_price = self.get_fair_price_roots(state)

                # Aggressive mean reversion parameters
                take_margin = 1.5

                # Snipe aggressively on reversions
                rem_buy = limit - position
                for ask, vol in sorted(depth.sell_orders.items()):
                    if ask < fair_price - take_margin and rem_buy > 0:
                        qty = min(rem_buy, -vol)
                        orders.append(Order(product, ask, qty))
                        rem_buy -= qty
                        position += qty

                rem_sell = limit + position
                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if bid > fair_price + take_margin and rem_sell > 0:
                        qty = min(rem_sell, vol)
                        orders.append(Order(product, bid, -qty))
                        rem_sell -= qty
                        position -= qty

                # Aggressive maker: try to close out position
                skew_factor = 0.08
                bid_price = math.floor(fair_price - 0.5 - (position * skew_factor))
                ask_price = math.ceil(fair_price + 0.5 - (position * skew_factor))

                final_bid = min(best_bid + 1, bid_price)
                final_ask = max(best_ask - 1, ask_price)

                final_bid = min(final_bid, math.floor(fair_price - 0.5))
                final_ask = max(final_ask, math.ceil(fair_price + 0.5))

                rem_buy = limit - position
                if rem_buy > 0:
                    orders.append(Order(product, int(final_bid), rem_buy))

                rem_sell = limit + position
                if rem_sell > 0:
                    orders.append(Order(product, int(final_ask), -rem_sell))

            elif product == 'ASH_COATED_OSMIUM':
                # ============= OSMIUM: REGIME-BASED MOMENTUM/REVERSAL =============
                fair_price = self.get_fair_price_osmium(state)
                self.regime = self.detect_regime(product)

                if self.regime == 'UPTREND':
                    # Hold small long, buy dips, sell fast
                    target_position = 30  # Small long bias
                    take_margin = 2.0

                    # Buy dips
                    rem_buy = limit - position
                    for ask, vol in sorted(depth.sell_orders.items()):
                        if ask <= fair_price - take_margin and rem_buy > 0 and position < target_position:
                            qty = min(rem_buy, -vol, target_position - position)
                            orders.append(Order(product, ask, qty))
                            rem_buy -= qty
                            position += qty

                    # Quick profit taking (sell at any rally)
                    rem_sell = limit + position
                    for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                        if bid >= fair_price and rem_sell > 0:
                            qty = min(rem_sell, vol, position)
                            orders.append(Order(product, bid, -qty))
                            rem_sell -= qty
                            position -= qty

                elif self.regime == 'DOWNTREND':
                    # Hold small short, sell rallies, avoid buying
                    target_position = -30  # Small short bias
                    take_margin = 2.0

                    # Sell rallies
                    rem_sell = limit + position
                    for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                        if bid >= fair_price + take_margin and rem_sell > 0 and position > target_position:
                            qty = min(rem_sell, vol, position - target_position)
                            orders.append(Order(product, bid, -qty))
                            rem_sell -= qty
                            position -= qty

                    # Quick cover (buy on any dip)
                    rem_buy = limit - position
                    for ask, vol in sorted(depth.sell_orders.items()):
                        if ask <= fair_price and rem_buy > 0:
                            qty = min(rem_buy, -vol, -position)
                            orders.append(Order(product, ask, qty))
                            rem_buy -= qty
                            position += qty

                else:  # NEUTRAL
                    # Market make only, minimal directional exposure
                    # Close existing position gradually
                    take_margin = 1.5

                    # Liquidate long if holding
                    if position > 0:
                        rem_sell = limit + position
                        for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                            if rem_sell > 0:
                                qty = min(rem_sell, vol, position)
                                orders.append(Order(product, bid, -qty))
                                rem_sell -= qty
                                position -= qty

                    # Liquidate short if holding
                    if position < 0:
                        rem_buy = limit - position
                        for ask, vol in sorted(depth.sell_orders.items()):
                            if rem_buy > 0:
                                qty = min(rem_buy, -vol, -position)
                                orders.append(Order(product, ask, qty))
                                rem_buy -= qty
                                position += qty

                    # Light market making
                    skew_factor = 0.03
                    bid_price = math.floor(fair_price - 0.5 - (position * skew_factor))
                    ask_price = math.ceil(fair_price + 0.5 - (position * skew_factor))

                    final_bid = min(best_bid + 1, bid_price)
                    final_ask = max(best_ask - 1, ask_price)

                    rem_buy = min(20, limit - position)
                    if rem_buy > 0:
                        orders.append(Order(product, int(final_bid), rem_buy))

                    rem_sell = min(20, limit + position)
                    if rem_sell > 0:
                        orders.append(Order(product, int(final_ask), -rem_sell))

                # General maker quotes for regime-based position (only if not neutral)
                if self.regime != 'NEUTRAL':
                    skew_factor = 0.05
                    bid_price = math.floor(fair_price - 0.5 - (position * skew_factor))
                    ask_price = math.ceil(fair_price + 0.5 - (position * skew_factor))

                    final_bid = min(best_bid + 1, bid_price)
                    final_ask = max(best_ask - 1, ask_price)

                    final_bid = min(final_bid, math.floor(fair_price - 0.5))
                    final_ask = max(final_ask, math.ceil(fair_price + 0.5))

                    rem_buy = limit - position
                    if rem_buy > 0:
                        orders.append(Order(product, int(final_bid), rem_buy))

                    rem_sell = limit + position
                    if rem_sell > 0:
                        orders.append(Order(product, int(final_ask), -rem_sell))

            result[product] = orders

        # Persist state
        trader_data_dict = {
            'history': self.history,
            'regime': self.regime
        }
        trader_data = json.dumps(trader_data_dict)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
