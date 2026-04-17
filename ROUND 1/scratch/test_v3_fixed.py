
import sys
import os
import importlib.util

# Mock datamodel in global namespace so the imported file can see it
class Order:
    def __init__(self, symbol, price, quantity):
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
    def __repr__(self):
        return f"Order({self.symbol}, {self.price}, {self.quantity})"

class OrderDepth:
    def __init__(self, buys, sells):
        self.buy_orders = buys
        self.sell_orders = sells

class TradingState:
    def __init__(self, depths, pos):
        self.traderData = ""
        self.order_depths = depths
        self.position = pos
        self.market_trades = {}

import datamodel
datamodel.Order = Order
datamodel.OrderDepth = OrderDepth
datamodel.TradingState = TradingState

# Import file directly
path = r"ROUND 1/traders/peter/trader_robust_peter_v3.py"
spec = importlib.util.spec_from_file_location("trader", path)
trader_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trader_mod)

t = trader_mod.Trader()
depths = {
    "INTARIAN_PEPPER_ROOT": OrderDepth({99: 10}, {101: -10}),
    "ASH_COATED_OSMIUM": OrderDepth({9999: 5}, {10001: -5})
}
state = TradingState(depths, {})
res, conv, data = t.run(state)
print("SUCCESS")
print("Result:", res)
