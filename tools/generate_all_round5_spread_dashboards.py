#!/usr/bin/env python3
from __future__ import annotations

import itertools
import subprocess
from pathlib import Path
import argparse

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
PRICES = [
    REPO_ROOT / "ROUND 5" / "data_capsule" / "prices_round_5_day_2.csv",
    REPO_ROOT / "ROUND 5" / "data_capsule" / "prices_round_5_day_3.csv",
    REPO_ROOT / "ROUND 5" / "data_capsule" / "prices_round_5_day_4.csv",
]

FAMILIES = [
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


def slug(s: str) -> str:
    return s.lower().replace("__", "_")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate all Round 5 same-family pair dashboards.")
    p.add_argument(
        "--out-dir",
        default=str(REPO_ROOT / "ROUND 5" / "docs" / "pair_dashboards"),
        help="Output folder for pair dashboards.",
    )
    p.add_argument("--spread-threshold", type=float, default=12.0, help="Tight spread threshold.")
    p.add_argument("--forward-lag", type=int, default=20, help="Forward return lag.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir).resolve()
    df = pd.read_csv(PRICES[0], sep=";")[["product"]].drop_duplicates()
    all_symbols = df["product"].tolist()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    failures = []
    for fam in FAMILIES:
        syms = sorted([s for s in all_symbols if s.startswith(fam + "_")])
        for a, b in itertools.combinations(syms, 2):
            out = out_dir / f"{slug(a)}__{slug(b)}__spread_dashboard.png"
            cmd = [
                "python",
                str(REPO_ROOT / "tools" / "generate_round5_spread_dashboard.py"),
                "--prices",
                str(PRICES[0]),
                str(PRICES[1]),
                str(PRICES[2]),
                "--symbol-a",
                a,
                "--symbol-b",
                b,
                "--reference-symbol",
                a,
                "--spread-threshold",
                str(args.spread_threshold),
                "--forward-lag",
                str(args.forward_lag),
                "--freq-window",
                "100",
                "--preview-points",
                "1000",
                "--out",
                str(out),
            ]
            proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
            total += 1
            if proc.returncode != 0:
                failures.append((a, b, proc.stderr[-400:]))

    manifest = out_dir / "manifest.txt"
    manifest.write_text(
        f"generated={total - len(failures)}\nfailed={len(failures)}\ntotal={total}\n",
        encoding="utf-8",
    )
    if failures:
        fail_file = out_dir / "failures.txt"
        fail_file.write_text("\n\n".join(f"{a},{b}\n{err}" for a, b, err in failures), encoding="utf-8")

    print(f"Generated {total - len(failures)}/{total} dashboards in {out_dir}")
    if failures:
        print(f"Failures logged: {out_dir / 'failures.txt'}")


if __name__ == "__main__":
    main()
