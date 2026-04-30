import pandas as pd
import glob
import os

files = glob.glob("ROUND 5/data_capsule/prices_round_5_day_*.csv")
for f in files:
    df = pd.read_csv(f, sep=';')
    bh = df[df['product'] == 'GALAXY_SOUNDS_BLACK_HOLES'][['timestamp', 'mid_price']].rename(columns={'mid_price': 'BH'})
    poly = df[df['product'] == 'SLEEP_POD_POLYESTER'][['timestamp', 'mid_price']].rename(columns={'mid_price': 'Poly'})
    merged = pd.merge(bh, poly, on='timestamp')
    corr = merged['BH'].corr(merged['Poly'])
    # Check lag 100
    merged['BH_lag'] = merged['BH'].shift(100)
    corr_lag = merged['BH_lag'].corr(merged['Poly'])
    print(f"{os.path.basename(f)}: Corr={corr:.2f}, Corr_Lag100={corr_lag:.2f}")
