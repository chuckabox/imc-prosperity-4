import json
import math
from typing import Dict, List, Any
from datamodel import Order, OrderDepth, TradingState, Symbol

class Trader:
    def __init__(self):
        self.limits = {
            "ASH_COATED_OSMIUM": 80,
            "INTARIAN_PEPPER_ROOT": 80
        }

        self.sf_weights = [0.34, 0.32, 0.34]
        self.sf_intercept = 0.0

        self.history = {}

    def get_mid(self, depth: OrderDepth):
        if not depth.buy_orders or not depth.sell_orders:
            return None
        return (max(depth.buy_orders) + min(depth.sell_orders)) / 2

    def get_volatility(self, depth: OrderDepth):
        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        return max(1.0, best_ask - best_bid)

    def fair_price(self, product, state: TradingState, mid):
        tape = 0
        for t in state.market_trades.get(product, []):
            tape += t.quantity if t.price >= mid else -t.quantity

        tape_adj = max(-2.0, min(2.0, tape * 0.1))

        if product == "ASH_COATED_OSMIUM":
            depth = state.order_depths[product]
            vwap = (
                sum(depth.buy_orders.keys()) / len(depth.buy_orders)
                if depth.buy_orders else mid
            )
            return vwap + tape_adj

        hist = self.history.get(product, [])
        hist.append(mid)
        hist = hist[-3:]
        self.history[product] = hist

        if len(hist) < 3:
            return mid + tape_adj

        pred = self.sf_intercept
        for i in range(3):
            pred += self.sf_weights[i] * hist[-(i+1)]

        return pred + tape_adj

    def run(self, state: TradingState):
        result = {}

        for product, depth in state.order_depths.items():
            if product not in self.limits:
                continue

            mid = self.get_mid(depth)
            if mid is None:
                continue

            pos = state.position.get(product, 0)
            limit = self.limits[product]

            fair = self.fair_price(product, state, mid)
            vol = self.get_volatility(depth)

            bid_orders = []
            ask_orders = []

            # Signal strength filter
            edge = fair - mid
            strong = abs(edge) > max(1.5, vol * 0.3)

            # INVENTORY SKEW
            skew = pos / limit if limit else 0

            # SIZE CONTROL
            base_size = 20 if strong else 5
            buy_cap = limit - pos
            sell_cap = limit + pos

            # ------------------------
            # TAKING LOGIC (ONLY IF STRONG EDGE)
            # ------------------------
            if strong:
                for ask, qty in sorted(depth.sell_orders.items()):
                    if ask < fair - 1:
                        trade_size = min(buy_cap, -qty, base_size)
                        bid_orders.append(Order(product, ask, trade_size))
                        buy_cap -= trade_size
                        pos += trade_size

                for bid, qty in sorted(depth.buy_orders.items(), reverse=True):
                    if bid > fair + 1:
                        trade_size = min(sell_cap, qty, base_size)
                        ask_orders.append(Order(product, bid, -trade_size))
                        sell_cap -= trade_size
                        pos -= trade_size

            # ------------------------
            # MAKING LOGIC (ALWAYS ON)
            # ------------------------
            spread = vol * 0.5

            bid_price = math.floor(fair - spread - skew)
            ask_price = math.ceil(fair + spread - skew)

            bid_size = max(1, buy_cap // 2)
            ask_size = max(1, sell_cap // 2)

            # Risk throttle
            if abs(pos) > limit * 0.7:
                bid_size = int(bid_size * 0.3)
                ask_size = int(ask_size * 0.3)

            if buy_cap > 0:
                bid_orders.append(Order(product, bid_price, bid_size))

            if sell_cap > 0:
                ask_orders.append(Order(product, ask_price, -ask_size))

            result[product] = bid_orders + ask_orders

        return result, 0, json.dumps(self.history)