import pandas as pd
import numpy as np

def analyze_window(day, start_ts, end_ts):
    df = pd.read_csv(f'ROUND 4/data_capsule/prices_round_4_day_{day}.csv', sep=';')
    window = df[(df['timestamp'] >= start_ts) & (df['timestamp'] <= end_ts)]
    pivot_df = window.pivot(index='timestamp', columns='product', values='mid_price')
    
    if 'HYDROGEL_PACK' in pivot_df.columns and 'VELVETFRUIT_EXTRACT' in pivot_df.columns:
        pivot_df['spread'] = pivot_df['HYDROGEL_PACK'] - pivot_df['VELVETFRUIT_EXTRACT']
        print(f"Window Day {day} [{start_ts}-{end_ts}] Spread Stats:")
        print(pivot_df['spread'].describe())
        
        # Check for profit potential
        # If we trade +/- 1 std dev from mean
        mean = pivot_df['spread'].mean()
        std = pivot_df['spread'].std()
        print(f"Mean: {mean:.2f}, Std: {std:.2f}")

analyze_window(3, 0, 100000)
