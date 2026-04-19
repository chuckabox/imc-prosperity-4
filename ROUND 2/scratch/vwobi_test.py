import pandas as pd
import numpy as np
import glob

def test_vw_obi():
    files = sorted(glob.glob("ROUND 2/data_capsule/prices_round_2_day_*.csv"))
    if not files: return

    for fpath in files:
        print(f"\nEvaluating: {fpath}")
        df = pd.read_csv(fpath, sep=";")
        prod = 'ASH_COATED_OSMIUM'
        pdf = df[df['product'] == prod].copy()
        pdf['mid'] = (pdf['bid_price_1'] + pdf['ask_price_1']) / 2
        
        # L1 OBI
        pdf['obi_l1'] = (pdf['bid_volume_1'] - pdf['ask_volume_1']) / (pdf['bid_volume_1'] + pdf['ask_volume_1'])
        
        # VW OBI (L1*1 + L2*0.5 + L3*0.25)
        def calc_vw_obi(r):
            b_score = r['bid_volume_1'] * 1.0 + r['bid_volume_2'] * 0.5 + r.get('bid_volume_3', 0) * 0.25
            a_score = r['ask_volume_1'] * 1.0 + r['ask_volume_2'] * 0.5 + r.get('ask_volume_3', 0) * 0.25
            return (b_score - a_score) / (b_score + a_score)
        
        pdf['vw_obi'] = pdf.apply(calc_vw_obi, axis=1)
        
        pdf['ret_5'] = pdf['mid'].shift(-5) - pdf['mid']
        
        print(f"Corr(L1 OBI, Ret_5): {pdf['obi_l1'].corr(pdf['ret_5']):.4f}")
        print(f"Corr(VW OBI, Ret_5): {pdf['vw_obi'].corr(pdf['ret_5']):.4f}")

if __name__ == "__main__":
    test_vw_obi()
