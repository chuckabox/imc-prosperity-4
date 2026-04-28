from __future__ import annotations

from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "ROUND 4" / "data_capsule"


def read_prices(day: int) -> pd.DataFrame:
    return pd.read_csv(DATASET / f"prices_round_4_day_{day}.csv", sep=";")


def best_round_trip(g: pd.DataFrame):
    # Long: buy first, sell later
    mids = g["mid_price"].astype(float).tolist()
    ts = g["timestamp"].astype(int).tolist()
    best_long = None
    min_px = mids[0]
    min_ts = ts[0]
    for t, px in zip(ts[1:], mids[1:]):
        pnl = px - min_px
        if best_long is None or pnl > best_long[0]:
            best_long = (pnl, min_ts, t, min_px, px)
        if px < min_px:
            min_px, min_ts = px, t

    # Short: sell first, buy later
    best_short = None
    max_px = mids[0]
    max_ts = ts[0]
    for t, px in zip(ts[1:], mids[1:]):
        pnl = max_px - px
        if best_short is None or pnl > best_short[0]:
            best_short = (pnl, max_ts, t, max_px, px)
        if px > max_px:
            max_px, max_ts = px, t
    return best_long, best_short


def print_probe(day: int, cutoff: int, symbols: list[str]) -> None:
    df = read_prices(day)
    print(f"\n=== Day {day} manual probe until {cutoff} ===")
    for sym in symbols:
        g = df[(df["product"] == sym) & (df["timestamp"] <= cutoff)].copy().sort_values("timestamp")
        if g.empty:
            continue
        long_trip, short_trip = best_round_trip(g)
        print(f"\n{sym}")
        if long_trip:
            pnl, t0, t1, p0, p1 = long_trip
            print(f"  best LONG  : buy {p0:.1f} @ {t0}, sell {p1:.1f} @ {t1}, pnl={pnl:.1f}")
        if short_trip:
            pnl, t0, t1, p0, p1 = short_trip
            print(f"  best SHORT : sell {p0:.1f} @ {t0}, buy {p1:.1f} @ {t1}, pnl={pnl:.1f}")


def main() -> None:
    print_probe(3, 100_000, [
        "VELVETFRUIT_EXTRACT",
        "HYDROGEL_PACK",
        "VEV_5000",
        "VEV_5200",
        "VEV_5300",
        "VEV_5400",
        "VEV_5500",
    ])
    print_probe(1, 1_000_000, [
        "VELVETFRUIT_EXTRACT",
        "HYDROGEL_PACK",
        "VEV_5000",
        "VEV_5200",
        "VEV_5300",
        "VEV_5400",
    ])
    print_probe(2, 1_000_000, [
        "VELVETFRUIT_EXTRACT",
        "HYDROGEL_PACK",
        "VEV_5000",
        "VEV_5200",
        "VEV_5300",
        "VEV_5400",
    ])


if __name__ == "__main__":
    main()

