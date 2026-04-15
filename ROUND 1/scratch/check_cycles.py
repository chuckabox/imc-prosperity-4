import pandas as pd
import numpy as np

def analyze_cycles(day):
    file_path = f"ROUND 1/data/data_capsule/prices_round_1_day_{day}.csv"
    try:
        df = pd.read_csv(file_path, sep=';')
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return

    osmium = df[df['product'] == 'ASH_COATED_OSMIUM']['mid_price'].dropna().values
    
    # Calculate auto-correlation for many lags to find cycles
    lags = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]
    results = {}
    for lag in lags:
        if len(osmium) > lag:
            corr = np.corrcoef(osmium[lag:], osmium[:-lag])[0, 1]
            results[lag] = corr
            
    print(f"--- Day {day} Osmium Auto-Correlation ---")
    for lag, corr in results.items():
        print(f"Lag {lag}: {corr:.4f}")

if __name__ == "__main__":
    for d in [-2, -1, 0]:
        analyze_cycles(d)
        print("\n")
