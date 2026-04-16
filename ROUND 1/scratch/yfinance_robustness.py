import yfinance as yf
import pandas as pd
import json
import math
import sys
import os

sys.path.append("ROUND 1/config")
from datamodel import OrderDepth, TradingState, Observation, Listing

# Import trader
sys.path.append("ROUND 1/traders")
import importlib.util
spec = importlib.util.spec_from_file_location("TraderModule", "ROUND 1/traders/trader_robust.py")
trader_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trader_module)
Trader = trader_module.Trader

tickers = ["BTC-USD", "TSLA"]

def run_external_backtest(ticker):
    print(f"\\nFetching {ticker} via yfinance...")
    data = yf.download(ticker, period="5d", interval="5m", progress=False)
    if data.empty:
        print(f"No data for {ticker}")
        return
    
    # Flatten MultiIndex columns if present
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [col[0] for col in data.columns]
        
    df = data.dropna().copy()
    
    # Save cache for the dashboard
    os.makedirs("ROUND 1/data/external/processed", exist_ok=True)
    df_cache = df.copy()
    df_cache.index.name = "timestamp"
    df_cache.rename(columns={'Close': 'close', 'Volume': 'volume'}, inplace=True)
    df_cache.to_csv(f"ROUND 1/data/external/processed/{ticker}.csv")
    
    trader = Trader()
    # Mock limits for external assets
    trader.limits = {ticker: 80}
    listings = {ticker: Listing(ticker, ticker, "USD")}
    
    cash = 0.0
    pos = 0
    pnl_history = []
    
    for i in range(len(df)):
        row = df.iloc[i]
        ts = i
        
        c = float(row['Close'])
        h = float(row['High'])
        l = float(row['Low'])
        
        # Synthetic Order Book
        depth = OrderDepth()
        # Assume tight spread around close
        spread = max(1.0, (h - l) * 0.1)
        bid = math.floor(c - spread)
        ask = math.ceil(c + spread)
        
        # Avoid 0 spread
        if bid >= ask:
            bid = math.floor(c - 1.0)
            ask = math.ceil(c + 1.0)
            
        depth.buy_orders[bid] = 100
        depth.sell_orders[ask] = -100
        
        state = TradingState(
            traderData=json.dumps(trader.emas) if trader.emas else "",
            timestamp=ts,
            listings=listings,
            order_depths={ticker: depth},
            own_trades={},
            market_trades={},
            position={ticker: pos},
            observations=Observation({}, {})
        )
        
        orders, _, trader_data = trader.run(state)
        if trader_data:
            trader.emas = json.loads(trader_data)
            
        if ticker in orders:
            for order in orders[ticker]:
                qty = order.quantity
                price = order.price
                
                if qty > 0 and price >= ask:
                    fill = min(qty, -depth.sell_orders[ask], 80 - pos)
                    if fill > 0:
                        pos += fill
                        cash -= fill * ask
                elif qty < 0 and price <= bid:
                    fill = min(-qty, depth.buy_orders[bid], pos + 80)
                    if fill > 0:
                        pos -= fill
                        cash += fill * bid
                        
        mtm = cash + pos * ((bid + ask) / 2.0)
        pnl_history.append(mtm)
        
    final_pnl = pnl_history[-1] if pnl_history else 0
    print(f"External Validation ({ticker}) -> Final PnL: ${final_pnl:,.2f} | Final Pos: {pos}")

for t in tickers:
    try:
        run_external_backtest(t)
    except Exception as e:
        print(f"Error testing {t}: {e}")

