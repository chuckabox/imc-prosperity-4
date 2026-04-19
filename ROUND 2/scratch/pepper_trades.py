import pandas as pd
import numpy as np
import glob

def analyze_pepper_trades():
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
        
        # Load trades
        tfile = fpath.replace("prices_", "trades_")
        try:
            tdf = pd.read_csv(tfile, sep=";")
            tpdf = tdf[tdf['symbol'] == prod].copy()
            
            # Signed volume (aggressive only)
            if 'quantity' in tpdf.columns:
                # We need to know who was the aggressor.
                # In Prosperity CSVs, price == ask_price_1 usually means buyer aggressed.
                # But we don't have the book in the trade csv.
                # We can merge it.
                tpdf = tpdf.merge(pdf[['timestamp', 'bid_price_1', 'ask_price_1', 'mid']], on='timestamp', how='left')
                tpdf['side'] = tpdf.apply(lambda r: 1 if r['price'] >= r['mid'] else -1, axis=1)
                tpdf['signed_vol'] = tpdf['quantity'] * tpdf['side']
                
                agg_t = tpdf.groupby('timestamp')['signed_vol'].sum().reset_index()
                pdf = pdf.merge(agg_t, on='timestamp', how='left').fillna(0)
                
                # Check correlation with next 1, 5, 20 ticks
                for h in [1, 5, 20]:
                    pdf[f'ret_{h}'] = pdf['mid'].shift(-h) - pdf['mid']
                    print(f"Corr(Trade Imb, Ret_{h}): {pdf['signed_vol'].corr(pdf[f'ret_{h}']):.4f}")
                    
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    analyze_pepper_trades()
