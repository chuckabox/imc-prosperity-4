import pandas as pd
import numpy as np

def analyze(day):
    file_path = f"ROUND 1/data/data_capsule/prices_round_1_day_{day}.csv"
    try:
        df = pd.read_csv(file_path, sep=';')
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return

    # Pivot to have products as columns
    df_pivot = df.pivot(index='timestamp', columns='product', values='mid_price')
    
    print(f"--- Day {day} Analysis ---")
    print(df_pivot.describe())
    
    correlation = df_pivot.corr()
    print("\nCorrelation Matrix:")
    print(correlation)
    
    # Check for lead/lag
    for lag in range(1, 11):
        corr = df_pivot['ASH_COATED_OSMIUM'].corr(df_pivot['INTARIAN_PEPPER_ROOT'].shift(lag))
        print(f"Corr(Osmium, Pepper Lag {lag}): {corr:.4f}")

    for lag in range(1, 11):
        corr = df_pivot['INTARIAN_PEPPER_ROOT'].corr(df_pivot['ASH_COATED_OSMIUM'].shift(lag))
        print(f"Corr(Pepper, Osmium Lag {lag}): {corr:.4f}")

    # Check for cycles or periodicity in Osmium
    # Calculate auto-correlation
    for lag in [1, 5, 10, 50, 100]:
        auto_corr = df_pivot['ASH_COATED_OSMIUM'].autocorr(lag=lag)
        print(f"Auto-corr Osmium (Lag {lag}): {auto_corr:.4f}")

if __name__ == "__main__":
    for d in [-2, -1, 0]:
        analyze(d)
        print("\n")
