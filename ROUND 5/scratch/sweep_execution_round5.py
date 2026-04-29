from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_capsule"
SCRATCH = ROOT / "scratch"
DOCS = ROOT / "docs"


def load_day(day: int) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"prices_round_5_day_{day}.csv", sep=";")
    keep = ["timestamp", "product", "bid_price_1", "ask_price_1", "mid_price"]
    df = df[keep].copy().sort_values(["product", "timestamp"])
    df["dmid"] = df.groupby("product")["mid_price"].diff().fillna(0.0)
    df["spread"] = (df["ask_price_1"] - df["bid_price_1"]).clip(lower=1)
    return df


def eval_exec(
    df: pd.DataFrame,
    threshold: float,
    hold: int,
    spread_max: int,
    size_scale: float,
    taker_frac: float,
    ts_max: int | None = None,
) -> dict:
    d = df if ts_max is None else df[df["timestamp"] <= ts_max]
    x = d.copy()
    x = x[(x["dmid"].abs() >= threshold) & (x["spread"] <= spread_max)].copy()
    if x.empty:
        return {"trades": 0, "pnl_per_unit": 0.0, "gross_pnl": 0.0}

    x["sig"] = np.where(x["dmid"] <= -threshold, 1, -1)  # reversal
    x["exit_bid"] = x.groupby("product")["bid_price_1"].shift(-hold)
    x["exit_ask"] = x.groupby("product")["ask_price_1"].shift(-hold)
    x = x.dropna(subset=["exit_bid", "exit_ask"]).copy()
    if x.empty:
        return {"trades": 0, "pnl_per_unit": 0.0, "gross_pnl": 0.0}

    # Hybrid execution: fraction taker (cross spread), remainder passive (half spread cost assumption).
    half_spread = 0.5 * x["spread"]
    entry_cost = taker_frac * half_spread + (1.0 - taker_frac) * (0.25 * x["spread"])
    exit_cost = taker_frac * half_spread + (1.0 - taker_frac) * (0.25 * x["spread"])
    total_cost = entry_cost + exit_cost

    mid_move = np.where(
        x["sig"] > 0,
        x["exit_bid"] - x["mid_price"],  # conservative on long exit
        x["mid_price"] - x["exit_ask"],  # conservative on short exit
    )
    unit = mid_move - total_cost
    qty = np.maximum(1.0, np.abs(x["dmid"]) * size_scale)
    x["pnl"] = unit * qty

    return {
        "trades": int(x.shape[0]),
        "pnl_per_unit": float(unit.mean()),
        "gross_pnl": float(x["pnl"].sum()),
    }


def main() -> None:
    day_data = {d: load_day(d) for d in [2, 3, 4]}
    rows: list[dict] = []

    for hold in [1, 2, 3]:
        for spread_max in [8, 10, 12, 14, 16, 20]:
            for size_scale in [0.15, 0.25, 0.35, 0.5, 0.75, 1.0]:
                for taker_frac in [0.2, 0.4, 0.6, 0.8, 1.0]:
                    row = {
                        "threshold": 8.0,
                        "hold": hold,
                        "spread_max": spread_max,
                        "size_scale": size_scale,
                        "taker_frac": taker_frac,
                    }
                    for day in [2, 3, 4]:
                        m = eval_exec(
                            day_data[day],
                            threshold=8.0,
                            hold=hold,
                            spread_max=spread_max,
                            size_scale=size_scale,
                            taker_frac=taker_frac,
                        )
                        row[f"day{day}_pnl"] = m["gross_pnl"]
                        row[f"day{day}_trades"] = m["trades"]

                    d3_10 = eval_exec(
                        day_data[3],
                        threshold=8.0,
                        hold=hold,
                        spread_max=spread_max,
                        size_scale=size_scale,
                        taker_frac=taker_frac,
                        ts_max=99_900,
                    )
                    row["day3_10pct_pnl"] = d3_10["gross_pnl"]
                    row["day3_10pct_trades"] = d3_10["trades"]
                    row["total_3days"] = row["day2_pnl"] + row["day3_pnl"] + row["day4_pnl"]
                    row["score"] = (
                        0.55 * row["day3_10pct_pnl"]
                        + 0.15 * row["day2_pnl"]
                        + 0.15 * row["day3_pnl"]
                        + 0.15 * row["day4_pnl"]
                    )
                    rows.append(row)

    res = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    res.to_csv(SCRATCH / "round5_execution_sweep.csv", index=False)
    (SCRATCH / "round5_execution_sweep_top30.json").write_text(
        json.dumps(res.head(30).to_dict(orient="records"), indent=2),
        encoding="utf-8",
    )

    robust = res[
        (res["day2_pnl"] > 0)
        & (res["day3_pnl"] > 0)
        & (res["day4_pnl"] > 0)
        & (res["day3_10pct_pnl"] > 0)
        & (res["day3_10pct_trades"] >= 200)
    ].copy()
    robust = robust.sort_values("score", ascending=False).reset_index(drop=True)
    robust.to_csv(SCRATCH / "round5_execution_sweep_robust.csv", index=False)

    best = robust.iloc[0] if not robust.empty else res.iloc[0]
    md = [
        "# Round 5 Execution Sweep",
        "",
        "Signal fixed to robust alpha: `reversal` with threshold `8.0`.",
        "Swept execution knobs: hold, spread cap, size scale, taker/passive mix.",
        "",
        f"Best config ({'robust' if not robust.empty else 'overall'}):",
        f"- hold: {int(best['hold'])}",
        f"- spread_max: {int(best['spread_max'])}",
        f"- size_scale: {best['size_scale']}",
        f"- taker_frac: {best['taker_frac']}",
        f"- day3 first 10% pnl proxy: {best['day3_10pct_pnl']:.2f}",
        f"- day2/day3/day4 pnl proxy: {best['day2_pnl']:.2f} / {best['day3_pnl']:.2f} / {best['day4_pnl']:.2f}",
        f"- total 3 days pnl proxy: {best['total_3days']:.2f}",
        "",
        "Outputs:",
        "- `ROUND 5/scratch/round5_execution_sweep.csv`",
        "- `ROUND 5/scratch/round5_execution_sweep_top30.json`",
        "- `ROUND 5/scratch/round5_execution_sweep_robust.csv`",
    ]
    (DOCS / "ken_round5_execution_sweep.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("Wrote execution sweep outputs")
    print("Top 5 overall:")
    print(res.head(5)[["hold", "spread_max", "size_scale", "taker_frac", "day3_10pct_pnl", "total_3days", "score"]])
    if not robust.empty:
        print("Top 5 robust:")
        print(robust.head(5)[["hold", "spread_max", "size_scale", "taker_frac", "day3_10pct_pnl", "total_3days", "score"]])
    else:
        print("No robust positive-all-days set found in this grid.")


if __name__ == "__main__":
    main()
