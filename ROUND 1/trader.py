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
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        # We truncate state.traderData, trader_data, and self.logs to the same max. length to fit the log limit
        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

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
        self.traderData = "SAMPLE"
        
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
            "target_spread": 2,
            "mr_threshold": 2
        }

    def load_config(self):
        try:
            with open('config.json', 'r') as f:
                self.config = json.load(f)
        except Exception as e:
            # Fallback defaults if dashboard fails / hasn't run
            pass

    def send_sell_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, price, amount))
        if msg is not None:
            logger.print(msg)

    def send_buy_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, price, amount))
        if msg is not None:
            logger.print(msg)

    def reset_orders(self, state):
        self.orders = {}
        self.conversions = 0

        self.emeralds_position = state.position.get('EMERALDS', 0)
        self.tomatoes_position = state.position.get('TOMATOES', 0)
        
        self.emeralds_buy_orders = 0
        self.emeralds_sell_orders = 0
        self.tomatoes_buy_orders = 0
        self.tomatoes_sell_orders = 0

        for product in state.order_depths:
            self.orders[product] = []

    def trade_emeralds(self, state):
        # The Emerald Rule: Mean Reversion around fixed fair value of 10,000
        if not self.config.get("emerald_active", True):
            return
            
        limit = self.config.get("emerald_limit", 20)
        if limit == 0:
            return

        fair_value = 10000
        threshold = self.config.get("mr_threshold", 2)
        spread = self.config.get("target_spread", 2)
        
        # We buy if ask <= fair_value - threshold or simply if there's a good price.
        # But we also market make around the fair value.
        buy_price = fair_value - spread
        sell_price = fair_value + spread
        
        # Inventory Skewing
        if self.emeralds_position >= limit - 2:
            buy_price -= 3
            sell_price -= 1
        elif self.emeralds_position <= -limit + 2:
            buy_price += 1
            sell_price += 3

        max_buy = limit - self.emeralds_position
        max_sell = limit + self.emeralds_position
        
        order_depth = state.order_depths.get('EMERALDS')
        if not order_depth:
            return
            
        if len(order_depth.sell_orders) != 0:
            for ask, amount in order_depth.sell_orders.items():
                if ask <= fair_value - threshold:
                    size = min(max_buy, -amount)
                    if size > 0:
                        self.send_buy_order('EMERALDS', ask, size, f"EMERALD MR BUY: {size} @ {ask}")
                        self.emeralds_position += size
                        max_buy -= size
                        
        if len(order_depth.buy_orders) != 0:
            for bid, amount in order_depth.buy_orders.items():
                if bid >= fair_value + threshold:
                    size = min(max_sell, amount)
                    if size > 0:
                        self.send_sell_order('EMERALDS', bid, -size, f"EMERALD MR SELL: {-size} @ {bid}")
                        self.emeralds_position -= size
                        max_sell -= size

        # Rest as market maker orders
        if max_buy > 0:
            self.send_buy_order('EMERALDS', buy_price, max_buy, f"EMERALD MM BUY: {max_buy} @ {buy_price}")
        if max_sell > 0:
            self.send_sell_order('EMERALDS', sell_price, -max_sell, f"EMERALD MM SELL: {-max_sell} @ {sell_price}")

    def trade_tomatoes(self, state):
        # The Tomato Trap: Market Making / Trend Following. 
        # Volatile asset. Don't hold overnight.
        if not self.config.get("tomato_active", True):
            return
            
        limit = self.config.get("tomato_limit", 20)
        if limit == 0:
            return

        order_depth = state.order_depths.get('TOMATOES')
        if not order_depth:
            return # empty book check
            
        # Empty book check
        if len(order_depth.sell_orders) == 0 or len(order_depth.buy_orders) == 0:
            return
            
        best_ask = min(order_depth.sell_orders.keys())
        best_bid = max(order_depth.buy_orders.keys())
        
        mid_price = (best_ask + best_bid) / 2.0
        
        spread = self.config.get("target_spread", 2)
        buy_price = math.floor(mid_price) - spread
        sell_price = math.ceil(mid_price) + spread
        
        # Position safety / skewing
        max_buy = limit - self.tomatoes_position
        max_sell = limit + self.tomatoes_position
        
        if self.tomatoes_position >= limit - 2:
            buy_price -= 3
            sell_price -= 1
        elif self.tomatoes_position <= -limit + 2:
            buy_price += 1
            sell_price += 3

        # We don't take existing orders, we just market make with a wider spread
        if max_buy > 0:
            self.send_buy_order('TOMATOES', buy_price, max_buy, f"TOMATOES MM BUY: {max_buy} @ {buy_price}")
        if max_sell > 0:
            self.send_sell_order('TOMATOES', sell_price, -max_sell, f"TOMATOES MM SELL: {-max_sell} @ {sell_price}")

    def run(self, state: TradingState):        
        # 1. Load the settings
        self.load_config()
        
        # 2. Reset tracking
        self.reset_orders(state)

        # 3. Trade logic
        if 'EMERALDS' in state.order_depths:
            self.trade_emeralds(state)
        
        if 'TOMATOES' in state.order_depths:
            self.trade_tomatoes(state)

        logger.flush(state, self.orders, self.conversions, self.traderData)
        return self.orders, self.conversions, self.traderData