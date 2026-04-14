import sys
import os
import pandas as pd
import json
import math
import numpy as np

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from datamodel import Listing, OrderDepth, TradingState, Observation, Order
import importlib.util

# Load the trader class from the provided file path
trader_file = sys.argv[1] if len(sys.argv) > 1 else "ROUND 1/trader_peter.py"
spec = importlib.util.spec_from_file_location("TraderModule", trader_file)
trader_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trader_module)
Trader = trader_module.Trader

def run_cli_backtest(day):
    # Adjust paths for ROUND 1
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(root_dir, "ROUND 1", "data_capsule")
    prices_file = os.path.join(data_dir, f"prices_round_1_day_{day}.csv")
    trades_file = os.path.join(data_dir, f"trades_round_1_day_{day}.csv")
    
    if not os.path.exists(prices_file):
        print(f"Error: Could not find {prices_file}")
        return

    print(f"--- Starting Backtest for Day {day} ---")
    df_prices = pd.read_csv(prices_file, sep=";")
    
    # Pre-process depths for faster access
    trader = Trader()
    listings = {
        "ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "SEASHELLS"),
        "INTARIAN_PEPPER_ROOT": Listing("INTARIAN_PEPPER_ROOT", "INTARIAN_PEPPER_ROOT", "SEASHELLS")
    }
    
    cash = 0.0
    positions = {p: 0 for p in listings.keys()}
    pnl_history = []
    
    # Pre-group prices by timestamp
    grouped = df_prices.groupby("timestamp")
    
    # Load trades for passive fill simulation
    df_trades = pd.read_csv(trades_file, sep=";") if os.path.exists(trades_file) else None
    trades_dict = {}
    if df_trades is not None:
        # Pre-group trades by (timestamp, symbol)
        for (t, s), g in df_trades.groupby(["timestamp", "symbol"]):
            trades_dict[(t, s)] = g.to_dict("records")
    
    for i, (ts, group) in enumerate(grouped):
        order_depths = {}
        for _, row in group.iterrows():
            product = row["product"]
            depth = OrderDepth()
            if not pd.isna(row["bid_price_1"]):
                depth.buy_orders[int(row["bid_price_1"])] = int(row["bid_volume_1"])
            if not pd.isna(row["ask_price_1"]):
                depth.sell_orders[int(row["ask_price_1"])] = -int(row["ask_volume_1"])
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
            if product not in order_depths: continue
            depth = order_depths[product]
            curr_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 999999
            curr_bid = max(depth.buy_orders.keys()) if depth.buy_orders else -999999
            
            for order in order_list:
                qty = order.quantity
                price = order.price
                
                # 1. Aggressive Fill (Take)
                if qty > 0 and price >= curr_ask:
                    fill = min(qty, -depth.sell_orders[curr_ask], trader.limits.get(product, 20) - positions[product])
                    if fill > 0:
                        positions[product] += fill
                        cash -= fill * curr_ask
                        qty -= fill
                elif qty < 0 and price <= curr_bid:
                    fill = min(-qty, depth.buy_orders[curr_bid], positions[product] + trader.limits.get(product, 20))
                    if fill > 0:
                        positions[product] -= fill
                        cash += fill * curr_bid
                        qty += fill
                
                # 2. Passive Fill (Make) - If price was traded through or at
                if qty != 0:
                    mkt_trades = trades_dict.get((ts, product), [])
                    for trade in mkt_trades:
                        trade_p = trade["price"]
                        trade_v = trade["quantity"]
                        # We only fill if we are BETTER than the trade price or AT it
                        # For conservatism, we fill up to 50% of the market trade volume
                        if qty > 0 and price >= trade_p: # Buy limit hit
                            fill = min(qty, int(trade_v * 0.5) + 1, trader.limits.get(product, 20) - positions[product])
                            if fill > 0:
                                positions[product] += fill
                                cash -= fill * price
                                qty -= fill
                        elif qty < 0 and price <= trade_p: # Sell limit hit
                            fill = min(-qty, int(trade_v * 0.5) + 1, positions[product] + trader.limits.get(product, 20))
                            if fill > 0:
                                positions[product] -= fill
                                cash += fill * price
                                qty -= fill

        # Mark-to-Market PnL
        mtm_pnl = cash
        for product, pos in positions.items():
            if product in order_depths:
                depth = order_depths[product]
                best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 0
                best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 0
                mid = (best_bid + best_ask) / 2.0 if best_bid and best_ask else (best_bid or best_ask or 0)
                mtm_pnl += pos * mid
        
        pnl_history.append(mtm_pnl)
        if i < 3: 
            order_list = []
            for p in orders:
                for o in orders[p]:
                    order_list.append((p, o.price, o.quantity))
            print(f"TS {ts}: PnL ${mtm_pnl:,.2f} | Pos {positions} | Orders: {order_list}")

    # Mark-to-Market PnL
    mtm_pnl = cash
    product_pnls = {"CASH": cash}
    for product, pos in positions.items():
        if product in order_depths:
            depth = order_depths[product]
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 0
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 0
            if best_bid and best_ask:
                mid = (best_bid + best_ask) / 2.0
            elif best_bid: mid = best_bid
            elif best_ask: mid = best_ask
            else: mid = 0
            val = pos * mid
            mtm_pnl += val
            product_pnls[product] = val
        else:
            product_pnls[product] = 0
            
    pnl_history.append(mtm_pnl)

    final_pnl = pnl_history[-1] if pnl_history else 0
    print(f"Final PnL: ${final_pnl:,.2f} | {product_pnls}")
    print(f"Final Positions: {positions}")
    return final_pnl

if __name__ == "__main__":
    total = 0
    for day in [-2, -1, 0]:
        total += run_cli_backtest(day)
    print(f"Total PnL: ${total:,.2f}")
