import os
import sys
import json
import pandas as pd
import numpy as np
from datamodel import Listing, OrderDepth, TradingState, Observation, Order

# Path setup
script_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(script_dir, ".."))
sys.path.append(os.path.join(root_dir, "config"))
sys.path.append(os.path.join(root_dir, "traders"))

# Import the backtest logic from dashboard (mocking required parts or using standard execution)
def execute_historical_backtest(trader_path):
    print(f"--- Historical Audit for {os.path.basename(trader_path)} ---")
    
    # Dynamic Import
    import importlib.util
    spec = importlib.util.spec_from_file_location("trader_audit", trader_path)
    trader_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trader_mod)
    trader = trader_mod.Trader()

    data_dir = os.path.join(root_dir, "data_capsule")
    days = [-2, -1, 0]
    total_pnl = 0
    daily_results = {}

    for day in days:
        price_file = os.path.join(data_dir, f"prices_round_1_day_{day}.csv")
        if not os.path.exists(price_file): continue
        
        df = pd.read_csv(price_file, sep=";")
        df = df.sort_values("timestamp")
        
        cash = 0
        position = {"ASH_COATED_OSMIUM": 0, "INTARIAN_PEPPER_ROOT": 0}
        trader_state_data = ""
        
        listings = {
            "ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "XIRECS"),
            "INTARIAN_PEPPER_ROOT": Listing("INTARIAN_PEPPER_ROOT", "INTARIAN_PEPPER_ROOT", "XIRECS")
        }

        # Simple Backtest Loop
        for ts, group in df.groupby("timestamp"):
            order_depths = {}
            for _, row in group.iterrows():
                p = row['product']
                depth = OrderDepth()
                for i in range(1, 4):
                    if not pd.isna(row[f'bid_price_{i}']): depth.buy_orders[int(row[f'bid_price_{i}'])] = int(row[f'bid_volume_{i}'])
                    if not pd.isna(row[f'ask_price_{i}']): depth.sell_orders[int(row[f'ask_price_{i}'])] = -int(row[f'ask_volume_{i}'])
                order_depths[p] = depth
            
            state = TradingState(
                timestamp=ts,
                traderData=trader_state_data,
                market_trades={},
                order_depths=order_depths,
                position=position,
                own_trades={},
                listings=listings,
                observations=Observation({}, {})
            )
            
            orders, _, trader_data = trader.run(state)
            trader_state_data = trader_data
            
            # Simple match-at-mid logic for historical "actual" estimation
            for p, order_list in orders.items():
                if p not in order_depths: continue
                for o in order_list:
                    # Fill if price crosses best opposite
                    if o.quantity > 0: # Buy
                        best_ask = min(order_depths[p].sell_orders.keys())
                        if o.price >= best_ask:
                            fill = min(o.quantity, abs(order_depths[p].sell_orders[best_ask]), 80 - position[p])
                            position[p] += fill
                            cash -= fill * best_ask
                    else: # Sell
                        best_bid = max(order_depths[p].buy_orders.keys())
                        if o.price <= best_bid:
                            fill = min(abs(o.quantity), order_depths[p].buy_orders[best_bid], position[p] + 80)
                            position[p] -= fill
                            cash += fill * best_bid
            
        # End of day MTM
        day_pnl = cash
        for p in position:
            last_mid = (max(order_depths[p].buy_orders.keys()) + min(order_depths[p].sell_orders.keys())) / 2
            day_pnl += position[p] * last_mid
            
        print(f"  Day {day}: ${day_pnl:,.2f}")
        total_pnl += day_pnl
    
    results_dir = os.path.join(root_dir, "results")
    os.makedirs(results_dir, exist_ok=True)
    out_file = os.path.join(results_dir, os.path.basename(trader_path).replace(".py", "_historical_results.json"))
    with open(out_file, "w") as f:
        json.dump({"total_pnl": total_pnl}, f)
    print(f"Historical Audit Finish: ${total_pnl:,.2f}")

if __name__ == "__main__":
    t_dir = os.path.join(root_dir, "traders")
    for f in os.listdir(t_dir):
        if f.endswith(".py"):
            execute_historical_backtest(os.path.join(t_dir, f))
