class Order:
    def __init__(self, symbol: str, price: int, quantity: int) -> None:
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
    def __repr__(self) -> str:
        return f"Order(symbol={self.symbol}, price={self.price}, quantity={self.quantity})"

class OrderDepth:
    def __init__(self) -> None:
        self.buy_orders = {}
        self.sell_orders = {}

class TradingState:
    def __init__(self, traderData, timestamp, listings, order_depths, own_trades, market_trades, position, observations):
        self.traderData = traderData
        self.timestamp = timestamp
        self.listings = listings
        self.order_depths = order_depths
        self.own_trades = own_trades
        self.market_trades = market_trades
        self.position = position
        self.observations = observations
