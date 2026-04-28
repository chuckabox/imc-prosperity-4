#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
PRICES = [
    REPO_ROOT / "ROUND 5" / "data_capsule" / "prices_round_5_day_2.csv",
    REPO_ROOT / "ROUND 5" / "data_capsule" / "prices_round_5_day_3.csv",
    REPO_ROOT / "ROUND 5" / "data_capsule" / "prices_round_5_day_4.csv",
]
OUT_DIR = REPO_ROOT / "ROUND 5" / "docs" / "item_over_time"


def day_num_from_name(path: Path, fallback: int) -> int:
    m = re.search(r"day_(\d+)\.csv$", path.name)
    return int(m.group(1)) if m else fallback


def load_data() -> pd.DataFrame:
    frames = []
    for i, p in enumerate(PRICES):
        d = pd.read_csv(p, sep=";")[["timestamp", "product", "bid_price_1", "ask_price_1", "mid_price"]].copy()
        d["day_idx"] = i
        d["day_num"] = day_num_from_name(p, i)
        d["spread"] = d["ask_price_1"] - d["bid_price_1"]
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


def slug(s: str) -> str:
    return s.lower().replace("__", "_")


def plot_symbol(df: pd.DataFrame, symbol: str, out_path: Path) -> None:
    s = df[df["product"] == symbol].sort_values(["day_idx", "timestamp"]).copy()
    if s.empty:
        return

    s["e_t"] = np.nan
    for day_idx, g in s.groupby("day_idx"):
        raw = g["mid_price"] - g["mid_price"].rolling(200, min_periods=30).mean()
        std = raw.rolling(200, min_periods=30).std().replace(0, np.nan)
        s.loc[g.index, "e_t"] = raw / std

    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=False)
    ax1, ax2, ax3 = axes

    for day_idx, g in s.groupby("day_idx"):
        day_num = int(g["day_num"].iloc[0])
        ax1.plot(g["timestamp"], g["mid_price"], lw=0.9, label=f"Day {day_num}")
        ax2.plot(g["timestamp"], g["spread"], lw=0.9, label=f"Day {day_num}")
        ax3.plot(g["timestamp"], g["e_t"], lw=0.9, label=f"Day {day_num}")

    ax1.set_title(f"{symbol} mid price over time")
    ax2.set_title(f"{symbol} spread over time")
    ax3.set_title(f"{symbol} normalized e_t over time")
    ax1.set_ylabel("Mid")
    ax2.set_ylabel("Spread")
    ax3.set_ylabel("e_t")
    ax3.set_xlabel("Timestamp")
    ax3.axhline(0.0, color="black", lw=0.8, alpha=0.6)
    for ax in axes:
        ax.grid(alpha=0.2)
        ax.legend(fontsize=8)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def main() -> None:
    df = load_data()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    symbols = sorted(df["product"].dropna().unique().tolist())
    for sym in symbols:
        out = OUT_DIR / f"{slug(sym)}__item_over_time.png"
        plot_symbol(df, sym, out)
    (OUT_DIR / "manifest.txt").write_text(f"generated={len(symbols)}\n", encoding="utf-8")
    print(f"Generated {len(symbols)} item-over-time charts in {OUT_DIR}")


if __name__ == "__main__":
    main()
