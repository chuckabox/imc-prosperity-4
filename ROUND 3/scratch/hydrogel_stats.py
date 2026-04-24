"""
hydrogel_stats.py — Characterise HYDROGEL_PACK for market-making.

Prints the mean, stdev, range, and Ornstein-Uhlenbeck mean-reversion
half-life of HYDROGEL_PACK across all 3 capsule days.

The half-life tells us how aggressively to skew quotes: short half-life →
price returns fast, take bigger positions against the dislocation.
"""

from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAPSULE = HERE.parent / "data_capsule"


def load_hp_prices() -> list[float]:
    prices: list[float] = []
    for day in (0, 1, 2):
        with open(CAPSULE / f"prices_round_3_day_{day}.csv") as f:
            for row in csv.DictReader(f, delimiter=";"):
                if row["product"] == "HYDROGEL_PACK":
                    prices.append(float(row["mid_price"]))
    return prices


def main():
    prices = load_hp_prices()
    print(f"N samples: {len(prices)}")
    print(f"Mean: {statistics.mean(prices):.2f}")
    print(f"Stdev: {statistics.stdev(prices):.2f}")
    print(f"Min / Max: {min(prices):.1f} / {max(prices):.1f}")
    print(f"Mean deviation from 10000: {statistics.mean(prices) - 10000:+.2f}")

    # OU estimate: Δp_t = -θ(p_{t-1} - μ) Δt + noise
    mean_p = statistics.mean(prices)
    diffs = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    devs = [prices[i - 1] - mean_p for i in range(1, len(prices))]
    n = len(diffs)
    cov_xy = sum(devs[i] * diffs[i] for i in range(n)) / n
    var_x = sum(d * d for d in devs) / n
    theta = -cov_xy / var_x
    half_life = math.log(2) / theta if theta > 0 else float("inf")
    print(f"OU theta (per tick): {theta:.6f}")
    print(f"Mean-reversion half-life: {half_life:.1f} ticks")


if __name__ == "__main__":
    main()
