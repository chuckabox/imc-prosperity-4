#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate Round 5 spread-regime dashboard (similar to provided example)."
    )
    p.add_argument(
        "--prices",
        nargs="+",
        required=True,
        help="Round 5 prices CSV files (e.g. day2/day3/day4).",
    )
    p.add_argument("--symbol-a", required=True, help="First symbol in pair.")
    p.add_argument("--symbol-b", required=True, help="Second symbol in pair.")
    p.add_argument(
        "--reference-symbol",
        default="",
        help="Reference symbol for distributions/returns (default: symbol-a).",
    )
    p.add_argument(
        "--spread-threshold",
        type=float,
        default=2.0,
        help="Tight spread threshold for both symbols.",
    )
    p.add_argument(
        "--forward-lag",
        type=int,
        default=20,
        help="Forward return lag in ticks.",
    )
    p.add_argument(
        "--freq-window",
        type=int,
        default=100,
        help="Rolling window for signal frequency.",
    )
    p.add_argument(
        "--preview-points",
        type=int,
        default=1000,
        help="Points to show in top-left spread-over-time panel.",
    )
    p.add_argument("--out", required=True, help="Output PNG file path.")
    return p.parse_args()


def infer_day_number(path: str, fallback_idx: int) -> int:
    m = re.search(r"day_(\d+)\.csv$", Path(path).name)
    return int(m.group(1)) if m else fallback_idx


def load_days(price_paths: list[str], symbol_a: str, symbol_b: str, reference_symbol: str) -> pd.DataFrame:
    keep = [
        "timestamp",
        "product",
        "bid_price_1",
        "ask_price_1",
        "mid_price",
    ]
    frames = []
    for i, p in enumerate(price_paths):
        df = pd.read_csv(p, sep=";")[keep].copy()
        df["day_idx"] = i
        df["day_num"] = infer_day_number(p, i)
        frames.append(df)
    all_df = pd.concat(frames, ignore_index=True)

    syms = {symbol_a, symbol_b, reference_symbol}
    all_df = all_df[all_df["product"].isin(syms)].copy()
    all_df["spread"] = all_df["ask_price_1"] - all_df["bid_price_1"]
    return all_df


def build_series(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    s = df[df["product"] == symbol][["day_idx", "day_num", "timestamp", "mid_price", "spread"]].copy()
    s = s.sort_values(["day_idx", "timestamp"]).reset_index(drop=True)
    return s


def make_dashboard(
    a: pd.DataFrame,
    b: pd.DataFrame,
    ref: pd.DataFrame,
    symbol_a: str,
    symbol_b: str,
    ref_symbol: str,
    spread_threshold: float,
    forward_lag: int,
    freq_window: int,
    preview_points: int,
    out_path: Path,
) -> None:
    merged = a.merge(
        b,
        on=["day_idx", "day_num", "timestamp"],
        how="inner",
        suffixes=("_a", "_b"),
    ).merge(
        ref[["day_idx", "day_num", "timestamp", "mid_price"]].rename(columns={"mid_price": "ref_mid"}),
        on=["day_idx", "day_num", "timestamp"],
        how="inner",
    )
    merged = merged.sort_values(["day_idx", "timestamp"]).reset_index(drop=True)
    merged["tight"] = (merged["spread_a"] <= spread_threshold) & (merged["spread_b"] <= spread_threshold)

    # Forward return on reference symbol.
    merged["fwd_ret"] = merged.groupby("day_idx")["ref_mid"].shift(-forward_lag) - merged["ref_mid"]

    # Simple "signal trading": if tight, trade mean-reversion on relative mid dislocation.
    rel = merged["mid_price_a"] - merged["mid_price_b"]
    rel_mu = rel.groupby(merged["day_idx"]).transform(lambda s: s.rolling(200, min_periods=50).mean())
    signal = np.where(merged["tight"], np.sign(rel_mu - rel), 0.0)
    merged["signal_ret"] = signal * merged["fwd_ret"].fillna(0.0)

    fig, axes = plt.subplots(3, 2, figsize=(14, 9))
    ax1, ax2, ax3, ax4, ax5, ax6 = axes.flatten()

    # 1) Spreads over time (preview on first day in list)
    day0 = merged[merged["day_idx"] == 0].head(preview_points)
    first_day_num = int(day0["day_num"].iloc[0]) if not day0.empty else 0
    ax1.plot(day0["timestamp"], day0["spread_a"], label=f"{symbol_a} spread", lw=1.0)
    ax1.plot(day0["timestamp"], day0["spread_b"], label=f"{symbol_b} spread", lw=1.0)
    ax1.axhline(spread_threshold, color="red", ls="--", lw=1.0, alpha=0.7, label=f"Threshold={spread_threshold:g}")
    ax1.set_title(f"{symbol_a} and {symbol_b} spreads (day {first_day_num}, first {preview_points} ticks)")
    ax1.set_xlabel("Timestamp")
    ax1.set_ylabel("Spread (ticks)")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.2)

    # 2) Reference price distribution tight vs not tight
    tight_ref = merged.loc[merged["tight"], "ref_mid"]
    not_tight_ref = merged.loc[~merged["tight"], "ref_mid"]
    if len(tight_ref) > 0:
        ax2.hist(tight_ref, bins=40, density=True, alpha=0.6, label="Tight spreads")
    if len(not_tight_ref) > 0:
        ax2.hist(not_tight_ref, bins=40, density=True, alpha=0.6, label="Not tight")
    ax2.set_title(f"Price Distribution: Tight vs Not Tight ({ref_symbol})")
    ax2.set_xlabel(f"{ref_symbol} mid price")
    ax2.set_ylabel("Density")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.2)

    # 3) Forward return distribution
    tight_ret = merged.loc[merged["tight"], "fwd_ret"].dropna()
    not_tight_ret = merged.loc[~merged["tight"], "fwd_ret"].dropna()
    if len(tight_ret) > 0:
        ax3.hist(tight_ret, bins=40, density=True, alpha=0.6, label=f"Tight (mean={tight_ret.mean():.2f})")
    if len(not_tight_ret) > 0:
        ax3.hist(not_tight_ret, bins=40, density=True, alpha=0.6, label=f"Not tight (mean={not_tight_ret.mean():.2f})")
    ax3.set_title(f"Forward Return Distribution ({forward_lag}-step)")
    ax3.set_xlabel(f"{forward_lag}-step forward return")
    ax3.set_ylabel("Density")
    ax3.legend(fontsize=8)
    ax3.grid(alpha=0.2)

    # 4) Cumulative returns from signal trading per day
    for d, g in merged.groupby("day_idx"):
        c = g["signal_ret"].fillna(0.0).cumsum()
        x = np.linspace(0.0, 1.0, len(c))
        day_num = int(g["day_num"].iloc[0])
        ax4.plot(x, c, lw=1.0, label=f"Day {day_num}")
    ax4.set_title(f"Cumulative Returns from Signal Trading ({forward_lag}-step lag)")
    ax4.set_xlabel("Normalized time")
    ax4.set_ylabel("Cumulative return")
    ax4.legend(fontsize=8)
    ax4.grid(alpha=0.2)

    # 5) Signal frequency over time (rolling mean) per day
    for d, g in merged.groupby("day_idx"):
        sig = g["tight"].astype(float).rolling(freq_window, min_periods=max(5, freq_window // 5)).mean()
        x = np.linspace(0.0, 1.0, len(sig))
        day_num = int(g["day_num"].iloc[0])
        ax5.plot(x, sig, lw=1.0, label=f"Day {day_num}")
    ax5.set_title(f"Signal Frequency Over Time (rolling {freq_window})")
    ax5.set_xlabel("Normalized time")
    ax5.set_ylabel("Signal frequency")
    ax5.legend(fontsize=8)
    ax5.grid(alpha=0.2)

    # 6) Spread relationship
    ax6.scatter(
        merged["spread_a"],
        merged["spread_b"],
        s=8,
        alpha=0.4,
        c=np.where(merged["tight"], "green", "tab:blue"),
    )
    ax6.axvline(spread_threshold, color="red", ls="--", lw=1.0, alpha=0.5)
    ax6.axhline(spread_threshold, color="red", ls="--", lw=1.0, alpha=0.5)
    ax6.set_title("Spread relationship (green = both tight)")
    ax6.set_xlabel(f"{symbol_a} spread")
    ax6.set_ylabel(f"{symbol_b} spread")
    ax6.grid(alpha=0.2)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    out_path = Path(args.out).resolve()
    ref_symbol = args.reference_symbol or args.symbol_a
    raw = load_days(args.prices, args.symbol_a, args.symbol_b, ref_symbol)
    a = build_series(raw, args.symbol_a)
    b = build_series(raw, args.symbol_b)
    ref = build_series(raw, ref_symbol)
    make_dashboard(
        a=a,
        b=b,
        ref=ref,
        symbol_a=args.symbol_a,
        symbol_b=args.symbol_b,
        ref_symbol=ref_symbol,
        spread_threshold=args.spread_threshold,
        forward_lag=args.forward_lag,
        freq_window=args.freq_window,
        preview_points=args.preview_points,
        out_path=out_path,
    )
    print(f"Wrote dashboard: {out_path}")


if __name__ == "__main__":
    main()
