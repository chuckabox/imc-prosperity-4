"""
2D Parameter Sweep for Robust Strategy Optimization
=====================================================
Sweeps key parameters of trader_robust.py across ALL scenarios,
producing heatmaps and Pareto frontier scatter plots.

Usage:
    python param_sweep.py                          # Full sweep
    python param_sweep.py --quick                  # Fast subset
    python param_sweep.py --plot-only results.csv  # Re-plot existing results
"""

import sys
import os
import json
import math
import copy
import argparse
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Dict, List, Tuple
from itertools import product as itertools_product

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
OUTPUT_DIR = SCRIPT_DIR / "sweep_results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT / "config"))

from robust_backtester import discover_datasets, run_backtest_on_csv


SWEEP_PARAMS = {
    "ema_fast_span": [5, 8, 12, 16],
    "ema_slow_span": [25, 40, 60],
    "trend_mult": [3.0, 6.0, 10.0],
    "inv_skew": [0.02, 0.03, 0.05, 0.08],
    "passive_size": [10, 15, 20, 25],
    "osm_take_margin": [1.5, 2.0, 3.0, 4.0],
}


def evaluate_params(params: Dict, datasets: List, trader_file: str) -> Dict:
    """Run the trader across all datasets with given parameter overrides."""
    pnls = []
    for name, path, category in datasets:
        result = run_backtest_on_csv(trader_file, path, name, category)
        if result:
            pnls.append(result.final_pnl)

    if not pnls:
        return {"mean_pnl": 0, "worst_pnl": 0, "std_pnl": 0, "win_rate": 0}

    return {
        "mean_pnl": float(np.mean(pnls)),
        "median_pnl": float(np.median(pnls)),
        "worst_pnl": float(np.min(pnls)),
        "best_pnl": float(np.max(pnls)),
        "std_pnl": float(np.std(pnls)),
        "win_rate": sum(1 for p in pnls if p > 0) / len(pnls),
        "n": len(pnls),
    }


def run_2d_sweep(param_a: str, param_b: str, datasets: List, quick: bool = False) -> pd.DataFrame:
    """Sweep two parameters and return results grid."""
    vals_a = SWEEP_PARAMS[param_a]
    vals_b = SWEEP_PARAMS[param_b]
    trader_file = str(PROJECT_ROOT / "traders" / "trader_robust.py")

    rows = []
    total = len(vals_a) * len(vals_b)
    count = 0

    for va in vals_a:
        for vb in vals_b:
            count += 1
            print(f"  [{count}/{total}] {param_a}={va}, {param_b}={vb}")

            stats = evaluate_params(
                {param_a: va, param_b: vb},
                datasets,
                trader_file,
            )
            rows.append({
                param_a: va,
                param_b: vb,
                **stats,
            })

    return pd.DataFrame(rows)


def plot_heatmap(df: pd.DataFrame, param_a: str, param_b: str, metric: str = "mean_pnl"):
    """Plot 2D heatmap of param sweep results."""
    pivot = df.pivot(index=param_b, columns=param_a, values=metric)

    fig, ax = plt.subplots(figsize=(10, 7))
    im = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto")

    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{v}" for v in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"{v}" for v in pivot.index])
    ax.set_xlabel(param_a)
    ax.set_ylabel(param_b)
    ax.set_title(f"{metric} Heatmap: {param_a} vs {param_b}")

    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            color = "white" if abs(val) > (pivot.values.max() - pivot.values.min()) * 0.5 else "black"
            ax.text(j, i, f"${val:,.0f}", ha="center", va="center", fontsize=8, color=color)

    fig.colorbar(im, ax=ax, label=metric)
    plt.tight_layout()

    out = OUTPUT_DIR / f"heatmap_{param_a}_vs_{param_b}_{metric}.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


def plot_pareto(df: pd.DataFrame, param_a: str, param_b: str):
    """Scatter: mean PNL vs worst-case PNL (Pareto frontier)."""
    fig, ax = plt.subplots(figsize=(10, 7))

    sc = ax.scatter(
        df["mean_pnl"], df["worst_pnl"],
        c=df["win_rate"], cmap="coolwarm", s=80, edgecolors="black", linewidths=0.5,
    )
    fig.colorbar(sc, ax=ax, label="Win Rate")

    for _, row in df.iterrows():
        label = f"({row[param_a]}, {row[param_b]})"
        ax.annotate(label, (row["mean_pnl"], row["worst_pnl"]),
                    fontsize=6, alpha=0.7, xytext=(5, 5), textcoords="offset points")

    ax.set_xlabel("Mean PnL (higher = better)")
    ax.set_ylabel("Worst-Case PnL (higher = safer)")
    ax.set_title(f"Pareto Frontier: {param_a} vs {param_b}")
    ax.axhline(0, color="grey", linestyle=":", linewidth=0.8)
    ax.axvline(0, color="grey", linestyle=":", linewidth=0.8)

    plt.tight_layout()
    out = OUTPUT_DIR / f"pareto_{param_a}_vs_{param_b}.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


def plot_distribution(results_csv: str):
    """Plot PNL distribution from a robust_results CSV."""
    df = pd.read_csv(results_csv)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    for ax, metric, title, color in [
        (axes[0], "final_pnl", "PnL Distribution Across All Scenarios", "#2ecc71"),
        (axes[1], "max_drawdown", "Max Drawdown Distribution", "#e74c3c"),
    ]:
        if metric not in df.columns:
            continue
        vals = df[metric].dropna()
        ax.hist(vals, bins=30, color=color, edgecolor="black", alpha=0.8)
        ax.axvline(vals.mean(), color="navy", linestyle="--", linewidth=2,
                   label=f"Mean: ${vals.mean():,.0f}")
        ax.axvline(vals.median(), color="orange", linestyle="--", linewidth=2,
                   label=f"Median: ${vals.median():,.0f}")
        ax.set_title(title)
        ax.set_xlabel(metric.replace("_", " ").title())
        ax.set_ylabel("Count")
        ax.legend()

    plt.tight_layout()
    out = OUTPUT_DIR / "pnl_distribution.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


def main():
    parser = argparse.ArgumentParser(description="2D Parameter Sweep")
    parser.add_argument("--quick", action="store_true", help="Quick mode (fewer datasets)")
    parser.add_argument("--plot-only", type=str, default=None, help="Plot existing results CSV")
    parser.add_argument("--param-a", type=str, default="passive_size", help="First sweep parameter")
    parser.add_argument("--param-b", type=str, default="inv_skew", help="Second sweep parameter")
    args = parser.parse_args()

    if args.plot_only:
        plot_distribution(args.plot_only)
        return

    datasets = discover_datasets(quick=True)
    print(f"Sweeping {args.param_a} vs {args.param_b} across {len(datasets)} datasets")

    df = run_2d_sweep(args.param_a, args.param_b, datasets, quick=args.quick)

    csv_path = OUTPUT_DIR / f"sweep_{args.param_a}_vs_{args.param_b}.csv"
    df.to_csv(csv_path, index=False)
    print(f"\nResults saved to: {csv_path}")

    print("\nGenerating plots...")
    plot_heatmap(df, args.param_a, args.param_b, "mean_pnl")
    plot_heatmap(df, args.param_a, args.param_b, "worst_pnl")
    plot_pareto(df, args.param_a, args.param_b)

    robust_csv = SCRIPT_DIR / "trader_robust_robust_results.csv"
    if robust_csv.exists():
        plot_distribution(str(robust_csv))

    print("\nBest by mean PnL:")
    best = df.sort_values("mean_pnl", ascending=False).head(5)
    print(best[[args.param_a, args.param_b, "mean_pnl", "worst_pnl", "win_rate"]].to_string(index=False))

    print("\nBest by worst-case PnL:")
    safest = df.sort_values("worst_pnl", ascending=False).head(5)
    print(safest[[args.param_a, args.param_b, "mean_pnl", "worst_pnl", "win_rate"]].to_string(index=False))


if __name__ == "__main__":
    main()
