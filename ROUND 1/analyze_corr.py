import pandas as pd
import numpy as np

def analyze_correlation(day):
    price_file = f"ROUND 1/data_capsule/prices_round_1_day_{day}.csv"
    df = pd.read_csv(price_file, sep=';')
    
    # Pivot to get products as columns
    pivoted = df.pivot(index='timestamp', columns='product', values='mid_price')
    pivoted = pivoted.dropna()
    
    corr = pivoted.corr()
    return corr

days = [-2, -1, 0]
for d in days:
    print(f"Day {d} Correlation:")
    print(analyze_correlation(d))
