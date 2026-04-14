import pandas as pd
import numpy as np
import os

def analyze_day(day):
    price_file = f"ROUND 1/data_capsule/prices_round_1_day_{day}.csv"
    trade_file = f"ROUND 1/data_capsule/trades_round_1_day_{day}.csv"
    
    df = pd.read_csv(price_file, sep=';')
    
    results = {}
    for product in df['product'].unique():
        pdf = df[df['product'] == product].copy()
        pdf = pdf.sort_values('timestamp')
        
        mid_prices = pdf['mid_price'].values
        
        # Stats
        mean = np.mean(mid_prices)
        std = np.std(mid_prices)
        min_p = np.min(mid_prices)
        max_p = np.max(mid_prices)
        
        # Mean Reversion Check
        # Half-life of mean reversion
        avg_price = np.mean(mid_prices)
        price_diff = np.diff(mid_prices)
        prev_price = mid_prices[:-1] - avg_price
        
        # Regression: dP = -lambda * (P - mean) * dt
        # Simplified: delta_p = alpha + beta * prev_p
        if len(prev_price) > 0:
            beta = np.polyfit(prev_price, price_diff, 1)[0]
            # beta = exp(-lambda * dt) - 1
            # lambda = -ln(1 + beta) / dt
            # half_life = ln(2) / lambda
            if beta < 0:
                half_life = -np.log(2) / beta
            else:
                half_life = np.inf
        else:
            half_life = np.nan
            
        # Spread analysis
        # bid_price_1, ask_price_1
        pdf['spread'] = pdf['ask_price_1'] - pdf['bid_price_1']
        avg_spread = pdf['spread'].mean()
        
        results[product] = {
            'mean': mean,
            'std': std,
            'min': min_p,
            'max': max_p,
            'half_life': half_life,
            'avg_spread': avg_spread
        }
        
    return results

days = [-2, -1, 0]
all_results = {}
for d in days:
    all_results[d] = analyze_day(d)

# Print Summary
import json
print(json.dumps(all_results, indent=2))
