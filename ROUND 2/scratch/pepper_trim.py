import pandas as pd
import numpy as np
import glob

def simulate_pepper_trim():
    files = sorted(glob.glob("ROUND 2/data_capsule/prices_round_2_day_*.csv"))
    if not files:
        print("No files found.")
        return

    for fpath in files:
        print(f"\nEvaluating: {fpath}")
        df = pd.read_csv(fpath, sep=";")
        prod = 'INTARIAN_PEPPER_ROOT'
        pdf = df[df['product'] == prod].copy()
        
        pdf['mid'] = (pdf['bid_price_1'] + pdf['ask_price_1']) / 2
        
        # Calculate slope over 20 ticks
        def get_slope(x):
            if len(x) < 20: return 0
            n = len(x)
            xm = (n-1)/2.0
            ym = np.mean(x)
            num = np.sum([(i - xm) * (v - ym) for i, v in enumerate(x)])
            den = np.sum([(i - xm) ** 2 for i in range(n)])
            return num/den * 19

        pdf['local_slope'] = pdf['mid'].rolling(20).apply(get_slope)
        
        # Future returns when slope is "Neutral" (between -5 and +5)
        # Compare to "Strong" (above 5)
        neutral = (pdf['local_slope'] > -5) & (pdf['local_slope'] < 5)
        strong = (pdf['local_slope'] >= 5)
        
        pdf['ret_10'] = pdf['mid'].shift(-10) - pdf['mid']
        
        print(f"Mean Ret_10 (Neutral): {pdf.loc[neutral, 'ret_10'].mean():.4f}")
        print(f"Mean Ret_10 (Strong):  {pdf.loc[strong, 'ret_10'].mean():.4f}")

if __name__ == "__main__":
    simulate_pepper_trim()
