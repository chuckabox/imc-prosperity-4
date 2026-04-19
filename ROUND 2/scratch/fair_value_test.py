"""
Quantify exact v2000 issues and proposed fixes.
1. _obi_deep has NEGATIVE predictive power — use L1 OBI instead
2. OSMIUM_OBI_FAIR_SHIFT uses raw OBI — quantify optimal shift
3. Microprice as fair value component
4. VWAP anchor blend ratio analysis
"""
import pandas as pd
import numpy as np

files = [
    "ROUND 2/data_capsule/prices_round_2_day_-1.csv",
    "ROUND 2/data_capsule/prices_round_2_day_0.csv",
    "ROUND 2/data_capsule/prices_round_2_day_1.csv",
]

print("ANALYSIS: What should the fair value be?\n")

for fpath in files:
    df = pd.read_csv(fpath, sep=";")
    prod = "ASH_COATED_OSMIUM"
    pdf = df[df["product"] == prod].copy()
    pdf = pdf.dropna(subset=["bid_price_1", "ask_price_1"])
    pdf["mid"] = (pdf["bid_price_1"] + pdf["ask_price_1"]) / 2
    pdf["bv1"] = pdf["bid_volume_1"]
    pdf["av1"] = pdf["ask_volume_1"]
    
    # L1 OBI
    pdf["obi_l1"] = (pdf["bv1"] - pdf["av1"]) / (pdf["bv1"] + pdf["av1"])
    
    # Deep OBI (v2000 style, 2-level harmonic)
    bv2 = pdf["bid_volume_2"].fillna(0)
    av2 = pdf["ask_volume_2"].fillna(0)
    deep_bv = pdf["bv1"] + bv2 / 2.0
    deep_av = pdf["av1"] + av2 / 2.0
    pdf["obi_deep"] = (deep_bv - deep_av) / (deep_bv + deep_av + 1e-9)
    
    # Microprice
    pdf["microprice"] = (pdf["bid_price_1"] * pdf["av1"] + pdf["ask_price_1"] * pdf["bv1"]) / (pdf["bv1"] + pdf["av1"])
    
    # VWAP (3-level)
    bid_val = pdf["bid_price_1"] * pdf["bv1"]
    bid_vol = pdf["bv1"].copy()
    ask_val = pdf["ask_price_1"] * pdf["av1"]
    ask_vol = pdf["av1"].copy()
    for i in [2, 3]:
        bp = pdf.get(f"bid_price_{i}")
        bv = pdf.get(f"bid_volume_{i}")
        ap = pdf.get(f"ask_price_{i}")
        av = pdf.get(f"ask_volume_{i}")
        if bp is not None:
            bid_val = bid_val + (bp * bv).fillna(0)
            bid_vol = bid_vol + bv.fillna(0)
            ask_val = ask_val + (ap * av).fillna(0)
            ask_vol = ask_vol + av.fillna(0)
    pdf["vwap_bid"] = bid_val / bid_vol
    pdf["vwap_ask"] = ask_val / ask_vol
    pdf["vwap_mid"] = (pdf["vwap_bid"] + pdf["vwap_ask"]) / 2
    
    # Future returns
    pdf["ret_1"] = pdf["mid"].shift(-1) - pdf["mid"]
    pdf["ret_5"] = pdf["mid"].shift(-5) - pdf["mid"]
    
    print(f"=== {fpath.split('_')[-1].replace('.csv','')} ===")
    print(f"  OSMIUM fair value comparison (corr to ret_5):")
    
    # Test various fair value formulas
    candidates = {}
    
    # Current v2000: 0.65 * vwap_mid + 0.35 * 10000 + obi_deep * 0.6
    pdf["fair_v2000"] = 0.65 * pdf["vwap_mid"] + 0.35 * 10000 + pdf["obi_deep"] * 0.6
    candidates["v2000 (vwap+anchor+deepOBI)"] = pdf["fair_v2000"] - pdf["mid"]
    
    # Microprice only
    candidates["microprice"] = pdf["microprice"] - pdf["mid"]
    
    # VWAP only
    candidates["vwap_mid"] = pdf["vwap_mid"] - pdf["mid"]
    
    # Mid + L1 OBI shift
    for shift in [0.3, 0.5, 0.8, 1.0, 1.5, 2.0]:
        key = f"mid + L1_OBI*{shift}"
        candidates[key] = pdf["obi_l1"] * shift
    
    # Microprice + anchor blend
    for aw in [0.0, 0.1, 0.2, 0.35]:
        key = f"micro*{1-aw:.2f} + anchor*{aw:.2f}"
        fair = (1 - aw) * pdf["microprice"] + aw * 10000
        candidates[key] = fair - pdf["mid"]
    
    # Microprice + L1 OBI shift
    for shift in [0.3, 0.5, 0.8]:
        key = f"microprice + L1*{shift}"
        fair = pdf["microprice"] + pdf["obi_l1"] * shift
        candidates[key] = fair - pdf["mid"]
    
    # VWAP + L1 OBI shift
    for shift in [0.3, 0.5, 0.8, 1.2, 1.5, 2.0, 2.5, 3.0]:
        key = f"vwap + L1*{shift}"
        fair = pdf["vwap_mid"] + pdf["obi_l1"] * shift
        candidates[key] = fair - pdf["mid"]
    
    # Sort by correlation
    results = []
    for name, edge in candidates.items():
        c1 = edge.corr(pdf["ret_1"])
        c5 = edge.corr(pdf["ret_5"])
        results.append((name, c1, c5))
    
    results.sort(key=lambda x: -x[2])
    for name, c1, c5 in results[:15]:
        marker = " <-- CURRENT" if "v2000" in name else ""
        print(f"    {name:38s} ret_1={c1:.4f}  ret_5={c5:.4f}{marker}")
    
    # Pepper analysis
    prod = "INTARIAN_PEPPER_ROOT"
    ppdf = df[df["product"] == prod].copy()
    ppdf = ppdf.dropna(subset=["bid_price_1", "ask_price_1"])
    ppdf["mid"] = (ppdf["bid_price_1"] + ppdf["ask_price_1"]) / 2
    ppdf["bv1"] = ppdf["bid_volume_1"]
    ppdf["av1"] = ppdf["ask_volume_1"]
    ppdf["obi_l1"] = (ppdf["bv1"] - ppdf["av1"]) / (ppdf["bv1"] + ppdf["av1"])
    ppdf["ret_5"] = ppdf["mid"].shift(-5) - ppdf["mid"]
    
    print(f"\n  PEPPER OBI analysis:")
    # When OBI is strongly positive, should we be MORE or LESS aggressive buying?
    obi_high = ppdf["obi_l1"] > 0.3
    obi_low = ppdf["obi_l1"] < -0.3
    obi_mid_range = (ppdf["obi_l1"] >= -0.3) & (ppdf["obi_l1"] <= 0.3)
    print(f"    OBI > 0.3:  ret_5 mean = {ppdf.loc[obi_high, 'ret_5'].mean():.4f} (n={obi_high.sum()})")
    print(f"    OBI in [-0.3, 0.3]: ret_5 mean = {ppdf.loc[obi_mid_range, 'ret_5'].mean():.4f} (n={obi_mid_range.sum()})")
    print(f"    OBI < -0.3: ret_5 mean = {ppdf.loc[obi_low, 'ret_5'].mean():.4f} (n={obi_low.sum()})")
    print()

print("Done.")
