from __future__ import annotations

from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "ROUND 4" / "data_capsule"


def read(day: int):
    p = pd.read_csv(DATASET / f"prices_round_4_day_{day}.csv", sep=";")
    t = pd.read_csv(DATASET / f"trades_round_4_day_{day}.csv", sep=";")
    return p, t


def scan(day: int, symbol: str, horizons=(20, 50, 100)) -> None:
    prices, trades = read(day)
    g = prices[prices["product"] == symbol][["timestamp", "mid_price"]].copy().sort_values("timestamp")
    g["mid_price"] = g["mid_price"].astype(float)
    tr = trades[trades["symbol"] == symbol].copy().sort_values("timestamp")
    if tr.empty:
        print(f"\nDAY {day} {symbol}: no trades")
        return
    tr["side"] = 0
    # heuristic: buyer initiating -> bullish, seller initiating -> bearish. We don't know aggressor,
    # but splitting by recurring counterparties is still informative enough for conditional forward returns.
    tr.loc[tr["buyer"].notna(), "side"] += 1
    tr.loc[tr["seller"].notna(), "side"] -= 1
    merged = tr.merge(g, on="timestamp", how="left")
    for h in horizons:
        shifted = g[["timestamp", "mid_price"]].copy()
        shifted["fwd"] = shifted["mid_price"].shift(-h) - shifted["mid_price"]
        merged_h = merged.merge(shifted[["timestamp", "fwd"]], on="timestamp", how="left")
        print(f"\nDAY {day} {symbol} horizon {h}")
        by_buyer = merged_h.groupby("buyer")["fwd"].mean().sort_values()
        by_seller = merged_h.groupby("seller")["fwd"].mean().sort_values()
        print("best buyer-conditioned bearish fwd:")
        print(by_buyer.head(5).to_string())
        print("best seller-conditioned bullish fwd:")
        print(by_seller.tail(5).to_string())


def main():
    for day in [1, 2, 3]:
        for symbol in ["VELVETFRUIT_EXTRACT", "HYDROGEL_PACK", "VEV_5300", "VEV_5400"]:
            scan(day, symbol)


if __name__ == "__main__":
    main()

