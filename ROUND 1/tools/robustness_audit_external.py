import os
import sys
import json
import math
import pandas as pd
import numpy as np
import yfinance as yf
from dotenv import load_dotenv

# Path setup
script_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(script_dir, ".."))
sys.path.append(os.path.join(root_dir, "config"))
sys.path.append(os.path.join(root_dir, "traders"))

from datamodel import Listing, OrderDepth, TradingState, Observation, Order, Trade

def run_audit(trader_file, tickers=["BTC-USD", "TSLA", "SPY"]):
    print(f"--- Robustness Audit for {os.path.basename(trader_file)} ---")
    
    # Load Trader
    import importlib.util
    spec = importlib.util.spec_from_file_location("TraderModule", trader_file)
    trader_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trader_module)
    TraderClass = trader_module.Trader
    
    results = []
    
    for ticker in tickers:
        print(f"Fetching {ticker} data...")
        # Get data (prefer local cache if fresh, otherwise fetch)
        csv_path = os.path.join(root_dir, "data", "external", "processed", f"{ticker}.csv")
        
        try:
            # Check if cache exists and is relatively new
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
            else:
                data = yf.download(ticker, period="5d", interval="5m", progress=False)
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = [col[0] for col in data.columns]
                df = data.reset_index()
                df.rename(columns={'Close': 'close', 'High': 'high', 'Low': 'low', 'Volume': 'volume', 'Datetime': 'timestamp'}, inplace=True)
                os.makedirs(os.path.dirname(csv_path), exist_ok=True)
                df.to_csv(csv_path, index=False)
            
            # Implementation of the backtest loop with passive fills
            trader = TraderClass()
            trader.limits = {ticker: 80}
            listings = {ticker: Listing(ticker, ticker, "USD")}
            
            cash = 0.0
            pos = 0
            pnl_history = []
            
            # Normalize column names
            df.columns = [c.lower() for c in df.columns]
            
            # Map required columns
            col_map = {
                'close': 'close',
                'high': 'high',
                'low': 'low',
                'price': 'close' # Backup
            }
            
            # Implementation of the backtest loop with passive fills
            trader = TraderClass()
            trader.limits = {ticker: 80}
            listings = {ticker: Listing(ticker, ticker, "USD")}
            
            cash = 0.0
            pos = 0
            pnl_history = []
            
            for i, row in df.iterrows():
                mid = float(row['close'])
                high = float(row.get('high', mid + 1))
                low = float(row.get('low', mid - 1))
                
                # Synthetic Book
                depth = OrderDepth()
                spread = max(1.0, (high - low) * 0.1)
                bid = math.floor(mid - spread)
                ask = math.ceil(mid + spread)
                if bid >= ask:
                    bid = math.floor(mid - 0.5)
                    ask = math.ceil(mid + 0.5)
                
                depth.buy_orders[bid] = 100
                depth.sell_orders[ask] = -100
                
                # Synthetic market trade for passive fills
                mkt_trades = []
                if np.random.rand() < 0.3:
                    side = 1 if np.random.rand() > 0.5 else -1
                    t_price = mid + side * (spread * 0.5)
                    mkt_trades = [Trade(ticker, int(t_price), 15, (None, side > 0), None, i)]

                state = TradingState(
                    traderData=getattr(trader, 'state_data', ""),
                    timestamp=i,
                    listings=listings,
                    order_depths={ticker: depth},
                    own_trades={},
                    market_trades={ticker: mkt_trades},
                    position={ticker: pos},
                    observations=Observation({}, {})
                )
                
                orders, _, trader_data = trader.run(state)
                trader.state_data = trader_data
                
                if ticker in orders:
                    for order in orders[ticker]:
                        qty = order.quantity
                        if qty > 0: # Buy
                            if order.price >= ask: # Aggressive
                                fill = min(qty, 100, 80 - pos)
                                pos += fill
                                cash -= fill * ask
                                qty -= fill
                            if qty > 0 and mkt_trades and mkt_trades[0].quantity > 0 and not mkt_trades[0].buyer: # Mkt selling
                                if order.price >= mkt_trades[0].price:
                                    fill = min(qty, mkt_trades[0].quantity, 80 - pos)
                                    pos += fill
                                    cash -= fill * order.price
                        elif qty < 0: # Sell
                            if order.price <= bid: # Aggressive
                                fill = min(abs(qty), 100, pos + 80)
                                pos -= fill
                                cash += fill * bid
                                qty += fill
                            if qty < 0 and mkt_trades and mkt_trades[0].quantity > 0 and mkt_trades[0].buyer: # Mkt buying
                                if order.price <= mkt_trades[0].price:
                                    fill = min(abs(qty), mkt_trades[0].quantity, pos + 80)
                                    pos -= fill
                                    cash += fill * order.price
                
                mtm = cash + pos * mid
                pnl_history.append(mtm)
            
            final_pnl = pnl_history[-1]
            results.append({"ticker": ticker, "final_pnl": final_pnl})
            print(f"  {ticker}: ${final_pnl:,.2f}")
            
        except Exception as e:
            print(f"  {ticker} failed: {e}")
            
    # Save combined results
    results_dir = os.path.join(root_dir, "results")
    os.makedirs(results_dir, exist_ok=True)
    out_file = os.path.join(results_dir, os.path.basename(trader_file).replace(".py", "_robustness_results.json"))
    with open(out_file, "w") as f:
        json.dump(results, f)
    print(f"Results saved to {os.path.basename(out_file)} in results/")

if __name__ == "__main__":
    t_file = sys.argv[1] if len(sys.argv) > 1 else "ROUND 1/traders/trader_robust_v3.py"
    run_audit(t_file)
