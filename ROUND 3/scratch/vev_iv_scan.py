"""
vev_iv_scan.py — Back out implied volatility from VEV market prices.

Usage:
    python "ROUND 3/scratch/vev_iv_scan.py"

Prints, for every (day, sample timestamp, strike) triple:
- market mid, Black-Scholes fair at a reference sigma, IV/day, BS delta.

The headline finding: IV is a flat ~1.26%/day across the chain while
realised volatility of VELVETFRUIT_EXTRACT is ~2.15%/day.
"""

from __future__ import annotations

import csv
import math
import os
import statistics
from pathlib import Path

from scipy.optimize import brentq
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
CAPSULE = HERE.parent / "data_capsule"

STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
TICKS_PER_DAY = 10_000  # timestamp step of 100 → 10_000 samples/day
TIMESTAMP_UNITS_PER_DAY = 1_000_000


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm.cdf(d1) - K * norm.cdf(d2)


def bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return norm.cdf(d1)


def implied_vol(S: float, K: float, T: float, market: float) -> float | None:
    intrinsic = max(S - K, 0.0)
    if market <= intrinsic + 1e-10:
        return None
    try:
        return brentq(lambda s: bs_call(S, K, T, s) - market, 1e-6, 5.0)
    except Exception:
        return None


def load_day(day: int) -> list[dict]:
    fname = CAPSULE / f"prices_round_3_day_{day}.csv"
    with open(fname) as f:
        return list(csv.DictReader(f, delimiter=";"))


def tte_days(day: int, timestamp: int) -> float:
    # TTE = 7 days starting from day 1 → 8 days as of day 0 timestamp 0.
    return (8 - day) - timestamp / TIMESTAMP_UNITS_PER_DAY


def realised_sigma_per_day() -> float:
    """Log-return stdev per tick × sqrt(ticks/day)."""
    prices = []
    for d in (0, 1, 2):
        for row in load_day(d):
            if row["product"] == "VELVETFRUIT_EXTRACT":
                prices.append(float(row["mid_price"]))
    log_returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
    return statistics.stdev(log_returns) * math.sqrt(TICKS_PER_DAY)


def scan():
    sigma_hist = realised_sigma_per_day()
    print(f"Historical VFE sigma per day: {sigma_hist:.5f} ({sigma_hist * 100:.3f}%)")
    print("-" * 72)

    for day in (0, 1, 2):
        rows = load_day(day)
        for sample_ts in (0,):
            vfe = next(
                (r for r in rows if r["product"] == "VELVETFRUIT_EXTRACT"
                 and int(r["timestamp"]) == sample_ts),
                None,
            )
            if vfe is None:
                continue
            S = float(vfe["mid_price"])
            T = tte_days(day, sample_ts)

            print(f"Day {day}, ts={sample_ts}: S={S:.2f}, TTE={T:.3f} days")
            print("  Strike | Market | BS(hist) | Edge   | IV/day | Δ")
            for K in STRIKES:
                row = next(
                    (r for r in rows if r["product"] == f"VEV_{K}"
                     and int(r["timestamp"]) == sample_ts),
                    None,
                )
                if row is None:
                    continue
                mp = float(row["mid_price"])
                fair = bs_call(S, K, T, sigma_hist)
                delta = bs_delta(S, K, T, sigma_hist)
                iv = implied_vol(S, K, T, mp)
                iv_str = f"{iv:.4f}" if iv else "  N/A "
                print(f"  VEV_{K:<4d}| {mp:6.2f} | {fair:8.2f} | {mp - fair:+6.2f} | {iv_str} | {delta:.3f}")
            print()


if __name__ == "__main__":
    scan()
