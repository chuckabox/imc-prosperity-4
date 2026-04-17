import sys
import os
from pathlib import Path

# Add config to path for datamodel
sys.path.append(str(Path(os.getcwd()) / "ROUND 1" / "config"))
from datamodel import Listing, OrderDepth, TradingState, Observation

# Import trader
sys.path.append(str(Path(os.getcwd()) / "ROUND 1" / "traders" / "peter"))
from trader_peter_v10 import Trader

def test():
    trader = Trader()
    
    # Tick 1
    depth = OrderDepth()
    depth.buy_orders = {100: 10, 99: 10}
    depth.sell_orders = {102: 10, 103: 10}
    
    state = TradingState(
        traderData="",
        timestamp=100,
        listings={"ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "SEASHELLS")},
        order_depths={"ASH_COATED_OSMIUM": depth},
        own_trades={},
        market_trades={},
        position={},
        observations=Observation({}, {})
    )
    
    orders, _, data = trader.run(state)
    print(f"Tick 1 Orders: {orders}")
    
    # Tick 2 - Price moves up
    depth2 = OrderDepth()
    depth2.buy_orders = {105: 10, 104: 10}
    depth2.sell_orders = {107: 10, 108: 10}
    
    state2 = TradingState(
        traderData=data,
        timestamp=200,
        listings={"ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "SEASHELLS")},
        order_depths={"ASH_COATED_OSMIUM": depth2},
        own_trades={},
        market_trades={},
        position={},
        observations=Observation({}, {})
    )
    
    orders2, _, data2 = trader.run(state2)
    print(f"Tick 2 Orders: {orders2}")

if __name__ == "__main__":
    test()
