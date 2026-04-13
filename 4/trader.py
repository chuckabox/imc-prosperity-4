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
            return history[-1][1], 0.0
            
        times = np.array([pt[0] for pt in history]) - history[0][0]
        values = np.array([pt[1] for pt in history])
        
        # 2nd order polynomial fit: p(t) = at^2 + bt + c
        # Drift (velocity) is p'(t) = 2at + b
        try:
            poly = np.polyfit(times, values, 2)
            current_t = current_time - history[0][0]
            
            fair_val = np.polyval(poly, current_t)
            drift = 2 * poly[0] * current_t + poly[1]
            
            return fair_val, drift
        except:
            return history[-1][1], 0.0

    def trade_emeralds(self, state, fair_value_estimate, drift):
        if not self.config.get("emerald_active", True): return
        limit = self.config.get("emerald_limit", 20)
        
        # Emeralds are theoretically pegged to 10k, 
        # but our estimate might suggest a local deviation.
        # We blend the anchor (10k) with our fitted curve.
        fair_value = (0.8 * 10000) + (0.2 * fair_value_estimate)
        
        threshold = self.config.get("mr_threshold", 1.5)
        spread = self.config.get("target_spread", 1)
        
        buy_price = fair_value - spread - (drift * 0.1)
        sell_price = fair_value + spread - (drift * 0.1)
        
        # Apply strict integer rounding for exchange
        buy_price = math.floor(buy_price)
        sell_price = math.ceil(sell_price)

        max_buy = limit - self.emeralds_position
        max_sell = limit + self.emeralds_position
        
        order_depth = state.order_depths.get('EMERALDS')
        if not order_depth: return
            
        # 1. Take aggressive orders
        sorted_asks = sorted(order_depth.sell_orders.items())
        for ask, amount in sorted_asks:
            if ask <= fair_value - threshold and max_buy > 0:
                size = min(max_buy, -amount)
                self.send_buy_order('EMERALDS', ask, size, f"EMERALD AGG BUY: {size}@{ask} (Fair:{fair_value:.1f})")
                self.emeralds_position += size
                max_buy -= size
        
        sorted_bids = sorted(order_depth.buy_orders.items(), reverse=True)
        for bid, amount in sorted_bids:
            if bid >= fair_value + threshold and max_sell > 0:
                size = min(max_sell, amount)
                self.send_sell_order('EMERALDS', bid, -size, f"EMERALD AGG SELL: {size}@{bid} (Fair:{fair_value:.1f})")
                self.emeralds_position -= size
                max_sell -= size

        # 2. Market Make residual
        if max_buy > 0:
            self.send_buy_order('EMERALDS', buy_price, max_buy)
        if max_sell > 0:
            self.send_sell_order('EMERALDS', sell_price, -max_sell)

    def trade_tomatoes(self, state, fair_value, drift):
        if not self.config.get("tomato_active", True): return
        limit = self.config.get("tomato_limit", 20)
        
        spread = self.config.get("target_spread", 2)
        
        # Use drift to adjust prices: if drifting up, don't sell too cheap!
        # Adjusting the mid-point based on predicted momentum
        adjusted_mid = fair_value + (drift * 0.5)
        
        buy_price = math.floor(adjusted_mid - spread)
        sell_price = math.ceil(adjusted_mid + spread)
        
        # Inventory Skewing: discourage building huge positions
        if self.tomatoes_position > 10:
            buy_price -= 1
        elif self.tomatoes_position < -10:
            sell_price += 1

        max_buy = limit - self.tomatoes_position
        max_sell = limit + self.tomatoes_position
        
        if max_buy > 0:
            self.send_buy_order('TOMATOES', buy_price, max_buy)
        if max_sell > 0:
            self.send_sell_order('TOMATOES', sell_price, -max_sell)

    def run(self, state: TradingState):
        self.load_config()
        self.reset_orders(state)
        
        # Parse persistence
        data = {}
        if state.traderData:
            try:
                data = json.loads(state.traderData)
            except:
                pass
        
        if "history" not in data:
            data["history"] = {}
            
        # Process each product
        for product in ['EMERALDS', 'TOMATOES']:
            if product not in state.order_depths: continue
            
            depth = state.order_depths[product]
            if not depth.buy_orders or not depth.sell_orders: continue
            
            mid = (max(depth.buy_orders.keys()) + min(depth.sell_orders.keys())) / 2.0
            
            if product not in data["history"]:
                data["history"][product] = []
                
            data["history"][product].append([state.timestamp, mid])
            
            # Keep window size
            win = self.config.get("window_size", 30)
            if len(data["history"][product]) > win:
                data["history"][product] = data["history"][product][-win:]
            
            # Fit and Trade
            fair_val, drift = self.get_fair_price_and_drift(data["history"][product], state.timestamp)
            
            if product == 'EMERALDS':
                self.trade_emeralds(state, fair_val, drift)
            elif product == 'TOMATOES':
                self.trade_tomatoes(state, fair_val, drift)

        self.traderData = json.dumps(data)
        logger.flush(state, self.orders, self.conversions, self.traderData)
        return self.orders, self.conversions, self.traderData