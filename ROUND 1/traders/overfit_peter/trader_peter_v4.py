import json
import math
import collections
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
    trader_peter_v4: The Hybrid Resilience Model.
    - Optimized Trend-Capture (0.2535 Alpha)
    - Volatility-Aware Take Thresholds (Osmium)
    - Portfolio Heat Mitigation (Safety)
    - Spread Guardian (Maker Protection)
    - Dynamic Layering (Imbalance)
    """
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 80,
            'INTARIAN_PEPPER_ROOT': 80
        }

        # Optimized Parameters
        self.sf_weights = [0.34296, 0.32058, 0.33645]
        self.sf_intercept = 0.2535 
        self.OSMIUM_ANCHOR = 10000.0
        
        # State
        self.history = {}
        self.rolling_prices = collections.defaultdict(lambda: collections.deque(maxlen=40))

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

    def get_volatility(self, product: str, mid: float) -> float:
        p_list = self.rolling_prices[product]
        p_list.append(mid)
        if len(p_list) < 2: return 5.0
        mean = sum(p_list) / len(p_list)
        var = sum((x - mean) ** 2 for x in p_list) / len(p_list)
        return math.sqrt(var)

    def get_osmium_fair(self, state: TradingState, mid: float) -> float:
        product = 'ASH_COATED_OSMIUM'
        tape_volume = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= 10000: tape_volume += trade.quantity
                else: tape_volume -= trade.quantity

        tape_adj = math.copysign(min(abs(tape_volume) * 0.185, 3.0), tape_volume)
        mid_pull = max(-1.0, min(1.0, (mid - 10000.0) * 0.15))
        return 10000.0 + tape_adj + mid_pull

    def get_pepper_fair(self, state: TradingState, mid: float) -> float:
        product = 'INTARIAN_PEPPER_ROOT'
        hist = list(self.rolling_prices[product])
        if len(hist) < 3: return mid

        prediction = self.sf_intercept
        for i in range(3):
            prediction += self.sf_weights[i] * hist[-(i + 1)]
        
        # Confluence (Peter Style)
        momentum = 0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= mid: momentum += trade.quantity
                else: momentum -= trade.quantity
        if (prediction > mid and momentum > 0) or (prediction < mid and momentum < 0):
            prediction += math.copysign(1.0, momentum)
                
        return prediction

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}
        
        # 🛡️ PORTFOLIO HEAT CHECK
        total_pos = sum(abs(state.position.get(p, 0)) for p in self.limits)
        heat_scalar = 1.0 if total_pos < 120 else 0.5

        # ── ASH_COATED_OSMIUM ──
        product = 'ASH_COATED_OSMIUM'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            mid = (max(depth.buy_orders.keys(), default=10000) + min(depth.sell_orders.keys(), default=10000)) / 2.0
            std = self.get_volatility(product, mid)
            fair = self.get_osmium_fair(state, mid)
            imbal = self.get_imbalance(depth)
            
            best_bid = max(depth.buy_orders.keys(), default=10000)
            best_ask = min(depth.sell_orders.keys(), default=10000)
            spread = best_ask - best_bid

            orders: List[Order] = []
            rem_buy = int((80 - position) * heat_scalar)
            rem_sell = int((80 + position) * heat_scalar)
            
            # 🚀 VOLATILITY-SENSITIVE TAKING
            # If market is erratic (std > 7), widen margins to avoid being picked off
            base_take = 2.25
            vol_adj = max(0, (std - 5.7) * 0.2)
            take_margin = base_take + vol_adj
            
            if spread <= 2: take_margin *= 0.9 # Snatch tight spread efficiency

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

            # 🛡️ SPREAD GUARDIAN MM
            skew = 0.05 if abs(position) < 45 else 0.1 # Aggressive de-risking near limits
            bid_p = math.floor(fair - 0.5 - (position * skew))
            ask_p = math.ceil(fair + 0.5 - (position * skew))
            
            # Preserve 1rd tick spread if possible
            final_bid = min(best_bid + 1, bid_p) if spread > 1 else min(best_bid, bid_p)
            final_ask = max(best_ask - 1, ask_p) if spread > 1 else max(best_ask, ask_p)
            
            # Split Quoting with Imbalance awareness
            split = min(0.8, max(0.4, 0.62 + (imbal * 0.15)))
            if rem_buy > 0:
                top = min(rem_buy, math.ceil(rem_buy * split))
                orders.append(Order(product, int(final_bid), top))
                if rem_buy - top > 0: orders.append(Order(product, int(final_bid - 1), rem_buy - top))
            if rem_sell > 0:
                top = min(rem_sell, math.ceil(rem_sell * (1.25 - split)))
                orders.append(Order(product, int(final_ask), -top))
                if rem_sell - top > 0: orders.append(Order(product, int(final_ask + 1), -(rem_sell - top)))
            
            result[product] = orders

        # ── INTARIAN_PEPPER_ROOT ──
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            mid = (max(depth.buy_orders.keys(), default=12500) + min(depth.sell_orders.keys(), default=12500)) / 2.0
            fair = self.get_pepper_fair(state, mid)
            
            orders = []
            buy_cap = int((80 - position) * heat_scalar)
            sell_cap = int((80 + position) * heat_scalar)

            # GOLD LOGIC: Take all asks
            for ask in sorted(depth.sell_orders.keys()):
                if buy_cap <= 0: break
                qty = min(abs(depth.sell_orders[ask]), buy_cap)
                orders.append(Order(product, ask, qty))
                buy_cap -= qty
            
            # Resting Bid
            if buy_cap > 0 and depth.buy_orders:
                orders.append(Order(product, max(depth.buy_orders.keys()) + 1, buy_cap))

            # Spike Exit
            for bid in sorted(depth.buy_orders.items(), reverse=True):
                if bid[0] > fair + 3.0 and sell_cap > 0:
                    qty = min(abs(bid[1]), sell_cap)
                    orders.append(Order(product, bid[0], -qty))
                    sell_cap -= qty
                else: break

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
