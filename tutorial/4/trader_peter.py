from typing import List
import string
import numpy as np
import json
from typing import Any
import math

import json
from typing import Any
from datamodel import *
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState

class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        # Mute logging for backtests to avoid terminal congestion
        pass

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])

        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]

        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )

        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
            ]

        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])

        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        if len(value) <= max_length:
            return value

        return value[: max_length - 3] + "..."

logger = Logger()

class Trader:
    def __init__(self):
        self.orders = {}
        self.conversions = 0
        self.traderData = ""
        
        # P4 Assets Support
        self.emeralds_position = 0
        self.tomatoes_position = 0
        
        self.emeralds_buy_orders = 0
        self.emeralds_sell_orders = 0
        self.tomatoes_buy_orders = 0
        self.tomatoes_sell_orders = 0
        
        self.config = {
            "emerald_active": True,
            "tomato_active": True,
            "emerald_limit": 20,
            "tomato_limit": 20,
            "target_spread": 1,
            "mr_threshold": 1.5,
            "window_size": 25 # Window for polynomial fitting
        }

    def load_config(self):
        try:
            with open('config.json', 'r') as f:
                self.config.update(json.load(f))
        except:
            pass

    def send_sell_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, int(round(price)), amount))
        if msg: logger.print(msg)

    def send_buy_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, int(round(price)), amount))
        if msg: logger.print(msg)

    def reset_orders(self, state):
        self.orders = {}
        self.conversions = 0
        self.emeralds_position = state.position.get('EMERALDS', 0)
        self.tomatoes_position = state.position.get('TOMATOES', 0)
        for product in state.order_depths:
            self.orders[product] = []

    def get_fair_price_and_drift(self, history, current_time):
        if len(history) < 5:
            return history[-1][1], 0.0, 1.0
            
        times = np.array([pt[0] for pt in history]) - history[0][0]
        values = np.array([pt[1] for pt in history])
        
        try:
            volatility = np.std(values)
            poly = np.polyfit(times, values, 2)
            current_t = current_time - history[0][0]
            
            fair_val = np.polyval(poly, current_t)
            drift = 2 * poly[0] * current_t + poly[1]
            
            return fair_val, drift, max(0.1, volatility)
        except:
            return history[-1][1], 0.0, 1.0

    def trade_emeralds(self, state, fair_value_estimate, drift, volatility):
        if not self.config.get("emerald_active", True): return
        limit = self.config.get("emerald_limit", 20)
        order_depth = state.order_depths.get('EMERALDS')
        if not order_depth or not order_depth.sell_orders or not order_depth.buy_orders: return

        # 1. 95% ANCHORING (Stable peg with slight market sensitivity)
        fair_value = (0.95 * 10000) + (0.05 * fair_value_estimate)
        best_ask = min(order_depth.sell_orders.keys())
        best_bid = max(order_depth.buy_orders.keys())
        
        max_buy = limit - self.emeralds_position
        max_sell = limit + self.emeralds_position

        # MARKET TAKING (Only with edge > 0.5)
        for ask, amount in sorted(order_depth.sell_orders.items()):
            if ask < fair_value - 0.5 and max_buy > 0:
                size = min(max_buy, -amount)
                self.send_buy_order('EMERALDS', int(ask), size)
                self.emeralds_position += size
                max_buy -= size
        
        for bid, amount in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid > fair_value + 0.5 and max_sell > 0:
                size = min(max_sell, amount)
                self.send_sell_order('EMERALDS', int(bid), -size)
                self.emeralds_position -= size
                max_sell -= size

        # 2. DEFENSIVE MARKET MAKING
        # We want to buy at 9999 or lower and sell at 10001 or higher if fair is 10000
        buy_p = min(best_bid + 1, math.floor(fair_value - 1))
        sell_p = max(best_ask - 1, math.ceil(fair_value + 1))

        if max_buy > 0:
            self.send_buy_order('EMERALDS', int(buy_p), max_buy)
        if max_sell > 0:
            self.send_sell_order('EMERALDS', int(sell_p), -max_sell)

    def trade_tomatoes(self, state, fair_value, drift, volatility):
        if not self.config.get("tomato_active", True): return
        limit = self.config.get("tomato_limit", 20)
        order_depth = state.order_depths.get('TOMATOES')
        if not order_depth or not order_depth.sell_orders or not order_depth.buy_orders: return
        
        best_ask = min(order_depth.sell_orders.keys())
        best_bid = max(order_depth.buy_orders.keys())
        
        # 1. STABILIZED DRIFT LEAD (0.8x instead of 1.5x to prevent overshooting)
        signal_mid = fair_value + (drift * 0.8)
        
        max_buy = limit - self.tomatoes_position
        max_sell = limit + self.tomatoes_position
        
        # 2. VOLATILITY Z-SCORE TAKING (1.5x)
        # Only sweep the market if the price is significantly far from our signal (1.5 sigma)
        for ask, amount in sorted(order_depth.sell_orders.items()):
            if ask < signal_mid - (1.5 * volatility) and max_buy > 0:
                size = min(max_buy, -amount)
                self.send_buy_order('TOMATOES', int(ask), size)
                self.tomatoes_position += size
                max_buy -= size
        
        for bid, amount in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid > signal_mid + (1.5 * volatility) and max_sell > 0:
                size = min(max_sell, amount)
                self.send_sell_order('TOMATOES', int(bid), -size)
                self.tomatoes_position -= size
                max_sell -= size

        # 3. DYNAMIC SQUASHING (Inventory-aware pricing)
        # Base pennying
        buy_p = min(best_bid + 1, math.floor(signal_mid - 0.5))
        sell_p = max(best_ask - 1, math.ceil(signal_mid + 0.5))
        
        # Shift quotes based on inventory to encourage mean reversion
        inventory_shift = self.tomatoes_position // 5
        buy_p -= inventory_shift
        sell_p -= inventory_shift
            
        if max_buy > 0: self.send_buy_order('TOMATOES', int(buy_p), max_buy)
        if max_sell > 0: self.send_sell_order('TOMATOES', int(sell_p), -max_sell)


    def run(self, state: TradingState):
        self.load_config()
        self.reset_orders(state)
        
        data = {}
        if state.traderData:
            try: data = json.loads(state.traderData)
            except: pass
        if "history" not in data: data["history"] = {}
            
        for product in ['EMERALDS', 'TOMATOES']:
            if product not in state.order_depths: continue
            depth = state.order_depths[product]
            if not depth.buy_orders or not depth.sell_orders: continue
            
            mid = (max(depth.buy_orders.keys()) + min(depth.sell_orders.keys())) / 2.0
            if product not in data["history"]: data["history"][product] = []
            
            # HYPER-REACT WINDOWS
            win_size = 20 if product == 'EMERALDS' else 30
            
            data["history"][product].append([state.timestamp, mid])
            if len(data["history"][product]) > win_size:
                data["history"][product] = data["history"][product][-win_size:]
            
            fair_val, drift, volatility = self.get_fair_price_and_drift(data["history"][product], state.timestamp)
            
            if product == 'EMERALDS':
                self.trade_emeralds(state, fair_val, drift, volatility)
            elif product == 'TOMATOES':
                self.trade_tomatoes(state, fair_val, drift, volatility)

        self.traderData = json.dumps(data)
        logger.flush(state, self.orders, self.conversions, self.traderData)
        return self.orders, self.conversions, self.traderData