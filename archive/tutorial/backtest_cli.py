import sys
import os
import pandas as pd
import json
import math
import numpy as np

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from datamodel import Listing, OrderDepth, TradingState, Observation, Order
from trader import Trader

def run_cli_backtest(day):
    data_dir = os.path.join(os.path.dirname(__file__), "data_capsule")
    prices_file = os.path.join(data_dir, f"prices_round_0_day_{day}.csv")
    trades_file = os.path.join(data_dir, f"trades_round_0_day_{day}.csv")
    
    if not os.path.exists(prices_file):
        print(f"Error: Could not find {prices_file}")
        return

    print(f"--- Starting Backtest for Day {day} ---")
    df_prices = pd.read_csv(prices_file, sep=";")
    df_trades = pd.read_csv(trades_file, sep=";") if os.path.exists(trades_file) else None
    
    trader = Trader()
    listings = {
        "EMERALDS": Listing("EMERALDS", "EMERALDS", "SEASHELLS"),
        "TOMATOES": Listing("TOMATOES", "TOMATOES", "SEASHELLS")
    }
    
    positions = {"EMERALDS": 0, "TOMATOES": 0}
    cash = 0.0
    pnl_history = []
    
    grouped = df_prices.groupby("timestamp")
    
    for ts, group in grouped:
        order_depths = {}
        for _, row in group.iterrows():
            product = row["product"]
            depth = OrderDepth()
            depth.buy_orders = {int(row["bid_price_1"]): 10}
            depth.sell_orders = {int(row["ask_price_1"]): -10}
            order_depths[product] = depth
            
        state = TradingState(
            traderData=trader.traderData,
            timestamp=ts,
            listings=listings,
            order_depths=order_depths,
            own_trades={},
            market_trades={},
            position=positions,
            observations=Observation({}, {})
        )
        
        orders, conversions, trader_data = trader.run(state)
        trader.traderData = trader_data
        
        for product, order_list in orders.items():
            if product not in group["product"].values: continue
            row = group[group["product"] == product].iloc[0]
            curr_ask = row["ask_price_1"]
            curr_bid = row["bid_price_1"]
            
            # --- Fill Logic ---
            for order in order_list:
                qty = order.quantity
                price = order.price
                
                # A. Aggressive (Market Taking)
                if qty > 0 and price >= curr_ask:
                    fill_qty = min(qty, 20 - positions[product])
                    if fill_qty > 0:
                        positions[product] += fill_qty
                        cash -= fill_qty * curr_ask
                elif qty < 0 and price <= curr_bid:
                    fill_qty = min(-qty, positions[product] + 20)
                    if fill_qty > 0:
                        positions[product] -= fill_qty
                        cash += fill_qty * curr_bid
                
                # B. Passive (Market Making) - Use market trades
                elif df_trades is not None:
                    mkt_trades = df_trades[(df_trades["timestamp"] == ts) & (df_trades["product"] == product)]
                    for _, trade in mkt_trades.iterrows():
                        trade_price = int(trade["price"])
                        trade_qty = 1 # Default since missing from CSV
                        
                        if qty > 0 and price >= trade_price:
                            # Someone sold to us
                            fill_qty = min(qty, 20 - positions[product], trade_qty)
                            if fill_qty > 0:
                                positions[product] += fill_qty
                                cash -= fill_qty * price
                        elif qty < 0 and price <= trade_price:
                            # Someone bought from us
                            fill_qty = min(-qty, positions[product] + 20, trade_qty)
                            if fill_qty > 0:
                                positions[product] -= fill_qty
                                cash += fill_qty * price
        
        mtm_pnl = cash
        for product, pos in positions.items():
            if product in group["product"].values:
                mid = (group[group["product"] == product].iloc[0]["bid_price_1"] + group[group["product"] == product].iloc[0]["ask_price_1"]) / 2.0
                mtm_pnl += pos * mid
        pnl_history.append(mtm_pnl)

    final_pnl = pnl_history[-1] if pnl_history else 0
    print(f"Final PnL: ${final_pnl:,.2f}")
    print(f"Final Positions: {positions}")
    print("---------------------------------------")

if __name__ == "__main__":
    run_cli_backtest(-1)
    run_cli_backtest(-2)
