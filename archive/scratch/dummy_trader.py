from datamodel import TradingState, Order
import json

class Trader:
    LIMIT = 80
    def run(self, state: TradingState):
        orders = {}
        for product in state.order_depths:
            orders[product] = []
        return orders, 0, ""
