#!/usr/bin/env python3
"""
One-shot launcher for the vendored Rust IMC backtester (like ``streamlit run tools/dashboard.py``).

From the repo root:

    python tools/run_rust_backtester.py

Override paths:

    python tools/run_rust_backtester.py --trader "ROUND 2/traders/ken/trader_ken_v6.py" --dataset "ROUND 2/data_capsule"

Pass flags through to ``rust_backtester`` (everything this script does not consume):

    python tools/run_rust_backtester.py -- --day -1

Skip rebuild if the release binary already exists:

    python tools/run_rust_backtester.py --no-build

Requires ``cargo`` on PATH. On Windows you need the MSVC linker (VS Build Tools) or use WSL2.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUST_CRATE = REPO_ROOT / "external" / "prosperity_rust_backtester"


def _default_trader() -> Path:
    return REPO_ROOT / "ROUND 2" / "traders" / "ken" / "trader_ken_v6.py"


def _default_dataset() -> Path:
    return REPO_ROOT / "ROUND 2" / "data_capsule"


def _release_binary() -> Path:
    name = "rust_backtester.exe" if os.name == "nt" else "rust_backtester"
    return RUST_CRATE / "target" / "release" / name


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build (unless --no-build) and run external/prosperity_rust_backtester against Round 2 capsule data by default.",
    )
    parser.add_argument(
        "--trader",
        type=Path,
        default=None,
        help=f"Trader .py file (default: {_default_trader().relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help=f"Directory with prices_*.csv / trades_*.csv (default: {_default_dataset().relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Do not run cargo build; fail if release binary is missing.",
    )
    args, rust_argv = parser.parse_known_args()

    if shutil.which("cargo") is None:
        print("ERROR: `cargo` not found on PATH. Install Rust, or run from WSL2.", file=sys.stderr)
        return 1

    trader = (args.trader or _default_trader()).resolve()
    dataset = (args.dataset or _default_dataset()).resolve()

    if not RUST_CRATE.is_dir():
        print(f"ERROR: Rust crate not found: {RUST_CRATE}", file=sys.stderr)
        return 1
    if not trader.is_file():
        print(f"ERROR: Trader file not found: {trader}", file=sys.stderr)
        return 1
    if not dataset.is_dir():
        print(f"ERROR: Dataset directory not found: {dataset}", file=sys.stderr)
        return 1

    exe = _release_binary()
    if not args.no_build:
        print("Building rust_backtester (cargo build --release) …", flush=True)
        br = subprocess.run(
            ["cargo", "build", "--release"],
            cwd=str(RUST_CRATE),
        )
        if br.returncode != 0:
            return br.returncode
    elif not exe.is_file():
        print(f"ERROR: --no-build but binary missing: {exe}", file=sys.stderr)
        return 1

    if not exe.is_file():
        print(f"ERROR: Release binary not found after build: {exe}", file=sys.stderr)
        return 1

    cmd = [str(exe), "--trader", str(trader), "--dataset", str(dataset), *rust_argv]
    print("Running:", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(RUST_CRATE)).returncode


if __name__ == "__main__":
    raise SystemExit(main())
