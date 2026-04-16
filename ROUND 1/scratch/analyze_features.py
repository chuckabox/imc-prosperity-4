import pandas as pd
import numpy as np

def analyze_day(file_path):
    df = pd.read_csv(file_path, sep=';')
    results = {}
    
    for product in df['product'].unique():
        pdf = df[df['product'] == product].copy()
        pdf = pdf.sort_values('timestamp')
        
        # 1. Midprice & Return
        pdf['mid'] = (pdf['bid_price_1'] + pdf['ask_price_1']) / 2
        pdf['next_mid'] = pdf['mid'].shift(-1)
        pdf['ret_1'] = pdf['next_mid'] - pdf['mid']
        
        # 2. Imbalance (L1)
        pdf['imb'] = (pdf['bid_volume_1'] - pdf['ask_volume_1']) / (pdf['bid_volume_1'] + pdf['ask_volume_1'])
        
        # 6. OFI
        pdf['prev_bid_p'] = pdf['bid_price_1'].shift(1)
        pdf['prev_ask_p'] = pdf['ask_price_1'].shift(1)
        pdf['prev_bid_v'] = pdf['bid_volume_1'].shift(1)
        pdf['prev_ask_v'] = pdf['ask_volume_1'].shift(1)
        
        def calc_ofi(row):
            if np.isnan(row['prev_bid_p']): return 0
            db = 0
            if row['bid_price_1'] > row['prev_bid_p']: db = row['bid_volume_1']
            elif row['bid_price_1'] == row['prev_bid_p']: db = row['bid_volume_1'] - row['prev_bid_v']
            else: db = -row['prev_bid_v']
            
            da = 0
            if row['ask_price_1'] < row['prev_ask_p']: da = row['ask_volume_1']
            elif row['ask_price_1'] == row['prev_ask_p']: da = row['ask_volume_1'] - row['prev_ask_v']
            else: da = -row['prev_ask_v']
            return db - da

        pdf['ofi'] = pdf.apply(calc_ofi, axis=1)
        
        # 7. One-Sided
        pdf['one_sided_bid'] = pdf['bid_volume_2'].isna() | (pdf['bid_volume_2'] == 0)
        pdf['one_sided_ask'] = pdf['ask_volume_2'].isna() | (pdf['ask_volume_2'] == 0)
        
        # 8. Spread & Gaps
        pdf['spread'] = pdf['ask_price_1'] - pdf['bid_price_1']
        pdf['bid_gap'] = pdf['bid_price_1'] - pdf['bid_price_2']
        pdf['ask_gap'] = pdf['ask_price_2'] - pdf['ask_price_1']

        results[product] = {
            'corr_l1_imb': pdf[['imb', 'ret_1']].corr().iloc[0, 1],
            'corr_ofi': pdf[['ofi', 'ret_1']].corr().iloc[0, 1],
            'avg_spread': pdf['spread'].mean(),
            'avg_bid_gap': pdf['bid_gap'].mean(),
            'avg_ask_gap': pdf['ask_gap'].mean(),
            'one_sided_bid_pct': pdf['one_sided_bid'].mean(),
            'one_sided_ask_pct': pdf['one_sided_ask'].mean(),
        }
    return results

print("--- Data Analysis Day 0 (Fixed) ---")
res = analyze_day('ROUND 1/data_capsule/prices_round_1_day_0.csv')
for p, stats in res.items():
    print(f"\nProduct: {p}")
    print(f"L1 Imbalance Corr: {stats['corr_l1_imb']:.4f}")
    print(f"OFI Corr:          {stats['corr_ofi']:.4f}")
    print(f"Avg Spread:        {stats['avg_spread']:.2f}")
    print(f"Avg Gap (B/A):     {stats['avg_bid_gap']:.2f} / {stats['avg_ask_gap']:.2f}")
    print(f"One-sidedness (B/A): {stats['one_sided_bid_pct']*100:.1f}% / {stats['one_sided_ask_pct']*100:.1f}%")
