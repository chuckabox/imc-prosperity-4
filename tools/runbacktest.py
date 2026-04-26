#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUST_BACKTESTER_DIR = REPO_ROOT / "external" / "prosperity_rust_backtester"


def infer_dataset_from_trader(trader_path: Path) -> Path:
    m = re.search(r"ROUND\s+(\d+)", str(trader_path), flags=re.IGNORECASE)
    if m:
        return REPO_ROOT / f"ROUND {m.group(1)}" / "data_capsule"
    return REPO_ROOT / "ROUND 4" / "data_capsule"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simple wrapper for rust backtester.\n"
        "Usage: python tools/runbacktest.py <trader_path> [--dataset <dataset_dir>] [--no-build] [other rust options]",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("trader_path", help="Path to trader python file")
    parser.add_argument(
        "--dataset",
        default="",
        help="Dataset directory (default: inferred from trader path, e.g. ROUND 4/data_capsule)",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip cargo build and directly run cargo run --release",
    )
    args, rust_args = parser.parse_known_args()

    if shutil.which("cargo") is None:
        print("ERROR: cargo not found on PATH.", file=sys.stderr)
        return 1

    trader = Path(args.trader_path)
    if not trader.is_absolute():
        trader = (REPO_ROOT / trader).resolve()
    else:
        trader = trader.resolve()
    if not trader.is_file():
        print(f"ERROR: trader file not found: {trader}", file=sys.stderr)
        return 1

    dataset = Path(args.dataset) if args.dataset else infer_dataset_from_trader(trader)
    if not dataset.is_absolute():
        dataset = (REPO_ROOT / dataset).resolve()
    else:
        dataset = dataset.resolve()
    if not dataset.is_dir():
        print(f"ERROR: dataset directory not found: {dataset}", file=sys.stderr)
        return 1

    if not RUST_BACKTESTER_DIR.is_dir():
        print(f"ERROR: rust backtester directory not found: {RUST_BACKTESTER_DIR}", file=sys.stderr)
        return 1

    if not args.no_build:
        build_cmd = ["cargo", "build", "--release"]
        print("Building:", shlex.join(build_cmd))
        build_rc = subprocess.run(build_cmd, cwd=str(RUST_BACKTESTER_DIR)).returncode
        if build_rc != 0:
            return build_rc

    run_cmd = [
        "cargo",
        "run",
        "--release",
        "--",
        "--trader",
        str(trader),
        "--dataset",
        str(dataset),
        *rust_args,
    ]
    print("Running:", shlex.join(run_cmd))
    return subprocess.run(run_cmd, cwd=str(RUST_BACKTESTER_DIR)).returncode


if __name__ == "__main__":
    raise SystemExit(main())
