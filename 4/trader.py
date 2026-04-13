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

    def get_starfruit_prediction(self, history):
        if len(history) < 4:
            return history[-1][1]
            
        y = np.array([pt[1] for pt in history])
        x = np.arange(len(y))
        
        n = len(y)
        m = (n * np.sum(x*y) - np.sum(x) * np.sum(y)) / (n * np.sum(x**2) - (np.sum(x))**2)
        c = (np.sum(y) - m * np.sum(x)) / n
        
        # Predict 1.5 steps ahead for reaction buffer
        return m * (n + 0.5) + c

    def trade_emeralds(self, state):
        limit = self.config.get("emerald_limit", 20)
        max_buy = limit - self.emeralds_position
        max_sell = limit + self.emeralds_position

        # Pure Grid Force
        if max_buy > 0: self.send_buy_order('EMERALDS', 9999, max_buy)
        if max_sell > 0: self.send_sell_order('EMERALDS', 10001, -max_sell)

    def trade_tomatoes(self, state, predicted_price):
        limit = self.config.get("tomato_limit", 20)
        order_depth = state.order_depths.get('TOMATOES')
        if not order_depth: return
        
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        
        mm_buy = min(best_bid + 1, math.floor(predicted_price - 0.5))
        mm_sell = max(best_ask - 1, math.ceil(predicted_price + 0.5))
        
        # Aggressive Skew
        if self.tomatoes_position > 8:
            mm_buy -= 2
            mm_sell -= 1
        elif self.tomatoes_position < -8:
            mm_buy += 1
            mm_sell += 2
        elif self.tomatoes_position > 0:
            mm_buy -= 1
        elif self.tomatoes_position < 0:
            mm_sell += 1

        max_buy = limit - self.tomatoes_position
        max_sell = limit + self.tomatoes_position
        
        if max_buy > 0: self.send_buy_order('TOMATOES', int(mm_buy), max_buy)
        if max_sell > 0: self.send_sell_order('TOMATOES', int(mm_sell), -max_sell)

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
            
            mid = (max(depth.buy_orders.keys()) + min(depth.sell_orders.keys())) / 2.0
            if product not in data["history"]: data["history"][product] = []
            
            # Hyper-Reactive Window: 4
            win_size = 4 if product == 'TOMATOES' else 10
            data["history"][product].append([state.timestamp, mid])
            if len(data["history"][product]) > win_size:
                data["history"][product] = data["history"][product][-win_size:]
            
            if product == 'EMERALDS':
                self.trade_emeralds(state)
            elif product == 'TOMATOES':
                pred = self.get_starfruit_prediction(data["history"][product])
                self.trade_tomatoes(state, pred)

        self.traderData = json.dumps(data)
        logger.flush(state, self.orders, self.conversions, self.traderData)
        return self.orders, self.conversions, self.traderData