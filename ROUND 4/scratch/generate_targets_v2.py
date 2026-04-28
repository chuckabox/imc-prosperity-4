import pandas as pd
import numpy as np
import json

def generate_day_targets(day_file, products, limits):
    df = pd.read_csv(day_file, sep=';')
    targets = {}
    
    # We want 1000 points per day (sampled every 10 timestamps)
    # Timestamps are 0, 100, ..., 999900 (10000 points)
    # We take indices 0, 1000, 2000, ... or index // 10
    
    for product in products:
        p_df = df[df['product'] == product].sort_values('timestamp')
        if p_df.empty:
            continue
            
        mids = p_df['mid_price'].values
        # Lookahead 10 timestamps (1000ms)
        lookahead = 10
        day_targets = []
        
        limit = limits.get(product, 200)
        
        # Calculate for all 10000 points first
        all_points = []
        for i in range(len(mids)):
            future_idx = min(i + lookahead, len(mids) - 1)
            future_mid = mids[future_idx]
            current_mid = mids[i]
            
            if future_mid > current_mid:
                all_points.append(limit)
            elif future_mid < current_mid:
                all_points.append(-limit)
            else:
                all_points.append(0)
        
        # Sample 1000 points
        sampled = [all_points[i] for i in range(0, len(all_points), 10)]
        # Ensure exactly 1000 points
        sampled = sampled[:1000]
        while len(sampled) < 1000:
            sampled.append(0)
            
        targets[product] = sampled
        
    return targets

if __name__ == "__main__":
    products = ['HYDROGEL_PACK', 'VELVETFRUIT_EXTRACT']
    strikes = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
    for s in strikes:
        products.append(f"VEV_{s}")
        
    limits = {'HYDROGEL_PACK': 200, 'VELVETFRUIT_EXTRACT': 200}
    for s in strikes:
        limits[f"VEV_{s}"] = 300
        
    all_days = {}
    for day in [1, 2, 3]:
        all_days[day] = generate_day_targets(f'ROUND 4/data_capsule/prices_round_4_day_{day}.csv', products, limits)
    
    with open('ROUND 4/scratch/targets_all_days.json', 'w') as f:
        json.dump(all_days, f)
    print("All days targets generated.")
