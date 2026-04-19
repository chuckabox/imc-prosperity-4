#!/usr/bin/env python3
"""Quickly backtest multiple traders on both engines (Rust + prosperity4bt) and
dump all results into the shared runs directory the dashboard reads.

    python tools/compare_rust.py ROUND\ 2/traders/ken/trader_ken_v6.py ROUND\ 2/traders/peter/trader_peter_v2000.py
    python tools/compare_rust.py --rust-only trader_a.py trader_b.py
    python tools/compare_rust.py --p4bt-only --day 1 trader_a.py

View the merged leaderboard (both engines) under the dashboard's 'Rust Backtester' tab.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run multiple traders through Rust and/or prosperity4bt and merge results.")
    parser.add_argument("traders", nargs="+", help="Trader .py files to backtest.")
    parser.add_argument("--dataset", default="ROUND 2/data_capsule", help="Dataset directory.")
    parser.add_argument("--day", type=int, default=None, help="Specific day (default: every day in dataset).")
    parser.add_argument("--rust-only", action="store_true", help="Skip prosperity4bt, run only the Rust engine.")
    parser.add_argument("--p4bt-only", action="store_true", help="Skip Rust, run only prosperity4bt.")
    parser.add_argument("--use-wsl", action="store_true", help="Pass --use-wsl to the Rust launcher (Windows only).")

    args = parser.parse_args()
    if args.rust_only and args.p4bt_only:
        print("ERROR: --rust-only and --p4bt-only are mutually exclusive.", file=sys.stderr)
        return 2

    run_rust = not args.p4bt_only
    run_p4bt = not args.rust_only

    rc = 0
    for trader in args.traders:
        print(f"\n=== {trader} ===")

        if run_rust:
            print("[rust]")
            cmd = [sys.executable, "tools/run_rust_backtester.py", "--trader", trader, "--dataset", args.dataset]
            if args.day is not None:
                cmd += ["--", "--day", str(args.day)]
            if args.use_wsl:
                cmd.insert(cmd.index("--trader"), "--use-wsl")
            r = subprocess.run(cmd, cwd=str(REPO_ROOT))
            rc = rc or r.returncode

        if run_p4bt:
            print("[prosperity4bt]")
            cmd = [sys.executable, "tools/run_prosperity4bt.py", "--trader", trader, "--dataset", args.dataset, "--no-progress"]
            if args.day is not None:
                cmd += ["--day", str(args.day)]
            r = subprocess.run(cmd, cwd=str(REPO_ROOT))
            rc = rc or r.returncode

    print("\nDone. Open the dashboard -> 'Rust Backtester' tab to see the merged leaderboard.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
