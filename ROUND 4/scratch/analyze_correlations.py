import pandas as pd
import numpy as np

def analyze_day(day):
    df = pd.read_csv(f'ROUND 4/data_capsule/prices_round_4_day_{day}.csv', sep=';')
    
    # Pivot the data to have products as columns
    pivot_df = df.pivot(index='timestamp', columns='product', values='mid_price')
    
    # Correlation matrix
    corr = pivot_df.corr()
    print(f"Correlation Matrix for Day {day}:")
    print(corr)
    
    # Check for constant spreads or ratios
    if 'VELVETFRUIT_EXTRACT' in pivot_df.columns and 'HYDROGEL_PACK' in pivot_df.columns:
        pivot_df['spread'] = pivot_df['HYDROGEL_PACK'] - pivot_df['VELVETFRUIT_EXTRACT']
        print(f"\nSpread (HYDROGEL_PACK - VELVETFRUIT_EXTRACT) stats for Day {day}:")
        print(pivot_df['spread'].describe())

analyze_day(1)
analyze_day(2)
analyze_day(3)
