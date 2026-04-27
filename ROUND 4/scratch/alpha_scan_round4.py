from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "ROUND 4" / "data_capsule"


def read_prices(day: int) -> pd.DataFrame:
    return pd.read_csv(DATASET / f"prices_round_4_day_{day}.csv", sep=";")


def scan_underlying(day: int, symbol: str, lookback: int = 100, horizons=(20, 50, 100, 200)) -> None:
    df = read_prices(day)
    g = df[df["product"] == symbol].copy().sort_values("timestamp")
    mid = g["mid_price"].astype(float)
    ema = mid.ewm(span=lookback, adjust=False).mean()
    diff = mid - ema
    vol = diff.rolling(lookback, min_periods=lookback).std()
    z = diff / vol.replace(0, np.nan)
    out = pd.DataFrame({"timestamp": g["timestamp"], "mid": mid, "ema": ema, "z": z})
    print(f"\n=== DAY {day} {symbol} mean-reversion scan ===")
    for thr in [1.0, 1.5, 2.0, 2.5]:
        hi = out[out["z"] >= thr]
        lo = out[out["z"] <= -thr]
        print(f"\nthreshold z={thr}")
        for h in horizons:
            fwd = out["mid"].shift(-h) - out["mid"]
            # short when rich: want negative fwd
            hi_edge = float((-fwd.loc[hi.index]).mean()) if len(hi) else float("nan")
            lo_edge = float((fwd.loc[lo.index]).mean()) if len(lo) else float("nan")
            print(
                f"  horizon={h:>3}  short-rich avg pnl/tick={hi_edge:>7.3f} ({len(hi):>4} obs)"
                f"   long-cheap avg pnl/tick={lo_edge:>7.3f} ({len(lo):>4} obs)"
            )


def scan_vev(day: int, strike: int, horizons=(20, 50, 100, 200)) -> None:
    df = read_prices(day)
    vfe = (
        df[df["product"] == "VELVETFRUIT_EXTRACT"][["timestamp", "mid_price"]]
        .rename(columns={"mid_price": "vfe_mid"})
        .sort_values("timestamp")
    )
    sym = f"VEV_{strike}"
    g = df[df["product"] == sym][["timestamp", "mid_price", "bid_price_1", "ask_price_1"]].copy().sort_values("timestamp")
    g = g.merge(vfe, on="timestamp", how="inner")
    g["mid"] = g["mid_price"].astype(float)
    g["intrinsic"] = (g["vfe_mid"].astype(float) - strike).clip(lower=0.0)
    g["mis"] = g["mid"] - g["intrinsic"]
    g["mis_z"] = (g["mis"] - g["mis"].rolling(200, min_periods=200).mean()) / g["mis"].rolling(200, min_periods=200).std()

    print(f"\n=== DAY {day} {sym} mispricing mean-reversion scan ===")
    for thr in [1.0, 1.5, 2.0]:
        hi = g[g["mis_z"] >= thr]
        lo = g[g["mis_z"] <= -thr]
        print(f"\nthreshold mis_z={thr}")
        for h in horizons:
            fwd = g["mid"].shift(-h) - g["mid"]
            hi_edge = float((-fwd.loc[hi.index]).mean()) if len(hi) else float("nan")
            lo_edge = float((fwd.loc[lo.index]).mean()) if len(lo) else float("nan")
            print(
                f"  horizon={h:>3}  short-rich avg pnl={hi_edge:>7.3f} ({len(hi):>4} obs)"
                f"   long-cheap avg pnl={lo_edge:>7.3f} ({len(lo):>4} obs)"
            )


def first_tenth_manual_windows(day: int) -> None:
    df = read_prices(day)
    cutoff = 100_000
    print(f"\n=== DAY {day} first 10% summary to timestamp {cutoff} ===")
    for sym in ["VELVETFRUIT_EXTRACT", "HYDROGEL_PACK", "VEV_5000", "VEV_5200", "VEV_5300", "VEV_5400"]:
        g = df[(df["product"] == sym) & (df["timestamp"] <= cutoff)].copy().sort_values("timestamp")
        if g.empty:
            continue
        mid = g["mid_price"].astype(float)
        print(
            f"{sym:20s} start={mid.iloc[0]:8.2f} end={mid.iloc[-1]:8.2f} "
            f"hi={mid.max():8.2f} lo={mid.min():8.2f} std={mid.std(ddof=0):7.2f}"
        )


def main() -> None:
    for day in [1, 2, 3]:
        scan_underlying(day, "VELVETFRUIT_EXTRACT")
        scan_underlying(day, "HYDROGEL_PACK")
        for strike in [5000, 5200, 5300, 5400]:
            scan_vev(day, strike)
        if day == 3:
            first_tenth_manual_windows(day)


if __name__ == "__main__":
    main()

