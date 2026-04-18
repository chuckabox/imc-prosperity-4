from dataclasses import dataclass
from typing import Dict, List

Symbol = str


@dataclass
class Listing:
    symbol: str
    product: str
    denomination: str


@dataclass
class Order:
    symbol: Symbol
    price: int
    quantity: int


class OrderDepth:
    def __init__(self):
        self.buy_orders: Dict[int, int] = {}
        self.sell_orders: Dict[int, int] = {}


@dataclass
class Observation:
    plainValueObservations: Dict
    conversionObservations: Dict


@dataclass
class TradingState:
    traderData: str
    timestamp: int
    listings: Dict[str, Listing]
    order_depths: Dict[str, OrderDepth]
    own_trades: Dict[str, List]
    market_trades: Dict[str, List]
    position: Dict[str, int]
    observations: Observation
