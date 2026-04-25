"""
Strategy analysis for ROUND 3 data.

Tests:
1. IV surface — Black-Scholes implied vol per strike, parabolic fit vs moneyness.
2. IV deviation autocorr (lag-1) — confirms mean reversion of mispricing.
3. EMA mean reversion edge on VFE underlying — fixed threshold vs random.
4. Realised vs implied vol — sanity check for gamma scalping edge.

Days 0+1 only (Day 2 hidden).
"""
from __future__ import annotations
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_capsule"
OUT = ROOT / "scratch" / "analysis_out"
OUT.mkdir(parents=True, exist_ok=True)

VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
TS_PER_DAY = 1_000_000
TOTAL_DAYS = 8  # contract life


# ----- Black-Scholes -----
def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_call(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def bs_delta(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1)


def implied_vol(price, S, K, T, lo=1e-4, hi=2.0, tol=1e-5, n=80):
    """Bisection IV in vol/sqrt(day) units (T in days)."""
    intrinsic = max(0.0, S - K)
    if price <= intrinsic + 1e-6:
        return None
    if price >= S:
        return None
    for _ in range(n):
        mid = 0.5 * (lo + hi)
        if bs_call(S, K, T, mid) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


# ----- Load -----
def load_day(day):
    f = DATA / f"prices_round_3_day_{day}.csv"
    return pd.read_csv(f, sep=";")


def main():
    days = [0, 1]  # train only — Day 2 is hidden
    print(f"Loading days {days}...")
    df = pd.concat([load_day(d) for d in days], ignore_index=True)
    df = df.dropna(subset=["bid_price_1", "ask_price_1"])
    df["mid"] = (df["bid_price_1"] + df["ask_price_1"]) / 2.0

    pivot_mid = df.pivot_table(index=["day", "timestamp"], columns="product", values="mid")
    pivot_mid = pivot_mid.sort_index()

    if "VELVETFRUIT_EXTRACT" not in pivot_mid.columns:
        print("VFE missing"); return
    S_series = pivot_mid["VELVETFRUIT_EXTRACT"]

    # --- (1) Realised vs implied vol on VFE ---
    print("\n=== (1) VFE returns ===")
    print(f"Mean S: {S_series.mean():.1f}, Std: {S_series.std():.2f}")
    log_ret = np.log(S_series / S_series.shift(1)).dropna()
    # tick = 100 timestamps. ticks per day = 10000. vol per day = std * sqrt(10000)
    real_vol_per_day = log_ret.std() * math.sqrt(10000)
    print(f"Realised vol per day (log-ret * sqrt(10000)): {real_vol_per_day*100:.3f}%")

    # --- (2) IV per strike per tick ---
    print("\n=== (2) IV surface ===")
    iv_records = []
    sample_every = 50  # ~200 samples per day per strike
    for (day, ts), row in pivot_mid.iloc[::sample_every].iterrows():
        S = row.get("VELVETFRUIT_EXTRACT")
        if pd.isna(S):
            continue
        TTE = (TOTAL_DAYS - day) - ts / TS_PER_DAY
        if TTE <= 0:
            continue
        for K in VEV_STRIKES:
            sym = f"VEV_{K}"
            price = row.get(sym)
            if pd.isna(price) or price <= 0:
                continue
            iv = implied_vol(price, S, K, TTE)
            if iv is None:
                continue
            mny = math.log(K / S)
            iv_records.append({
                "day": day, "ts": ts, "K": K, "S": S,
                "price": price, "TTE": TTE, "iv": iv, "moneyness": mny,
            })
    iv_df = pd.DataFrame(iv_records)
    print(f"IV samples: {len(iv_df)}")
    if iv_df.empty:
        return
    print("\nMean IV per strike:")
    print(iv_df.groupby("K")["iv"].agg(["mean", "std", "count"]))

    # --- (3) Parabolic fit IV vs moneyness, per snapshot ---
    print("\n=== (3) Parabolic fit IV vs moneyness ===")
    fit_residuals = []
    for (day, ts), grp in iv_df.groupby(["day", "ts"]):
        if len(grp) < 4:
            continue
        x = grp["moneyness"].values
        y = grp["iv"].values
        # fit y = a*x^2 + b*x + c
        try:
            coefs = np.polyfit(x, y, 2)
        except np.linalg.LinAlgError:
            continue
        fair_iv = np.polyval(coefs, x)
        for i, (idx, r) in enumerate(grp.iterrows()):
            fit_residuals.append({
                "day": day, "ts": ts, "K": r["K"], "S": r["S"], "TTE": r["TTE"],
                "iv": r["iv"], "fair_iv": fair_iv[i], "iv_dev": r["iv"] - fair_iv[i],
                "price": r["price"],
            })
    res_df = pd.DataFrame(fit_residuals)
    print(f"Residual samples: {len(res_df)}")
    print("\nIV deviation per strike:")
    print(res_df.groupby("K")["iv_dev"].agg(["mean", "std"]))

    # --- (4) Autocorrelation lag-1 of iv_dev per strike ---
    print("\n=== (4) IV-deviation lag-1 autocorr (negative = mean reversion) ===")
    for K, grp in res_df.groupby("K"):
        s = grp.sort_values(["day", "ts"])["iv_dev"].values
        if len(s) < 20:
            continue
        ac = np.corrcoef(s[:-1], s[1:])[0, 1]
        print(f"  K={K}: lag-1 autocorr = {ac:+.3f}  (n={len(s)})")

    # --- (5) Convert iv_dev → price-edge per strike ---
    print("\n=== (5) Price edge from IV deviation ===")
    edges = []
    for _, r in res_df.iterrows():
        fair_price = bs_call(r["S"], r["K"], r["TTE"], r["fair_iv"])
        edge = r["price"] - fair_price  # > 0 = option overpriced
        edges.append(edge)
    res_df["price_edge"] = edges
    print("Mean price edge per strike (positive = overpriced):")
    print(res_df.groupby("K")["price_edge"].agg(["mean", "std"]))

    # --- (6) EMA reversion on VFE ---
    print("\n=== (6) EMA reversion on VFE ===")
    for span in [50, 100, 200, 500]:
        ema = S_series.ewm(span=span, adjust=False).mean()
        dev = (S_series - ema).dropna()
        # fwd return at +50 ticks
        fwd = S_series.shift(-50) - S_series
        df_ev = pd.DataFrame({"dev": dev, "fwd": fwd}).dropna()
        if len(df_ev) < 100:
            continue
        # correlation: deviation vs fwd return — negative = mean reverting
        corr = df_ev["dev"].corr(df_ev["fwd"])
        print(f"  EMA span {span}: dev vs fwd-50 corr = {corr:+.4f}")

    # --- (7) HYDROGEL stationarity check ---
    print("\n=== (7) HYDROGEL_PACK stats ===")
    if "HYDROGEL_PACK" in pivot_mid.columns:
        H = pivot_mid["HYDROGEL_PACK"].dropna()
        print(f"  Mean: {H.mean():.2f}  Std: {H.std():.2f}  Range: [{H.min():.0f},{H.max():.0f}]")
        # lag-1 autocorr of returns
        h_ret = H.diff().dropna()
        if len(h_ret) > 100:
            print(f"  Return lag-1 autocorr: {np.corrcoef(h_ret[:-1], h_ret[1:])[0,1]:+.4f}")

    # --- save outputs ---
    iv_df.to_csv(OUT / "iv_surface.csv", index=False)
    res_df.to_csv(OUT / "iv_deviation.csv", index=False)
    print(f"\nSaved -> {OUT}")


if __name__ == "__main__":
    main()
