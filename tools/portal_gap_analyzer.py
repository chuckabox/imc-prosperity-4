"""Analyze Prosperity portal/live fills against Round-3 market data.

Input formats supported (CSV):
1) Columns: timestamp, symbol, price, quantity, side
2) Columns: timestamp, product, price, quantity, side
3) Columns: timestamp, buyer, seller, symbol, price, quantity, trader
   (side inferred from trader == buyer/seller)

Example:
    python tools/portal_gap_analyzer.py ^
      --fills path/to/portal_fills.csv ^
      --prices "ROUND 3/data_capsule/prices_round_3_day_0.csv" "ROUND 3/data_capsule/prices_round_3_day_1.csv" "ROUND 3/data_capsule/prices_round_3_day_2.csv"
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd


@dataclass
class FillRow:
    timestamp: int
    symbol: str
    price: float
    quantity: int
    side: str  # BUY/SELL


def _normalize_fills(df: pd.DataFrame, trader_name: str | None) -> pd.DataFrame:
    cols = {c.lower(): c for c in df.columns}
    out = pd.DataFrame()

    # timestamp
    ts_col = cols.get("timestamp")
    if ts_col is None:
        raise ValueError("fills file needs 'timestamp' column")
    out["timestamp"] = pd.to_numeric(df[ts_col], errors="coerce").astype("Int64")

    # symbol/product
    sym_col = cols.get("symbol") or cols.get("product")
    if sym_col is None:
        raise ValueError("fills file needs 'symbol' or 'product' column")
    out["symbol"] = df[sym_col].astype(str)

    # price/qty
    price_col = cols.get("price")
    qty_col = cols.get("quantity") or cols.get("qty")
    if price_col is None or qty_col is None:
        raise ValueError("fills file needs 'price' and 'quantity' columns")
    out["price"] = pd.to_numeric(df[price_col], errors="coerce")
    out["quantity"] = pd.to_numeric(df[qty_col], errors="coerce").astype("Int64")

    # side
    side_col = cols.get("side")
    if side_col is not None:
        s = df[side_col].astype(str).str.upper().str.strip()
        s = s.replace({"B": "BUY", "S": "SELL"})
        out["side"] = s
    else:
        buyer_col = cols.get("buyer")
        seller_col = cols.get("seller")
        if buyer_col is None or seller_col is None or trader_name is None:
            raise ValueError(
                "fills file needs 'side' column OR (buyer/seller columns + --trader-name)"
            )
        buyer = df[buyer_col].astype(str)
        seller = df[seller_col].astype(str)
        side = np.where(buyer == trader_name, "BUY", np.where(seller == trader_name, "SELL", ""))
        out["side"] = side

    out = out.dropna(subset=["timestamp", "symbol", "price", "quantity"])
    out = out[out["side"].isin(["BUY", "SELL"])].copy()
    out["timestamp"] = out["timestamp"].astype(int)
    out["quantity"] = out["quantity"].astype(int)
    out["symbol"] = out["symbol"].str.strip()
    return out


def _load_prices(price_files: List[str]) -> pd.DataFrame:
    frames = []
    for f in price_files:
        x = pd.read_csv(f, sep=";")
        x = x[[
            "timestamp",
            "product",
            "bid_price_1",
            "ask_price_1",
            "mid_price",
            "bid_volume_1",
            "ask_volume_1",
        ]].copy()
        x["timestamp"] = pd.to_numeric(x["timestamp"], errors="coerce").astype("Int64")
        frames.append(x.dropna(subset=["timestamp"]))
    if not frames:
        raise ValueError("No valid price files loaded")
    p = pd.concat(frames, ignore_index=True)
    p["timestamp"] = p["timestamp"].astype(int)
    p = p.sort_values(["product", "timestamp"]).reset_index(drop=True)
    return p


def _asof_join(fills: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    chunks = []
    for sym, g in fills.groupby("symbol"):
        pg = prices[prices["product"] == sym].copy()
        if pg.empty:
            continue
        fg = g.sort_values("timestamp").copy()
        merged = pd.merge_asof(
            fg,
            pg.sort_values("timestamp"),
            on="timestamp",
            direction="backward",
            tolerance=500,  # half-second tolerance in IMC ticks
        )
        merged["symbol"] = sym
        chunks.append(merged)
    if not chunks:
        return pd.DataFrame()
    out = pd.concat(chunks, ignore_index=True)
    return out.dropna(subset=["bid_price_1", "ask_price_1", "mid_price"])


def _score(df: pd.DataFrame, prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    x = df.copy()
    x["spread"] = x["ask_price_1"] - x["bid_price_1"]
    x["is_buy"] = x["side"] == "BUY"

    # Effective edge relative to mid (positive is good for us).
    x["edge_vs_mid"] = np.where(x["is_buy"], x["mid_price"] - x["price"], x["price"] - x["mid_price"])

    # Aggressive/passive heuristics from top-of-book.
    x["is_taker"] = np.where(
        x["is_buy"],
        x["price"] >= x["ask_price_1"],
        x["price"] <= x["bid_price_1"],
    )
    x["is_maker"] = ~x["is_taker"]

    # Realized short-horizon move after fill using market data at t+50.
    fwd_chunks = []
    for sym, g in x.groupby("symbol"):
        pg = prices[prices["product"] == sym].sort_values("timestamp")
        if pg.empty:
            g2 = g.copy()
            g2["fwd_mid_50"] = np.nan
            fwd_chunks.append(g2)
            continue
        g2 = g.copy().sort_values("timestamp")
        g2["future_ts"] = g2["timestamp"] + 50
        g2 = pd.merge_asof(
            g2,
            pg[["timestamp", "mid_price"]].sort_values("timestamp").rename(columns={"timestamp": "future_ts", "mid_price": "fwd_mid_50"}),
            on="future_ts",
            direction="forward",
            tolerance=500,
        )
        fwd_chunks.append(g2)
    x = pd.concat(fwd_chunks, ignore_index=True) if fwd_chunks else x
    x["alpha_50"] = np.where(
        x["is_buy"],
        x["fwd_mid_50"] - x["price"],
        x["price"] - x["fwd_mid_50"],
    )

    by_symbol = (
        x.groupby("symbol")
        .agg(
            fills=("symbol", "size"),
            qty=("quantity", "sum"),
            taker_ratio=("is_taker", "mean"),
            avg_spread=("spread", "mean"),
            avg_edge_vs_mid=("edge_vs_mid", "mean"),
            avg_alpha_50=("alpha_50", "mean"),
        )
        .reset_index()
        .sort_values("avg_alpha_50", ascending=False)
    )

    overall = pd.DataFrame(
        {
            "metric": [
                "fills",
                "total_qty",
                "taker_ratio",
                "avg_spread",
                "avg_edge_vs_mid",
                "avg_alpha_50",
            ],
            "value": [
                int(len(x)),
                int(x["quantity"].sum()),
                float(x["is_taker"].mean()),
                float(x["spread"].mean()),
                float(x["edge_vs_mid"].mean()),
                float(x["alpha_50"].mean()),
            ],
        }
    )
    return overall, by_symbol


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze portal/live fill quality.")
    ap.add_argument("--fills", required=True, help="Path to portal/live fills CSV")
    ap.add_argument("--prices", nargs="+", required=True, help="One or more Round3 prices CSV files")
    ap.add_argument("--trader-name", default=None, help="Required only when side must be inferred from buyer/seller")
    args = ap.parse_args()

    fills_raw = pd.read_csv(args.fills)
    fills = _normalize_fills(fills_raw, trader_name=args.trader_name)
    prices = _load_prices(args.prices)
    joined = _asof_join(fills, prices)
    if joined.empty:
        print("No joined rows. Check symbols/timestamps and file format.")
        return

    overall, by_symbol = _score(joined, prices=prices)
    print("\n[OVERALL]")
    print(overall.to_string(index=False))
    print("\n[BY SYMBOL]")
    print(by_symbol.to_string(index=False))

    out_dir = os.path.join("tools", "out")
    os.makedirs(out_dir, exist_ok=True)
    overall.to_csv(os.path.join(out_dir, "portal_gap_overall.csv"), index=False)
    by_symbol.to_csv(os.path.join(out_dir, "portal_gap_by_symbol.csv"), index=False)
    print(f"\nSaved CSVs to {out_dir}")


if __name__ == "__main__":
    main()

