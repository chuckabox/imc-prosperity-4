"""Large sweep around v57 dual-allocator design.

Auto-generates temporary candidates and removes them after run.
"""
from __future__ import annotations

import itertools
import os
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TRADERS_DIR = REPO_ROOT / "ROUND 3" / "traders" / "ken"
DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"


def write_candidate(name: str, p: dict) -> Path:
    fp = TRADERS_DIR / f"{name}.py"
    fp.write_text(
        f'''"""Auto-generated dual-allocator candidate: {name}."""
from __future__ import annotations
from trader_ken_v57_dual_allocator import Trader as _Base


class Trader(_Base):
    HP_MAKER_EDGE = {p["HP_MAKER_EDGE"]}
    HP_TAKER_EDGE = {p["HP_TAKER_EDGE"]}
    HP_MAKER_BASE = {p["HP_MAKER_BASE"]}
    HP_TAKER_BASE = {p["HP_TAKER_BASE"]}
    HP_TAKER_SPREAD_MAX = {p["HP_TAKER_SPREAD_MAX"]}
    VEV_Z_ENTRY = {p["VEV_Z_ENTRY"]}
    VEV_TAKER_BASE = {{5000: {p["VEV5000"]}, 5100: {p["VEV5100"]}}}
    VOL_ON = {p["VOL_ON"]}
    VOL_OFF = {p["VOL_OFF"]}
''',
        encoding="utf-8",
    )
    return fp


def param_space():
    grid = {
        "HP_MAKER_EDGE": [1.9, 2.0, 2.1],
        "HP_TAKER_EDGE": [2.9, 3.1, 3.4],
        "HP_MAKER_BASE": [32, 36, 40],
        "HP_TAKER_BASE": [10, 12, 14],
        "HP_TAKER_SPREAD_MAX": [11, 12, 13],
        "VEV_Z_ENTRY": [1.9, 2.05, 2.2],
        "VEV5000": [3, 4, 5],
        "VEV5100": [1, 2, 3],
        "VOL_ON": [1.35, 1.45, 1.55],
        "VOL_OFF": [0.95, 1.05, 1.15],
    }
    keys = list(grid.keys())
    vals = [grid[k] for k in keys]
    for c in itertools.product(*vals):
        d = dict(zip(keys, c))
        if d["VOL_OFF"] >= d["VOL_ON"]:
            continue
        if d["VEV5100"] > d["VEV5000"]:
            continue
        if d["HP_MAKER_EDGE"] > d["HP_TAKER_EDGE"]:
            continue
        yield d


def parse_totals(text: str):
    pat = re.compile(r"\[prosperity4bt\]\s+([^\s]+)\s+.*?day=(-?\d+).*?PnL=([-\d,]+)", re.S)
    totals = {}
    for m in pat.finditer(text):
        t = m.group(1)
        pnl = int(m.group(3).replace(",", ""))
        totals[t] = totals.get(t, 0) + pnl
    return totals


def main():
    baseline = TRADERS_DIR / "trader_ken_v41_standalone.py"
    space = list(param_space())[:64]
    temp = []
    try:
        for i, p in enumerate(space):
            temp.append(write_candidate(f"trader_ken_v57s_{i:02d}", p))

        cmd = [
            "python",
            "tools/compare_rust.py",
            str(baseline.relative_to(REPO_ROOT)),
        ] + [str(t.relative_to(REPO_ROOT)) for t in temp] + [
            "--dataset",
            str(DATASET.relative_to(REPO_ROOT)),
            "--p4bt-only",
        ]
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, capture_output=True)
        print(proc.stdout)
        if proc.returncode != 0:
            print(proc.stderr)
            raise SystemExit(proc.returncode)

        totals = parse_totals(proc.stdout)
        ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        print("\n=== SWEEP V57 DUAL LEADERBOARD ===")
        for t, v in ranked[:15]:
            print(f"{t:32s} {v:8d}")

        out = REPO_ROOT / "tools" / "out"
        out.mkdir(parents=True, exist_ok=True)
        (out / "sweep_v57_dual_last.txt").write_text(
            "\n".join(f"{t},{v}" for t, v in ranked),
            encoding="utf-8",
        )
    finally:
        for t in temp:
            if t.exists():
                t.unlink()


if __name__ == "__main__":
    main()

