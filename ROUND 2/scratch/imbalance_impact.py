import pandas as pd
import numpy as np
import glob

def analyze_imbalance_impact():
    files = sorted(glob.glob("ROUND 2/data_capsule/prices_round_2_day_*.csv"))
    if not files:
        print("No files found.")
        return

    results = []

    for fpath in files:
        print(f"\nEvaluating: {fpath}")
        df = pd.read_csv(fpath, sep=";")
        prod = 'ASH_COATED_OSMIUM'
        pdf = df[df['product'] == prod].copy()
        
        pdf['mid'] = (pdf['bid_price_1'] + pdf['ask_price_1']) / 2
        
        # Load trades for volume imbalance
        tfile = fpath.replace("prices_", "trades_")
        try:
            tdf = pd.read_csv(tfile, sep=";")
            tpdf = tdf[tdf['symbol'] == prod].copy()
            
            # Aggregate trades per timestamp
            tpdf['signed_qty'] = tpdf.apply(lambda r: r['quantity'] if r['price'] >= pdf.loc[pdf['timestamp']==r['timestamp'], 'mid'].values[0] else -r['quantity'], axis=1)
            agg_trades = tpdf.groupby('timestamp')['signed_qty'].sum().reset_index()
            
            pdf = pdf.merge(agg_trades, on='timestamp', how='left').fillna(0)
            
            # Signed volume imbalance
            pdf['imbalance'] = pdf['signed_qty']
            
            # Future return over 5 ticks
            pdf['ret_5'] = pdf['mid'].shift(-5) - pdf['mid']
            
            # Group by imbalance buckets
            pdf['imb_bucket'] = (pdf['imbalance'] // 5) * 5
            
            summary = pdf.groupby('imb_bucket')['ret_5'].agg(['mean', 'std', 'count'])
            print(summary[summary['count'] > 10])
            
        except Exception as e:
            print(f"Error processing trades: {e}")

if __name__ == "__main__":
    analyze_imbalance_impact()
