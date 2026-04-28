import pandas as pd
import numpy as np

def calculate_delta(day):
    df = pd.read_csv(f'ROUND 4/data_capsule/prices_round_4_day_{day}.csv', sep=';')
    pivot_df = df.pivot(index='timestamp', columns='product', values='mid_price')
    
    if 'VELVETFRUIT_EXTRACT' in pivot_df.columns:
        underlying = pivot_df['VELVETFRUIT_EXTRACT']
        for col in pivot_df.columns:
            if col.startswith('VEV_'):
                # Calculate correlation with underlying changes
                delta_u = underlying.diff()
                delta_o = pivot_df[col].diff()
                
                # Filter out NaNs
                mask = ~delta_u.isna() & ~delta_o.isna()
                if mask.any():
                    # Simple linear regression slope (delta)
                    slope = np.polyfit(delta_u[mask], delta_o[mask], 1)[0]
                    print(f"Day {day} - {col} Delta: {slope:.4f}")

calculate_delta(1)
calculate_delta(2)
calculate_delta(3)
