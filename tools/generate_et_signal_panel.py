#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate normalized e_t signal panel."
    )
    p.add_argument(
        "--prices",
        nargs="+",
        required=True,
        help="One or more prices CSV files (semicolon-separated IMC format).",
    )
    p.add_argument(
        "--mode",
        choices=["option_like", "cross_section"],
        default="option_like",
        help="Signal mode: option_like (strike vs underlying) or cross_section (symbol vs group mean).",
    )
    p.add_argument(
        "--underlying",
        default="",
        help="Underlying product symbol (required for --mode option_like), e.g. VELVETFRUIT_EXTRACT",
    )
    p.add_argument(
        "--prefix",
        required=True,
        help="Symbol group prefix, e.g. VEV or PEBBLES",
    )
    p.add_argument(
        "--rolling-window",
        type=int,
        default=200,
        help="Rolling window for std normalization (default: 200 ticks).",
    )
    p.add_argument(
        "--out",
        required=True,
        help="Output PNG path for panel.",
    )
    p.add_argument(
        "--out-csv",
        default="",
        help="Optional output CSV path for computed e_t series.",
    )
    p.add_argument(
        "--title",
        default="Normalized e_t signal over time",
        help="Figure title.",
    )
    return p.parse_args()


def load_prices(paths: list[str]) -> pd.DataFrame:
    frames = []
    for p in paths:
        df = pd.read_csv(p, sep=";")
        use_cols = ["timestamp", "product", "mid_price"]
        missing = [c for c in use_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns {missing} in {p}")
        frames.append(df[use_cols].copy())
    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["timestamp", "product"], kind="mergesort").reset_index(drop=True)
    return out


def option_symbols(df: pd.DataFrame, prefix: str) -> list[str]:
    pat = re.compile(rf"^{re.escape(prefix)}_(\d+)$")
    symbols = [s for s in df["product"].unique().tolist() if pat.match(s)]
    symbols.sort(key=lambda s: int(s.split("_")[1]))
    return symbols


def grouped_symbols(df: pd.DataFrame, prefix: str) -> list[str]:
    symbols = [s for s in df["product"].unique().tolist() if s.startswith(prefix + "_")]
    symbols.sort()
    return symbols


def compute_et_for_symbol(
    merged: pd.DataFrame,
    symbol: str,
    rolling_window: int,
) -> pd.DataFrame:
    s = merged[merged["product"] == symbol].copy()
    s = s.sort_values("global_t").reset_index(drop=True)
    strike = int(symbol.split("_")[1])
    s["intrinsic"] = np.maximum(s["underlying_mid"] - strike, 0.0)

    # Fit a simple linear mapping: option_mid ~= alpha + beta * intrinsic
    x = s["intrinsic"].to_numpy()
    y = s["mid_price"].to_numpy()
    if np.allclose(x.std(), 0.0):
        alpha, beta = float(np.nanmean(y)), 0.0
    else:
        beta, alpha = np.polyfit(x, y, 1)
    s["theo"] = alpha + beta * s["intrinsic"]
    s["raw_e"] = s["mid_price"] - s["theo"]

    # Normalize by rolling std (with warmup min periods)
    roll_std = s["raw_e"].rolling(window=rolling_window, min_periods=max(20, rolling_window // 5)).std()
    roll_std = roll_std.replace(0, np.nan)
    s["e_t"] = s["raw_e"] / roll_std
    s["symbol"] = symbol
    return s


def compute_cross_section_et(
    merged: pd.DataFrame,
    symbol: str,
    symbols_group: list[str],
    rolling_window: int,
) -> pd.DataFrame:
    g = merged[merged["product"].isin(symbols_group)].copy()
    g["group_mean"] = g.groupby("global_t")["mid_price"].transform("mean")
    s = g[g["product"] == symbol].copy().sort_values("global_t").reset_index(drop=True)
    s["theo"] = s["group_mean"]
    s["raw_e"] = s["mid_price"] - s["theo"]
    roll_std = s["raw_e"].rolling(window=rolling_window, min_periods=max(20, rolling_window // 5)).std()
    roll_std = roll_std.replace(0, np.nan)
    s["e_t"] = s["raw_e"] / roll_std
    s["symbol"] = symbol
    s["underlying_mid"] = np.nan
    s["intrinsic"] = np.nan
    return s


def day_boundaries(global_df: pd.DataFrame) -> list[int]:
    starts = global_df.groupby("day_idx")["global_t"].min().sort_values().tolist()
    return [int(x) for x in starts]


def plot_panel(
    et_df: pd.DataFrame,
    symbols: list[str],
    bounds: list[int],
    title: str,
    out_png: Path,
) -> None:
    n = len(symbols)
    cols = 2
    rows = math.ceil(n / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(16, 2.8 * rows), sharex=True)
    axes = np.array(axes).reshape(rows, cols)

    for i, symbol in enumerate(symbols):
        r, c = divmod(i, cols)
        ax = axes[r, c]
        s = et_df[et_df["symbol"] == symbol].copy()
        ax.plot(s["global_t"], s["e_t"], linewidth=0.8)
        ax.axhline(0.0, color="black", linewidth=0.8, alpha=0.7)
        for b in bounds[1:]:
            ax.axvline(b, color="gray", linestyle="--", linewidth=0.8, alpha=0.4)
        mean_v = s["e_t"].mean(skipna=True)
        med_v = s["e_t"].median(skipna=True)
        ax.set_title(f"{symbol} | mean={mean_v:.2f} | median={med_v:.2f}", fontsize=9)
        ax.grid(alpha=0.2, linewidth=0.5)
        ax.tick_params(axis="both", labelsize=7)

    # Hide unused subplots
    total = rows * cols
    for i in range(n, total):
        r, c = divmod(i, cols)
        axes[r, c].axis("off")

    # Day labels on bottom row only
    if bounds:
        max_t = et_df["global_t"].max()
        label_positions = []
        label_text = []
        for i, b in enumerate(bounds):
            next_b = bounds[i + 1] if i + 1 < len(bounds) else max_t + 1
            label_positions.append((b + next_b) / 2)
            label_text.append(f"Day {i + 1}")
        for c in range(cols):
            ax = axes[rows - 1, c]
            ax.set_xticks(label_positions)
            ax.set_xticklabels(label_text, fontsize=8)

    fig.suptitle(title, fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=160)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    price_files = [str(Path(p).resolve()) for p in args.prices]
    out_png = Path(args.out).resolve()
    out_csv = Path(args.out_csv).resolve() if args.out_csv else None

    all_prices = load_prices(price_files)
    if args.mode == "option_like":
        symbols = option_symbols(all_prices, args.prefix)
        if not symbols:
            raise ValueError(f"No option-like symbols found for prefix {args.prefix} (expected PREFIX_<number>)")
        if not args.underlying:
            raise ValueError("--underlying is required for --mode option_like")
        if args.underlying not in set(all_prices["product"].unique()):
            raise ValueError(f"Underlying symbol {args.underlying} not found in prices data")
    else:
        symbols = grouped_symbols(all_prices, args.prefix)
        if not symbols:
            raise ValueError(f"No grouped symbols found for prefix {args.prefix}")

    # Build a global timeline across files to get clean day boundaries on a single axis.
    frames = []
    global_offset = 0
    for day_idx, p in enumerate(price_files):
        day_df = pd.read_csv(p, sep=";")[["timestamp", "product", "mid_price"]].copy()
        ts_sorted = sorted(day_df["timestamp"].unique().tolist())
        ts_map = {t: i + global_offset for i, t in enumerate(ts_sorted)}
        day_df["global_t"] = day_df["timestamp"].map(ts_map)
        day_df["day_idx"] = day_idx
        frames.append(day_df)
        global_offset += len(ts_sorted)
    global_df = pd.concat(frames, ignore_index=True)

    if args.mode == "option_like":
        under = global_df[global_df["product"] == args.underlying][["global_t", "mid_price"]].rename(
            columns={"mid_price": "underlying_mid"}
        )
        merged = global_df.merge(under, on="global_t", how="left")
    else:
        merged = global_df.copy()

    out_series = []
    for symbol in symbols:
        if args.mode == "option_like":
            out_series.append(compute_et_for_symbol(merged, symbol, args.rolling_window))
        else:
            out_series.append(compute_cross_section_et(merged, symbol, symbols, args.rolling_window))
    et_df = pd.concat(out_series, ignore_index=True)
    bounds = day_boundaries(global_df)

    plot_panel(et_df, symbols, bounds, args.title, out_png)
    if out_csv:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        et_df[["global_t", "day_idx", "timestamp", "symbol", "mid_price", "underlying_mid", "intrinsic", "theo", "raw_e", "e_t"]].to_csv(out_csv, index=False)

    print(f"Wrote panel: {out_png}")
    if out_csv:
        print(f"Wrote series: {out_csv}")
    print(f"Mode: {args.mode}")
    print(f"Symbols: {symbols}")


if __name__ == "__main__":
    main()
