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

    def get_ema(self, product: str, current_mid: float, length: int = 20) -> float:
        ema_key = f'{product}_ema'
        prev_ema = self.history.get(ema_key, current_mid)
        alpha = 2 / (length + 1)
        new_ema = (current_mid * alpha) + (prev_ema * (1 - alpha))
        self.history[ema_key] = new_ema
        return new_ema

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ── ASH_COATED_OSMIUM: Dynamic Mean Reversion ──────────────────────
        product = 'ASH_COATED_OSMIUM'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            best_bid = max(depth.buy_orders.keys(), default=10000)
            best_ask = min(depth.sell_orders.keys(), default=10000)
            mid = (best_bid + best_ask) / 2.0
            
            # Use 20-period EMA to follow the trend + tape for momentum
            fair = self.get_ema(product, mid, 20)
            
            tape_volume = 0.0
            if product in state.market_trades:
                for trade in state.market_trades[product]:
                    if trade.price >= mid: tape_volume += trade.quantity
                    else: tape_volume -= trade.quantity
            
            fair += math.copysign(min(abs(tape_volume) * 0.1, 2.0), tape_volume)
            
            orders: List[Order] = []
            rem_buy = self.limits[product] - position
            rem_sell = self.limits[product] + position
            
            # MM Skewed by Position
            skew = -0.1 * position
            bid_p = math.floor(fair - 2.0 + skew)
            ask_p = math.ceil(fair + 2.0 + skew)
            
            if rem_buy > 0: orders.append(Order(product, int(bid_p), rem_buy))
            if rem_sell > 0: orders.append(Order(product, int(ask_p), -rem_sell))
            result[product] = orders

        # ── INTARIAN_PEPPER_ROOT: Trend Following ──────────────────────────
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
            mid = (best_bid + best_ask) / 2.0 if best_bid and best_ask else 12500.0
            
            # Predict fair using regression
            hist = self.history.get(product, [])
            if not isinstance(hist, list): hist = []
            hist.append(mid)
            if len(hist) > 3: hist = hist[-3:]
            self.history[product] = hist
            
            fair = self.sf_intercept
            if len(hist) == 3:
                for i in range(3):
                    fair += self.sf_weights[i] * hist[-(i+1)]
            else:
                fair = mid

            orders = []
            buy_cap = self.limits[product] - position
            sell_cap = self.limits[product] + position
            
            # Regression says UP? Buy.
            if fair > mid:
                for ask, vol in sorted(depth.sell_orders.items()):
                    if buy_cap <= 0: break
                    if ask > fair + 2.0: break # Guard
                    qty = min(abs(vol), buy_cap)
                    orders.append(Order(product, ask, qty))
                    buy_cap -= qty
            
            # Resting Bid
            if buy_cap > 0 and best_bid:
                orders.append(Order(product, best_bid + 1, buy_cap))

            # Profit Take
            if position > 0:
                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if sell_cap <= 0: break
                    if bid > fair + 3.0:
                        qty = min(abs(vol), sell_cap)
                        orders.append(Order(product, bid, -qty))
                        sell_cap -= qty
                    else: break

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
