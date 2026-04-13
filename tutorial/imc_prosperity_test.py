from datamodel import Order, TradingState, Symbol
import math

class Trader:
    def __init__(self):
        # Configuration and Limits
        self.limits = {"EMERALDS": 20, "TOMATOES": 20}
        self.fair_values = {"EMERALDS": 10000}
        self.target_spread = 2 # How far from fair value we place our orders

    def run(self, state: TradingState):
        """
        Processes the spreadsheet data and returns orders, conversions, and traderData.
        """
        result = {}
        conversions = 0
        trader_data = "Logic: Skewed Market Making"

        for product in state.order_depths:
            order_depth = state.order_depths[product]
            orders = []
            
            # 1. Get current inventory position
            current_pos = state.position.get(product, 0)
            limit = self.limits.get(product, 20)

            # 2. Determine "Fair Value"
            # For Emeralds, use fixed 10k. For others, use the current Mid-Price.
            if product == "EMERALDS":
                acceptable_price = self.fair_values[product]
            else:
                # Calculate mid-price safely
                best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
                best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
                if best_ask and best_bid:
                    acceptable_price = (best_ask + best_bid) / 2
                else:
                    continue # Skip if the book is empty

            # 3. Inventory Skewing Logic
            # If we own too much, we lower our prices to encourage selling.
            # If we owe too much (short), we raise our prices to encourage buying.
            buy_price = math.floor(acceptable_price - self.target_spread)
            sell_price = math.ceil(acceptable_price + self.target_spread)
            
            if current_pos > 10: # We are "Long"
                buy_price -= 1
                sell_price -= 1
            elif current_pos < -10: # We are "Short"
                buy_price += 1
                sell_price += 1

            # 4. Calculate Room to Trade (Position Management)
            max_buy = limit - current_pos
            max_sell = limit + current_pos # This is the room to go "short"

            # 5. Place Market Maker Orders
            if max_buy > 0:
                orders.append(Order(product, buy_price, max_buy))
            if max_sell > 0:
                # Selling is always a negative quantity
                orders.append(Order(product, sell_price, -max_sell))

            result[product] = orders

        # IMPORTANT: Return all three required values
        return result, conversions, trader_data