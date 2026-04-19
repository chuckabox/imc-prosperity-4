import pandas as pd
import numpy as np
import glob

def analyze_cross_corr():
    files = sorted(glob.glob("ROUND 2/data_capsule/prices_round_2_day_*.csv"))
    if not files:
        print("No files found.")
        return

    for fpath in files:
        print(f"\nEvaluating: {fpath}")
        df = pd.read_csv(fpath, sep=";")
        
        # Pivot to get mid prices side by side
        df['mid'] = (df['bid_price_1'] + df['ask_price_1']) / 2
        pivoted = df.pivot_table(index='timestamp', columns='product', values='mid')
        
        if 'ASH_COATED_OSMIUM' not in pivoted.columns or 'INTARIAN_PEPPER_ROOT' not in pivoted.columns:
            continue
            
        pivoted = pivoted.dropna()
        
        osm = pivoted['ASH_COATED_OSMIUM']
        pep = pivoted['INTARIAN_PEPPER_ROOT']
        
        # Returns
        osm_ret = osm.pct_change().dropna()
        pep_ret = pep.pct_change().dropna()
        
        common_idx = osm_ret.index.intersection(pep_ret.index)
        osm_ret = osm_ret.loc[common_idx]
        pep_ret = pep_ret.loc[common_idx]
        
        print(f"Direct correlation: {osm_ret.corr(pep_ret):.4f}")
        
        # Lead/Lag
        for lag in range(1, 11):
            # Does OSM lead PEP?
            c_osm_leads = osm_ret.shift(lag).corr(pep_ret)
            # Does PEP lead OSM?
            c_pep_leads = pep_ret.shift(lag).corr(osm_ret)
            print(f"Lag {lag:2d}: OSM leads PEP: {c_osm_leads:7.4f} | PEP leads OSM: {c_pep_leads:7.4f}")

if __name__ == "__main__":
    analyze_cross_corr()
