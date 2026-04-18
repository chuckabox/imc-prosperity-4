"""
Deeper alpha analysis: microprice, OBI regime splits, and combined signals.
Focus on actionable improvements for the trader.
"""
import pandas as pd
import numpy as np

files = [
    "ROUND 2/data_capsule/prices_round_2_day_-1.csv",
    "ROUND 2/data_capsule/prices_round_2_day_0.csv",
    "ROUND 2/data_capsule/prices_round_2_day_1.csv",
]

for fpath in files:
    print(f"\n{'='*70}")
    print(f"{fpath}")
    df = pd.read_csv(fpath, sep=";")
    
    for prod in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        pdf = df[df["product"] == prod].copy()
        pdf = pdf.dropna(subset=["bid_price_1", "ask_price_1"])
        pdf["mid"] = (pdf["bid_price_1"] + pdf["ask_price_1"]) / 2
        pdf["spread"] = pdf["ask_price_1"] - pdf["bid_price_1"]
        pdf["bv1"] = pdf["bid_volume_1"]
        pdf["av1"] = pdf["ask_volume_1"]
        pdf["obi"] = (pdf["bv1"] - pdf["av1"]) / (pdf["bv1"] + pdf["av1"])
        
        # Microprice
        pdf["microprice"] = (pdf["bid_price_1"] * pdf["av1"] + pdf["ask_price_1"] * pdf["bv1"]) / (pdf["bv1"] + pdf["av1"])
        
        # Future returns
        pdf["ret_1"] = pdf["mid"].shift(-1) - pdf["mid"]
        pdf["ret_5"] = pdf["mid"].shift(-5) - pdf["mid"]
        
        print(f"\n--- {prod} ---")
        
        # 1. Microprice as fair value: how good is it?
        # If we used microprice instead of mid, what edge would we capture?
        pdf["micro_vs_mid"] = pdf["microprice"] - pdf["mid"]
        # When microprice > mid, price tends to go up
        up_mask = pdf["micro_vs_mid"] > 0
        dn_mask = pdf["micro_vs_mid"] < 0
        print(f"  Microprice analysis:")
        print(f"    Micro > mid: mean ret_1 = {pdf.loc[up_mask, 'ret_1'].mean():.4f}")
        print(f"    Micro < mid: mean ret_1 = {pdf.loc[dn_mask, 'ret_1'].mean():.4f}")
        print(f"    Micro > mid: mean ret_5 = {pdf.loc[up_mask, 'ret_5'].mean():.4f}")
        print(f"    Micro < mid: mean ret_5 = {pdf.loc[dn_mask, 'ret_5'].mean():.4f}")
        
        # 2. OBI quartile analysis
        print(f"\n  OBI quartile analysis (ret_5):")
        pdf["obi_q"] = pd.qcut(pdf["obi"], 5, labels=False, duplicates="drop")
        for q in sorted(pdf["obi_q"].unique()):
            mask = pdf["obi_q"] == q
            obi_range = f"[{pdf.loc[mask, 'obi'].min():.2f}, {pdf.loc[mask, 'obi'].max():.2f}]"
            print(f"    Q{q}: OBI {obi_range:20s} -> ret_5={pdf.loc[mask, 'ret_5'].mean():.4f}  (n={mask.sum()})")
        
        # 3. Combined signal: microprice + momentum
        pdf["combo"] = pdf["micro_vs_mid"] * 0.5 + (pdf["mid"] - pdf["mid"].shift(5)) * -0.5
        print(f"\n  Combined signal corr -> ret_5: {pdf['combo'].corr(pdf['ret_5']):.4f}")
        
        # 4. Spread regime -> return characteristics
        print(f"\n  Spread regime analysis:")
        spread_median = pdf["spread"].median()
        wide = pdf["spread"] > spread_median
        narrow = pdf["spread"] <= spread_median
        print(f"    Wide spread:   ret_5 mean={pdf.loc[wide, 'ret_5'].mean():.4f}, std={pdf.loc[wide, 'ret_5'].std():.4f}")
        print(f"    Narrow spread: ret_5 mean={pdf.loc[narrow, 'ret_5'].mean():.4f}, std={pdf.loc[narrow, 'ret_5'].std():.4f}")
        
        # 5. VWAP vs mid as fair value
        # 3-level VWAP
        bp1, bv1 = pdf["bid_price_1"], pdf["bid_volume_1"]
        ap1, av1 = pdf["ask_price_1"], pdf["ask_volume_1"]
        
        bid_val = bp1 * bv1
        bid_vol = bv1.copy()
        ask_val = ap1 * av1
        ask_vol = av1.copy()
        
        for i in [2, 3]:
            bp = pdf.get(f"bid_price_{i}")
            bv = pdf.get(f"bid_volume_{i}")
            ap = pdf.get(f"ask_price_{i}")
            av = pdf.get(f"ask_volume_{i}")
            if bp is not None:
                valid_b = ~bp.isna()
                bid_val = bid_val + (bp * bv).fillna(0)
                bid_vol = bid_vol + bv.fillna(0)
                valid_a = ~ap.isna()
                ask_val = ask_val + (ap * av).fillna(0)
                ask_vol = ask_vol + av.fillna(0)
        
        pdf["vwap_bid"] = bid_val / bid_vol
        pdf["vwap_ask"] = ask_val / ask_vol
        pdf["vwap_mid"] = (pdf["vwap_bid"] + pdf["vwap_ask"]) / 2
        pdf["vwap_edge"] = pdf["vwap_mid"] - pdf["mid"]
        print(f"\n  VWAP edge -> ret_5: {pdf['vwap_edge'].corr(pdf['ret_5']):.4f}")
        
        # 6. Blended fair: microprice + VWAP
        pdf["blended_fair"] = 0.6 * pdf["microprice"] + 0.4 * pdf["vwap_mid"]
        pdf["blended_edge"] = pdf["blended_fair"] - pdf["mid"]
        print(f"  Blended (0.6*micro + 0.4*vwap) -> ret_5: {pdf['blended_edge'].corr(pdf['ret_5']):.4f}")
        
        # 7. Osmium specific: anchor reversion
        if prod == "ASH_COATED_OSMIUM":
            pdf["anchor_dist"] = pdf["mid"] - 10000
            print(f"\n  Anchor dist -> ret_10: {pdf['anchor_dist'].corr(pdf['ret_5'].shift(-5) if 'ret_5' in pdf else pdf['ret_5']):.4f}")
            print(f"  Anchor dist -> ret_5: {pdf['anchor_dist'].corr(pdf['ret_5']):.4f}")

print("\nDone.")
