"""Quick alpha scan across all Round 2 IMC days."""
import pandas as pd
import numpy as np
import glob

files = sorted(glob.glob("ROUND 2/data_capsule/prices_round_*_day_*.csv"))
print(f"Scanning {len(files)} files\n")

for fpath in files:
    print(f"\n{'='*60}")
    print(f"FILE: {fpath}")
    df = pd.read_csv(fpath, sep=";")
    
    for prod in df["product"].unique():
        pdf = df[df["product"] == prod].copy()
        pdf = pdf.dropna(subset=["bid_price_1", "ask_price_1"])
        pdf["mid"] = (pdf["bid_price_1"] + pdf["ask_price_1"]) / 2
        pdf["spread"] = pdf["ask_price_1"] - pdf["bid_price_1"]
        pdf["bv1"] = pdf["bid_volume_1"]
        pdf["av1"] = pdf["ask_volume_1"]
        pdf["obi"] = (pdf["bv1"] - pdf["av1"]) / (pdf["bv1"] + pdf["av1"])
        
        # 3-level depth
        total_bv = pdf["bv1"].copy()
        total_av = pdf["av1"].copy()
        for i in [2, 3]:
            bv_col = f"bid_volume_{i}"
            av_col = f"ask_volume_{i}"
            if bv_col in pdf.columns:
                total_bv = total_bv + pdf[bv_col].fillna(0)
                total_av = total_av + pdf[av_col].fillna(0)
        pdf["deep_obi"] = (total_bv - total_av) / (total_bv + total_av + 1e-9)
        
        # Microprice
        pdf["microprice"] = (pdf["bid_price_1"] * pdf["av1"] + pdf["ask_price_1"] * pdf["bv1"]) / (pdf["bv1"] + pdf["av1"])
        pdf["micro_edge"] = pdf["microprice"] - pdf["mid"]
        
        # Weighted microprice (L1+L2)
        if "bid_price_2" in pdf.columns:
            bp2 = pdf["bid_price_2"].fillna(pdf["bid_price_1"])
            bv2 = pdf["bid_volume_2"].fillna(0)
            ap2 = pdf["ask_price_2"].fillna(pdf["ask_price_1"])
            av2 = pdf["ask_volume_2"].fillna(0)
            w_bid = pdf["bv1"] + bv2 * 0.5
            w_ask = pdf["av1"] + av2 * 0.5
            pdf["wmicro"] = (pdf["bid_price_1"] * w_ask + pdf["ask_price_1"] * w_bid) / (w_bid + w_ask)
            pdf["wmicro_edge"] = pdf["wmicro"] - pdf["mid"]
        
        # Momentum
        pdf["mom_5"] = pdf["mid"] - pdf["mid"].shift(5)
        pdf["mom_10"] = pdf["mid"] - pdf["mid"].shift(10)
        pdf["mom_20"] = pdf["mid"] - pdf["mid"].shift(20)
        
        # Spread change
        pdf["spread_chg"] = pdf["spread"] - pdf["spread"].shift(1)
        
        # EMA of mid
        pdf["ema_10"] = pdf["mid"].ewm(span=10).mean()
        pdf["ema_dev"] = pdf["mid"] - pdf["ema_10"]
        
        # Volume pressure: ratio of L1 to total depth
        pdf["l1_concentration"] = (pdf["bv1"] + pdf["av1"]) / (total_bv + total_av + 1e-9)
        
        # Future returns
        for h in [1, 3, 5, 10, 20]:
            pdf[f"ret_{h}"] = pdf["mid"].shift(-h) - pdf["mid"]
        
        print(f"\n--- {prod} ---")
        print(f"  Ticks={len(pdf)}  Mid: {pdf['mid'].min():.0f}-{pdf['mid'].max():.0f}  Spread: {pdf['spread'].mean():.2f}")
        
        signals = ["obi", "deep_obi", "micro_edge", "mom_5", "mom_10", "spread_chg", "ema_dev", "l1_concentration"]
        if "wmicro_edge" in pdf.columns:
            signals.append("wmicro_edge")
        
        horizons = [1, 3, 5, 10]
        
        print(f"  {'Signal':20s} | {'ret_1':>7s} {'ret_3':>7s} {'ret_5':>7s} {'ret_10':>7s}")
        print(f"  {'-'*20}-+-{'-'*7}-{'-'*7}-{'-'*7}-{'-'*7}")
        for sig in signals:
            if sig in pdf.columns:
                corrs = []
                for h in horizons:
                    c = pdf[sig].corr(pdf[f"ret_{h}"])
                    corrs.append(f"{c:7.4f}")
                print(f"  {sig:20s} | {' '.join(corrs)}")
        
        # Trade flow analysis
        tfile = fpath.replace("prices_", "trades_")
        try:
            tdf = pd.read_csv(tfile, sep=";")
            tpdf = tdf[tdf["symbol"] == prod] if "symbol" in tdf.columns else tdf[tdf.get("product", pd.Series()) == prod] if "product" in tdf.columns else pd.DataFrame()
            if len(tpdf) > 0:
                print(f"  Trades: {len(tpdf)} rows")
                if "quantity" in tpdf.columns:
                    print(f"  Trade qty: mean={tpdf['quantity'].mean():.1f}, total={tpdf['quantity'].sum()}")
        except Exception:
            pass

print("\n\nDone.")
