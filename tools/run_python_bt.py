#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BT_ROOT = REPO_ROOT / "external" / "imc-prosperity-4-backtester"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run kevin-fu1 Prosperity 4 Python backtester against this repo data."
    )
    parser.add_argument("trader", help="Path to trader python file")
    parser.add_argument(
        "rounds_or_days",
        nargs="+",
        help="Backtester day args, e.g. 5 or 5-3 5-4",
    )
    parser.add_argument(
        "--data",
        default=str(REPO_ROOT),
        help="Data root (default: repo root with ROUND */data_capsule)",
    )
    parser.add_argument("--print-output", action="store_true", help="Pass --print to backtester")
    args = parser.parse_args()

    if not BT_ROOT.is_dir():
        print(f"ERROR: backtester not found at {BT_ROOT}", file=sys.stderr)
        return 1

    trader = Path(args.trader)
    if not trader.is_absolute():
        trader = (REPO_ROOT / trader).resolve()
    if not trader.is_file():
        print(f"ERROR: trader file not found: {trader}", file=sys.stderr)
        return 1

    bt_out_dir = BT_ROOT / "backtests"
    bt_out_dir.mkdir(parents=True, exist_ok=True)
    trader_stem = trader.stem
    day_tokens = "+".join(args.rounds_or_days)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_file = bt_out_dir / f"{trader_stem}__{day_tokens}__{stamp}.log"

    cmd = [
        sys.executable,
        "-m",
        "prosperity4bt",
        str(trader),
        *args.rounds_or_days,
        "--out",
        str(out_file),
        "--data",
        str(Path(args.data).resolve()),
        "--no-vis",
        "--no-progress",
    ]
    if args.print_output:
        cmd.append("--print")

    env = os.environ.copy()
    # Needed for user trader modules that import datamodel from repo root.
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO_ROOT) if not prev else str(REPO_ROOT) + os.pathsep + prev

    print("Running:", shlex.join(cmd))
    rc = subprocess.run(cmd, cwd=str(BT_ROOT), env=env).returncode
    if rc == 0:
        meta = {
            "trader_path": str(trader),
            "rounds_or_days": list(args.rounds_or_days),
            "data_root": str(Path(args.data).resolve()),
            "created_at": datetime.now().isoformat(),
            "engine": "i4bt",
        }
        out_file.with_suffix(".meta.json").write_text(
            __import__("json").dumps(meta, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"Saved log: {out_file}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
