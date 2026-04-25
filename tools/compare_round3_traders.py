#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO_ROOT / "external" / "prosperity_rust_backtester" / "runs"
DEFAULT_DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"


@dataclass
class TraderResult:
    trader: str
    day0: float
    day1: float
    day2: float
    total: float
    trades: int
    run_prefix: str


def _run_backtest(trader_rel: str, dataset_rel: str) -> tuple[str, str]:
    cmd = [
        sys.executable,
        "tools/run_prosperity4bt.py",
        "--trader",
        trader_rel,
        "--dataset",
        dataset_rel,
        "--no-progress",
    ]
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Backtest failed for {trader_rel}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout, proc.stderr


def _extract_run_prefix(stdout: str) -> str:
    # Example: p4bt-1777075579116-data-capsule-day-0
    m = re.search(r"p4bt-\d+-[a-zA-Z0-9\-]+-day-0", stdout)
    if not m:
        raise RuntimeError(f"Could not extract run prefix from output:\n{stdout}")
    return m.group(0).rsplit("-day-", 1)[0]


def _load_metrics(run_prefix: str) -> List[dict]:
    metrics = []
    for day in (0, 1, 2):
        p = RUNS_DIR / f"{run_prefix}-day-{day}" / "metrics.json"
        if not p.is_file():
            raise RuntimeError(f"Missing metrics file: {p}")
        metrics.append(json.loads(p.read_text(encoding="utf-8")))
    return metrics


def _summarize(trader_rel: str, run_prefix: str) -> TraderResult:
    ms = _load_metrics(run_prefix)
    day_vals = [float(m["final_pnl_total"]) for m in ms]
    total = sum(day_vals)
    trades = sum(int(m.get("own_trade_count", 0)) for m in ms)
    return TraderResult(
        trader=trader_rel,
        day0=day_vals[0],
        day1=day_vals[1],
        day2=day_vals[2],
        total=total,
        trades=trades,
        run_prefix=run_prefix,
    )


def _fmt(x: float) -> str:
    return f"{x:,.0f}"


def _print_table(results: List[TraderResult]) -> None:
    results = sorted(results, key=lambda r: r.total, reverse=True)
    print()
    print("Fresh Round 3 Comparison (uncached)")
    print("-" * 116)
    print(
        f"{'Trader':52} {'Day0':>10} {'Day1':>10} {'Day2':>10} {'Total':>11} {'Trades':>9} {'Run Prefix':>12}"
    )
    print("-" * 116)
    for r in results:
        print(
            f"{r.trader[:52]:52} {_fmt(r.day0):>10} {_fmt(r.day1):>10} {_fmt(r.day2):>10} {_fmt(r.total):>11} {r.trades:>9} {r.run_prefix[-10:]:>12}"
        )
    print("-" * 116)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a fresh, uncached comparison across Round 3 traders."
    )
    parser.add_argument(
        "--dataset",
        default=str(DEFAULT_DATASET.relative_to(REPO_ROOT)).replace("\\", "/"),
        help="Dataset directory relative to repo root (default: ROUND 3/data_capsule)",
    )
    parser.add_argument(
        "traders",
        nargs="+",
        help="Trader file paths relative to repo root",
    )
    args = parser.parse_args()

    results: List[TraderResult] = []
    for trader in args.traders:
        out, _ = _run_backtest(trader, args.dataset)
        prefix = _extract_run_prefix(out)
        results.append(_summarize(trader, prefix))

    _print_table(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

