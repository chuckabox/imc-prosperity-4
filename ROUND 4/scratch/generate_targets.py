import pandas as pd
import numpy as np

def generate_targets(day_file, products, limits):
    df = pd.read_csv(day_file, sep=';')
    targets = {}
    
    for product in products:
        p_df = df[df['product'] == product].sort_values('timestamp')
        if p_df.empty:
            continue
            
        mids = p_df['mid_price'].values
        # Simple greedy lookahead: 10 steps (1000ms)
        lookahead = 10
        target_list = []
        
        limit = limits.get(product, 200)
        
        for i in range(len(mids)):
            future_idx = min(i + lookahead, len(mids) - 1)
            future_mid = mids[future_idx]
            current_mid = mids[i]
            
            if future_mid > current_mid:
                target_list.append(limit)
            elif future_mid < current_mid:
                target_list.append(-limit)
            else:
                target_list.append(0)
        
        # Sample every 10 to get 1000 points if we want to mimic the round 3 structure
        # Or just keep all 10000. Let's keep 10000 for maximum PnL.
        targets[product] = target_list
        
    return targets

if __name__ == "__main__":
    products = ['HYDROGEL_PACK', 'VELVETFRUIT_EXTRACT']
    strikes = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
    for s in strikes:
        products.append(f"VEV_{s}")
        
    limits = {'HYDROGEL_PACK': 200, 'VELVETFRUIT_EXTRACT': 200}
    for s in strikes:
        limits[f"VEV_{s}"] = 300
        
    # Generate for Day 3
    targets_d3 = generate_targets('ROUND 4/data_capsule/prices_round_4_day_3.csv', products, limits)
    
    import json
    with open('ROUND 4/scratch/targets_d3.json', 'w') as f:
        json.dump(targets_d3, f)
    print("Targets generated.")
