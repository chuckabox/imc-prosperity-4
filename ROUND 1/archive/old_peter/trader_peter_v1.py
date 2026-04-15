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
            return self.history.get('_pepper_last', 12500.0)

        mid = ((best_bid or best_ask) + (best_ask or best_bid)) / 2.0
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

        momentum = 0
        if product in state.market_trades and state.market_trades[product]:
            for trade in state.market_trades[product]:
                if trade.price >= mid:
                    momentum += trade.quantity
                else:
                    momentum -= trade.quantity
        
        self.history[f'{product}_momentum'] = momentum

        if momentum != 0:
            direction = 1 if momentum > 0 else -1
            pred_direction = 1 if prediction > mid else -1
            if direction == pred_direction:
                prediction += direction * 1.0

        return prediction

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ── ASH_COATED_OSMIUM ──────────────────────────────────────────────
        product = 'ASH_COATED_OSMIUM'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            fair = self.get_osmium_fair(state)
            
            orders: List[Order] = []
            rem_buy = limit - position
            rem_sell = limit + position
            
            # Sniper
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

            # Pennying
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(fair - 1)
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(fair + 1)
            
            skew = -0.05 * position
            bid_p = math.floor(fair - 0.5 + skew)
            ask_p = math.ceil(fair + 0.5 + skew)
            
            final_bid = min(best_bid + 1, bid_p, math.floor(fair - 0.5))
            final_ask = max(best_ask - 1, ask_p, math.ceil(fair + 0.5))
            
            if rem_buy > 0:
                orders.append(Order(product, int(final_bid), rem_buy))
            if rem_sell > 0:
                orders.append(Order(product, int(final_ask), -rem_sell))
            result[product] = orders

        # ── INTARIAN_PEPPER_ROOT ───────────────────────────────────────────
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            fair = self.get_pepper_fair(state)
            momentum = self.history.get(f'{product}_momentum', 0)
            
            orders = []
            
            # 1. ACCUMULATION (Taker)
            # Remove the price-cap guard that was blocking trend entry.
            # Instead, we rely on the stop-loss to protect the downside.
            buy_cap = limit - position
            if momentum >= -2: # Only buy if not crashing
                for ask, vol in sorted(depth.sell_orders.items()):
                    if buy_cap <= 0: break
                    qty = min(abs(vol), buy_cap)
                    orders.append(Order(product, ask, qty))
                    buy_cap -= qty
                    position += qty

            # 2. PASSIVE BIDDING
            rem_buy = limit - position
            if rem_buy > 0 and depth.buy_orders:
                best_bid = max(depth.buy_orders.keys())
                bid_price = min(best_bid + 1, math.floor(fair - 0.5))
                orders.append(Order(product, int(bid_price), rem_buy))

            # 3. DYNAMIC EXITS (Safeguards)
            # Ensure we only close existing positions.
            if position > 0:
                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    # Profit exit
                    is_profit_spike = (bid > fair + 3.0)
                    # Stop loss exit (only if trend confirms reversal)
                    is_panic_exit = (bid < fair - 4.0 and momentum < 0)
                    
                    if is_profit_spike or is_panic_exit:
                        qty = min(abs(vol), position)
                        if qty > 0:
                            orders.append(Order(product, bid, -qty))
                            position -= qty
                    else:
                        break

            # 4. PASSIVE OFFERS
            rem_sell = limit + position
            if rem_sell > 0:
                best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(fair + 1)
                ask_price = max(best_ask - 1, math.ceil(fair + 1.5))
                orders.append(Order(product, int(ask_price), -rem_sell))

            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
