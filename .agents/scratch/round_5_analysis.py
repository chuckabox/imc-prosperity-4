import json
import pandas as pd
import numpy as np
import os
import glob
from io import StringIO

def parse_live_log(file_path):
    with open(file_path, 'r') as f:
        data = json.load(f)
    
    csv_content = data.get('activitiesLog', '')
    if not csv_content:
        return pd.DataFrame()
    
    df = pd.read_csv(StringIO(csv_content), sep=';')
    return df

def analyze_performance(df, name):
    if df.empty:
        return f"No data for {name}"
    
    # Aggregate PnL across all products at each timestamp
    # Note: timestamps might be repeated for different products
    pnl_curve = df.groupby('timestamp')['profit_and_loss'].sum()
    
    final_pnl = pnl_curve.iloc[-1]
    peak = pnl_curve.cummax()
    drawdown = peak - pnl_curve
    max_drawdown = drawdown.max()
    
    # Calculate returns (approximate since we don't have capital, use PnL diff)
    pnl_diff = pnl_curve.diff().dropna()
    sharpe = (pnl_diff.mean() / pnl_diff.std() * np.sqrt(1000000 / 100)) if pnl_diff.std() != 0 else 0 # Assuming 100 tick steps
    
    return {
        "Name": name,
        "Final PnL": final_pnl,
        "Max Drawdown": max_drawdown,
        "Sharpe Ratio": sharpe,
        "Entries": len(df)
    }

def analyze_market_data(capsule_path):
    prices_files = glob.glob(os.path.join(capsule_path, "prices_round_5_day_*.csv"))
    market_stats = []
    
    for f in prices_files:
        day = f.split('_')[-1].replace('.csv', '')
        df = pd.read_csv(f, sep=';')
        
        for product in df['product'].unique():
            pdf = df[df['product'] == product]
            mid = pdf['mid_price']
            volatility = mid.pct_change().std() * np.sqrt(pdf.shape[0])
            avg_spread = (pdf['ask_price_1'] - pdf['bid_price_1']).mean()
            
            market_stats.append({
                "Day": day,
                "Product": product,
                "Volatility": volatility,
                "Avg Spread": avg_spread,
                "Max Price": mid.max(),
                "Min Price": mid.min()
            })
    
    return pd.DataFrame(market_stats)

def main():
    log_dirs = [
        "/home/suvin/Desktop/GitHub/imc-prosperity-4/ROUND 5/live_logs/MATH1052/MATH1052.log",
        "/home/suvin/Desktop/GitHub/imc-prosperity-4/ROUND 5/live_logs/MATH1061/MATH1061.log",
        "/home/suvin/Desktop/GitHub/imc-prosperity-4/ROUND 5/live_logs/pot/pot.log"
    ]
    
    perf_summaries = []
    for log_path in log_dirs:
        if os.path.exists(log_path):
            name = os.path.basename(os.path.dirname(log_path))
            df = parse_live_log(log_path)
            perf_summaries.append(analyze_performance(df, name))
    
    print("--- PERFORMANCE ANALYSIS ---")
    print(pd.DataFrame(perf_summaries).to_string())
    
    print("\n--- MARKET DATA ANALYSIS ---")
    market_df = analyze_market_data("/home/suvin/Desktop/GitHub/imc-prosperity-4/ROUND 5/data_capsule")
    # Group by product to see overall characteristics
    summary = market_df.groupby('Product').agg({
        'Volatility': 'mean',
        'Avg Spread': 'mean'
    }).reset_index()
    print(summary.to_string())

if __name__ == "__main__":
    main()
