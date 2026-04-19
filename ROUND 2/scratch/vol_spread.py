import pandas as pd
import numpy as np
import glob

def analyze_vol_spread():
    files = sorted(glob.glob("ROUND 2/data_capsule/prices_round_2_day_*.csv"))
    if not files:
        print("No files found.")
        return

    for fpath in files:
        print(f"\nEvaluating: {fpath}")
        df = pd.read_csv(fpath, sep=";")
        prod = 'ASH_COATED_OSMIUM'
        pdf = df[df['product'] == prod].copy()
        
        pdf['mid'] = (pdf['bid_price_1'] + pdf['ask_price_1']) / 2
        pdf['spread'] = pdf['ask_price_1'] - pdf['bid_price_1']
        
        # Volatility over 20 ticks
        pdf['vol'] = pdf['mid'].rolling(20).std()
        
        # Future profitability of a wider spread?
        # This is harder to measure from prices alone without a full sim.
        # But we can look at how spread behaves with vol.
        print(f"Correlation (Vol, Spread): {pdf['vol'].corr(pdf['spread']):.4f}")
        
        # If vol is high, does the spread tend to widen vertically immediately after?
        pdf['next_spread'] = pdf['spread'].shift(-5)
        print(f"Correlation (Vol, Next Spread): {pdf['vol'].corr(pdf['next_spread']):.4f}")

if __name__ == "__main__":
    analyze_vol_spread()
