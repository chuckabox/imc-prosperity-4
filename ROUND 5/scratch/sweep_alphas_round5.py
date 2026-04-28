from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_capsule"
SCRATCH = ROOT / "scratch"
DOCS = ROOT / "docs"

FAMILY_PREFIXES = [
    "PEBBLES",
    "SNACKPACK",
    "UV_VISOR",
    "GALAXY_SOUNDS",
    "MICROCHIP",
    "TRANSLATOR",
    "SLEEP_POD",
    "OXYGEN_SHAKE",
    "PANEL",
    "ROBOT",
]


def family_of(symbol: str) -> str:
    for prefix in FAMILY_PREFIXES:
        if symbol.startswith(prefix + "_"):
            return prefix
    return symbol.split("_", 1)[0]


def load_prices(day: int) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"prices_round_5_day_{day}.csv", sep=";")
    keep = ["timestamp", "product", "bid_price_1", "ask_price_1", "mid_price"]
    df = df[keep].copy().sort_values(["product", "timestamp"])
    df["family"] = df["product"].map(family_of)
    df["dmid"] = df.groupby("product")["mid_price"].diff().fillna(0.0)
    return df


def eval_reversal(df: pd.DataFrame, threshold: float, hold: int, ts_max: int | None = None) -> dict:
    d = df if ts_max is None else df[df["timestamp"] <= ts_max]
    x = d.copy()
    x["sig"] = np.where(x["dmid"] <= -threshold, 1, np.where(x["dmid"] >= threshold, -1, 0))
    x = x[x["sig"] != 0].copy()
    if x.empty:
        return {"trades": 0, "alpha_edge_per_unit": 0.0, "edge_per_unit": 0.0, "win_rate": 0.0, "gross_edge": 0.0}

    x["exit_mid"] = x.groupby("product")["mid_price"].shift(-hold)
    x["exit_bid"] = x.groupby("product")["bid_price_1"].shift(-hold)
    x["exit_ask"] = x.groupby("product")["ask_price_1"].shift(-hold)
    x = x.dropna(subset=["exit_mid", "exit_bid", "exit_ask"]).copy()
    if x.empty:
        return {"trades": 0, "alpha_edge_per_unit": 0.0, "edge_per_unit": 0.0, "win_rate": 0.0, "gross_edge": 0.0}

    # +1 signal => buy now at ask, sell later at bid
    # -1 signal => sell now at bid, buy later at ask
    x["unit_pnl"] = np.where(
        x["sig"] > 0,
        x["exit_bid"] - x["ask_price_1"],
        x["bid_price_1"] - x["exit_ask"],
    )
    x["alpha_unit"] = np.where(
        x["sig"] > 0,
        x["exit_mid"] - x["mid_price"],
        x["mid_price"] - x["exit_mid"],
    )
    return {
        "trades": int(x.shape[0]),
        "alpha_edge_per_unit": float(x["alpha_unit"].mean()),
        "edge_per_unit": float(x["unit_pnl"].mean()),
        "win_rate": float((x["unit_pnl"] > 0).mean()),
        "gross_edge": float(x["unit_pnl"].sum()),
    }


def eval_momentum(df: pd.DataFrame, threshold: float, hold: int, ts_max: int | None = None) -> dict:
    d = df if ts_max is None else df[df["timestamp"] <= ts_max]
    x = d.copy()
    x["sig"] = np.where(x["dmid"] <= -threshold, -1, np.where(x["dmid"] >= threshold, 1, 0))
    x = x[x["sig"] != 0].copy()
    if x.empty:
        return {"trades": 0, "alpha_edge_per_unit": 0.0, "edge_per_unit": 0.0, "win_rate": 0.0, "gross_edge": 0.0}

    x["exit_mid"] = x.groupby("product")["mid_price"].shift(-hold)
    x["exit_bid"] = x.groupby("product")["bid_price_1"].shift(-hold)
    x["exit_ask"] = x.groupby("product")["ask_price_1"].shift(-hold)
    x = x.dropna(subset=["exit_mid", "exit_bid", "exit_ask"]).copy()
    if x.empty:
        return {"trades": 0, "alpha_edge_per_unit": 0.0, "edge_per_unit": 0.0, "win_rate": 0.0, "gross_edge": 0.0}

    x["unit_pnl"] = np.where(
        x["sig"] > 0,
        x["exit_bid"] - x["ask_price_1"],
        x["bid_price_1"] - x["exit_ask"],
    )
    x["alpha_unit"] = np.where(
        x["sig"] > 0,
        x["exit_mid"] - x["mid_price"],
        x["mid_price"] - x["exit_mid"],
    )
    return {
        "trades": int(x.shape[0]),
        "alpha_edge_per_unit": float(x["alpha_unit"].mean()),
        "edge_per_unit": float(x["unit_pnl"].mean()),
        "win_rate": float((x["unit_pnl"] > 0).mean()),
        "gross_edge": float(x["unit_pnl"].sum()),
    }


def eval_cross_section(df: pd.DataFrame, z_th: float, hold: int, ts_max: int | None = None) -> dict:
    d = df if ts_max is None else df[df["timestamp"] <= ts_max]
    x = d.copy()
    mu = x.groupby(["timestamp", "family"])["mid_price"].transform("mean")
    sd = x.groupby(["timestamp", "family"])["mid_price"].transform("std").fillna(1.0).replace(0, 1.0)
    x["z"] = (x["mid_price"] - mu) / sd
    x["sig"] = np.where(x["z"] <= -z_th, 1, np.where(x["z"] >= z_th, -1, 0))
    x = x[x["sig"] != 0].copy()
    if x.empty:
        return {"trades": 0, "alpha_edge_per_unit": 0.0, "edge_per_unit": 0.0, "win_rate": 0.0, "gross_edge": 0.0}

    x["exit_mid"] = x.groupby("product")["mid_price"].shift(-hold)
    x["exit_bid"] = x.groupby("product")["bid_price_1"].shift(-hold)
    x["exit_ask"] = x.groupby("product")["ask_price_1"].shift(-hold)
    x = x.dropna(subset=["exit_mid", "exit_bid", "exit_ask"]).copy()
    if x.empty:
        return {"trades": 0, "alpha_edge_per_unit": 0.0, "edge_per_unit": 0.0, "win_rate": 0.0, "gross_edge": 0.0}

    x["unit_pnl"] = np.where(
        x["sig"] > 0,
        x["exit_bid"] - x["ask_price_1"],
        x["bid_price_1"] - x["exit_ask"],
    )
    x["alpha_unit"] = np.where(
        x["sig"] > 0,
        x["exit_mid"] - x["mid_price"],
        x["mid_price"] - x["exit_mid"],
    )
    return {
        "trades": int(x.shape[0]),
        "alpha_edge_per_unit": float(x["alpha_unit"].mean()),
        "edge_per_unit": float(x["unit_pnl"].mean()),
        "win_rate": float((x["unit_pnl"] > 0).mean()),
        "gross_edge": float(x["unit_pnl"].sum()),
    }


def rows_for_strategy(
    day_data: dict[int, pd.DataFrame],
    strategy: str,
    grid_values: Iterable[tuple[float, int]],
) -> list[dict]:
    out = []
    for p1, hold in grid_values:
        row = {"strategy": strategy, "p1": p1, "hold": hold}
        all_days = {}
        for day in [2, 3, 4]:
            if strategy == "reversal":
                m = eval_reversal(day_data[day], threshold=p1, hold=hold)
            elif strategy == "momentum":
                m = eval_momentum(day_data[day], threshold=p1, hold=hold)
            else:
                m = eval_cross_section(day_data[day], z_th=p1, hold=hold)
            all_days[day] = m
            row[f"day{day}_alpha"] = m["alpha_edge_per_unit"]
            row[f"day{day}_edge"] = m["edge_per_unit"]
            row[f"day{day}_trades"] = m["trades"]

        d3_10 = (
            eval_reversal(day_data[3], p1, hold, ts_max=99_900)
            if strategy == "reversal"
            else eval_momentum(day_data[3], p1, hold, ts_max=99_900)
            if strategy == "momentum"
            else eval_cross_section(day_data[3], p1, hold, ts_max=99_900)
        )
        row["day3_10pct_alpha"] = d3_10["alpha_edge_per_unit"]
        row["day3_10pct_edge"] = d3_10["edge_per_unit"]
        row["day3_10pct_trades"] = d3_10["trades"]
        row["alpha_score"] = (
            0.45 * row["day3_10pct_alpha"]
            + 0.20 * row["day2_alpha"]
            + 0.20 * row["day3_alpha"]
            + 0.15 * row["day4_alpha"]
        )
        row["trade_score"] = (
            0.45 * row["day3_10pct_edge"]
            + 0.20 * row["day2_edge"]
            + 0.20 * row["day3_edge"]
            + 0.15 * row["day4_edge"]
        )
        row["score"] = row["alpha_score"]
        out.append(row)
    return out


def main() -> None:
    day_data = {day: load_prices(day) for day in [2, 3, 4]}

    reversal_grid = [(th, hold) for th in [2, 4, 6, 8, 10, 12, 14, 16] for hold in [1, 2, 3]]
    momentum_grid = [(th, hold) for th in [2, 4, 6, 8, 10, 12, 14, 16] for hold in [1, 2, 3]]
    cross_grid = [(z, hold) for z in [0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0] for hold in [1, 2, 3]]

    rows: list[dict] = []
    rows.extend(rows_for_strategy(day_data, "reversal", reversal_grid))
    rows.extend(rows_for_strategy(day_data, "momentum", momentum_grid))
    rows.extend(rows_for_strategy(day_data, "cross_section", cross_grid))

    res = pd.DataFrame(rows)
    res = res[res["day3_10pct_trades"] >= 200].copy()
    res = res.sort_values("score", ascending=False).reset_index(drop=True)
    out_csv = SCRATCH / "round5_alpha_sweep.csv"
    res.to_csv(out_csv, index=False)

    top = res.head(25).to_dict(orient="records")
    out_json = SCRATCH / "round5_alpha_sweep_top25.json"
    out_json.write_text(json.dumps(top, indent=2), encoding="utf-8")

    best = res.iloc[0]
    md_lines = [
        "# Round 5 Alpha Sweep",
        "",
        "Ranked on weighted alpha score (mid-to-mid edge per unit):",
        "- 45% day3 first 10% alpha edge",
        "- 20% day2 full alpha edge",
        "- 20% day3 full alpha edge",
        "- 15% day4 full alpha edge",
        "",
        f"Best setup: `{best['strategy']}` p1={best['p1']} hold={int(best['hold'])}",
        f"- day3 first 10% alpha edge/unit: {best['day3_10pct_alpha']:.4f} ({int(best['day3_10pct_trades'])} trades)",
        f"- day2 alpha edge/unit: {best['day2_alpha']:.4f}",
        f"- day3 alpha edge/unit: {best['day3_alpha']:.4f}",
        f"- day4 alpha edge/unit: {best['day4_alpha']:.4f}",
        f"- day3 first 10% tradeable edge/unit (cross spread): {best['day3_10pct_edge']:.4f}",
        "",
        "Top 10 parameter sets are saved in CSV/JSON under `ROUND 5/scratch`.",
    ]
    (DOCS / "ken_round5_alpha_sweep.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"Wrote {out_csv}")
    print(f"Wrote {out_json}")
    print(f"Wrote {DOCS / 'ken_round5_alpha_sweep.md'}")
    print("Top 5:")
    print(
        res.head(5)[
            [
                "strategy",
                "p1",
                "hold",
                "score",
                "day3_10pct_alpha",
                "day3_10pct_edge",
                "day2_alpha",
                "day3_alpha",
                "day4_alpha",
            ]
        ]
    )


if __name__ == "__main__":
    main()
