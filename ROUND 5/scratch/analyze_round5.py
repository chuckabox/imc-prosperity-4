from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1] / "data_capsule"


@dataclass
class SignalResult:
    day: int
    timestamp: int
    product: str
    side: str
    z: float
    next_ret: float
    score: float


def load_prices(day: int) -> pd.DataFrame:
    df = pd.read_csv(ROOT / f"prices_round_5_day_{day}.csv", sep=";")
    keep = [
        "day",
        "timestamp",
        "product",
        "bid_price_1",
        "ask_price_1",
        "mid_price",
    ]
    df = df[keep].copy()
    df["family"] = df["product"].str.rsplit("_", n=1).str[0]
    df["suffix"] = df["product"].str.rsplit("_", n=1).str[-1]
    return df


def make_features(df: pd.DataFrame) -> pd.DataFrame:
    fam_mean = df.groupby(["timestamp", "family"])["mid_price"].transform("mean")
    fam_std = df.groupby(["timestamp", "family"])["mid_price"].transform("std").fillna(1.0)
    fam_std = fam_std.replace(0, 1.0)
    df["cross_z"] = (df["mid_price"] - fam_mean) / fam_std
    df = df.sort_values(["product", "timestamp"]).copy()
    df["ret_1"] = df.groupby("product")["mid_price"].pct_change().fillna(0.0)
    df["mom_5"] = df.groupby("product")["mid_price"].pct_change(5).fillna(0.0)
    df["next_ret_1"] = df.groupby("product")["ret_1"].shift(-1).fillna(0.0)
    return df


def evaluate_cross_section_signal(df: pd.DataFrame) -> dict:
    test = df.copy()
    test["signal"] = np.where(test["cross_z"] > 1.4, -1, np.where(test["cross_z"] < -1.4, 1, 0))
    test["edge"] = test["signal"] * test["next_ret_1"]
    active = test[test["signal"] != 0]
    return {
        "trades": int(active.shape[0]),
        "mean_edge_bps": float(active["edge"].mean() * 1e4) if not active.empty else 0.0,
        "win_rate": float((active["edge"] > 0).mean()) if not active.empty else 0.0,
    }


def pick_manual_trades(df: pd.DataFrame, day: int, only_first_10pct: bool = False) -> list[dict]:
    ts_max = int(df["timestamp"].max())
    cutoff = ts_max // 10 if only_first_10pct else ts_max
    c = df[(df["timestamp"] <= cutoff) & (df["cross_z"].abs() >= 2.1)].copy()
    if c.empty:
        return []
    c["side"] = np.where(c["cross_z"] < 0, "BUY", "SELL")
    c["score"] = c["cross_z"].abs() * (1 + c["mom_5"].abs() * 120)
    c = c.sort_values("score", ascending=False).head(25)
    out: list[dict] = []
    for _, r in c.iterrows():
        out.append(
            {
                "day": day,
                "timestamp": int(r["timestamp"]),
                "product": str(r["product"]),
                "family": str(r["family"]),
                "action": str(r["side"]),
                "mid": float(r["mid_price"]),
                "cross_z": float(r["cross_z"]),
                "mom_5": float(r["mom_5"]),
            }
        )
    return out


def main() -> None:
    results = {"signal_quality": {}, "manual_trade_candidates": {}, "family_volatility": {}}
    for day in (2, 3, 4):
        df = make_features(load_prices(day))
        results["signal_quality"][f"day_{day}"] = evaluate_cross_section_signal(df)
        first10 = pick_manual_trades(df, day, only_first_10pct=True)
        full_day = pick_manual_trades(df, day, only_first_10pct=False)
        results["manual_trade_candidates"][f"day_{day}_first10pct"] = first10[:10]
        results["manual_trade_candidates"][f"day_{day}_full"] = full_day[:10]
        fam_vol = (
            df.groupby("family")["ret_1"]
            .std()
            .sort_values(ascending=False)
            .head(10)
            .mul(1e4)
            .round(3)
            .to_dict()
        )
        results["family_volatility"][f"day_{day}_top"] = fam_vol

    out_path = Path(__file__).resolve().parent / "round5_analysis_summary.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
