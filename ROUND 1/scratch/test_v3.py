
import sys
import os
# Add current dir to path
sys.path.append(os.getcwd())

# Mock datamodel
class Order:
    def __init__(self, symbol, price, quantity):
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
    def __repr__(self):
        return f"Order({self.symbol}, {self.price}, {self.quantity})"

class OrderDepth:
    def __init__(self):
        self.buy_orders = {99: 10, 98: 20}
        self.sell_orders = {101: -10, 102: -20}

class TradingState:
    def __init__(self):
        self.traderData = ""
        self.order_depths = {
            "INTARIAN_PEPPER_ROOT": OrderDepth(),
            "ASH_COATED_OSMIUM": OrderDepth()
        }
        self.position = {}
        self.market_trades = {}

# Import candidate
try:
    from ROUND_1.traders.peter.trader_robust_peter_v3 import Trader
    t = Trader()
    state = TradingState()
    res, conv, data = t.run(state)
    print("SUCCESS")
    print("Result:", res)
except Exception as e:
    print("ERROR:", e)
    import traceback
    traceback.print_exc()
