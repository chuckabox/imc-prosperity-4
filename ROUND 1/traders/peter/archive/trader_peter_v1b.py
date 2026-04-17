import json
import math
from typing import Dict, List, Any

from datamodel import Order, OrderDepth, TradingState, Symbol


class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        conversions: int,
        trader_data: str,
    ) -> None:
        pass


logger = Logger()


class Trader:
    """
    Peter V1b: 
    - Linear Regression Fair Value for Pepper
    - Price Velocity Drift defense for Osmium
    """

    LIMIT_OSMIUM = 80
    LIMIT_PEPPER = 80
    
    WINDOW_SIZE = 100
    WARMUP = 20

    def __init__(self):
        self.limits = {
            "ASH_COATED_OSMIUM": self.LIMIT_OSMIUM,
            "INTARIAN_PEPPER_ROOT": self.LIMIT_PEPPER,
        }
        self.history = {}

    def _load_state(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except Exception:
                self.history = {}

    def _ema(self, prices: list, span: int) -> float:
        if not prices: return 0.0
        alpha = 2.0 / (span + 1)
        val = prices[0]
        for p in prices[1:]:
            val = alpha * p + (1 - alpha) * val
        return val

    def _std_dev(self, prices: list) -> float:
        if len(prices) < 2: return 1.0
        mu = sum(prices) / len(prices)
        variance = sum((x - mu) ** 2 for x in prices) / len(prices)
        return max(math.sqrt(variance), 0.5)

    def _linreg_slope(self, y: list) -> float:
        n = len(y)
        if n < 2: return 0.0
        sum_x = n * (n - 1) / 2.0
        sum_y = sum(y)
        sum_xx = n * (n - 1) * (2 * n - 1) / 6.0
        sum_xy = sum(i * y[i] for i in range(n))
        denominator = n * sum_xx - sum_x**2
        if denominator == 0: return 0.0
        return (n * sum_xy - sum_x * sum_y) / denominator

    def _get_wmid(self, depth: OrderDepth) -> float:
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if best_bid and best_ask:
            b_qty = depth.buy_orders[best_bid]
            a_qty = abs(depth.sell_orders[best_ask])
            return (best_bid * a_qty + best_ask * b_qty) / (b_qty + a_qty)
        return best_bid or best_ask or 0.0

    def _pepper_logic(self, state: TradingState) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths: return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)
        limit = self.limits[product]
        wmid = self._get_wmid(depth)
        
        hist = self.history.get("pp", [])
        hist.append(wmid)
        if len(hist) > self.WINDOW_SIZE: hist.pop(0)
        self.history["pp"] = hist

        if len(hist) < self.WARMUP: return []

        # Technical Indicators
        ema_f = self._ema(hist, 8)
        ema_s = self._ema(hist, 24)
        volat = self._std_dev(hist[-25:])
        
        # Momentum normalized by volatility (Context)
        momentum = (ema_f - ema_s) / volat
        momentum_skew = max(-2.5, min(2.5, momentum * 1.2))

        slope = self._linreg_slope(hist)

        # Dynamic inventory skew
        inv_ratio = pos / limit
        inv_skew = (inv_ratio * 4.0) + math.copysign((inv_ratio ** 2) * 3.0, inv_ratio)

        # Adjust fair by trend slope (projecting slow-growing trend)
        fair = ema_f + momentum_skew + (slope * 20.0)
        
        # Dynamic Spread based on Volatility
        spread_half = max(1.0, volat * 0.65)
        
        bid_price = math.floor(fair - spread_half - inv_skew)
        ask_price = math.ceil(fair + spread_half - inv_skew)

        # Microstructure bounds
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if best_bid is not None: bid_price = min(bid_price, best_bid + 1)
        if best_ask is not None: ask_price = max(ask_price, best_ask - 1)
        if bid_price >= ask_price: ask_price = bid_price + 1

        orders = []
        buy_cap = limit - pos
        sell_cap = limit + pos

        # Layered quoting
        if buy_cap > 0:
            q = min(buy_cap, 25)
            orders.append(Order(product, int(bid_price), q))
            if buy_cap > 25:
                orders.append(Order(product, int(bid_price - 1), min(buy_cap - 25, 25)))

        if sell_cap > 0:
            q = min(sell_cap, 25)
            orders.append(Order(product, int(ask_price), -q))
            if sell_cap > 25:
                orders.append(Order(product, int(ask_price + 1), -min(sell_cap - 25, 25)))

        # Emergency Unwind
        if abs(pos) > limit * 0.75:
            if pos > 35 and best_bid is not None:
                orders.append(Order(product, best_bid, -min(pos - 35, 20)))
            elif pos < -35 and best_ask is not None:
                orders.append(Order(product, best_ask, min(abs(pos) - 35, 20)))

        return orders

    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths: return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)
        limit = self.limits[product]
        wmid = self._get_wmid(depth)
        
        hist = self.history.get("op", [])
        hist.append(wmid)
        if len(hist) > self.WINDOW_SIZE: hist.pop(0)
        self.history["op"] = hist

        if len(hist) < self.WARMUP: return []

        # Price Velocity (absolute change over time)
        velocity = abs(hist[-1] - hist[0]) / len(hist) if len(hist) > 1 else 0.0

        # Tape Reading (Market Trades)
        tape_val = 0.0
        if product in state.market_trades:
            for t in state.market_trades[product]:
                tape_val += t.quantity if t.price >= wmid else -t.quantity
        
        self.history["tape"] = self.history.get("tape", 0) * 0.6 + tape_val * 0.4
        tape_signal = max(-1.5, min(1.5, self.history["tape"] * 0.08))

        # Anchoring to long-term mean
        anchor = self._ema(hist, 40)
        volat = self._std_dev(hist[-20:])
        
        fair = anchor + tape_signal
        
        # Widen spread if velocity is high
        spread_base = max(0.5, volat * 0.4) + (velocity * 20.0)

        # Increase inventory leaning strength if velocity is high
        inv_skew_factor = 0.06 + (velocity * 1.5)
        inv_skew = pos * inv_skew_factor
        
        bid_price = math.floor(fair - spread_base - inv_skew)
        ask_price = math.ceil(fair + spread_base - inv_skew)

        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if best_bid is not None: bid_price = min(bid_price, best_bid + 1)
        if best_ask is not None: ask_price = max(ask_price, best_ask - 1)

        orders = []
        rem_buy = limit - pos
        rem_sell = limit + pos

        # Aggressive Take (also penalized by velocity to avoid bad fills in drift)
        take_threshold = max(2.0, volat * 1.2) + (velocity * 10.0)
        if best_ask is not None and best_ask <= fair - take_threshold and rem_buy > 0:
            q = min(rem_buy, -depth.sell_orders.get(best_ask, 0))
            orders.append(Order(product, best_ask, q))
            rem_buy -= q
        if best_bid is not None and best_bid >= fair + take_threshold and rem_sell > 0:
            q = min(rem_sell, depth.buy_orders.get(best_bid, 0))
            orders.append(Order(product, best_bid, -q))
            rem_sell -= q

        if rem_buy > 0:
            orders.append(Order(product, int(bid_price), min(rem_buy, 45)))
        if rem_sell > 0:
            orders.append(Order(product, int(ask_price), -min(rem_sell, 45)))

        return orders

    def run(self, state: TradingState):
        self._load_state(state.traderData)
        result = {}
        
        pep = self._pepper_logic(state)
        if pep: result["INTARIAN_PEPPER_ROOT"] = pep
        
        osm = self._osmium_logic(state)
        if osm: result["ASH_COATED_OSMIUM"] = osm

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
