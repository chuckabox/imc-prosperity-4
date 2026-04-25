"""Batch sweep around v50_balanced_live parameters.

Generates candidate trader files, runs compare_rust (p4bt-only), and prints a leaderboard.
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


def _write_candidate(name: str, params: dict) -> Path:
    path = TRADERS_DIR / f"{name}.py"
    body = f'''"""Auto-generated sweep candidate: {name}."""
from __future__ import annotations
from trader_ken_v50_balanced_live import Trader as _BaseTrader


class Trader(_BaseTrader):
    HP_MAKER_EDGE = {params["HP_MAKER_EDGE"]}
    HP_TAKER_EDGE = {params["HP_TAKER_EDGE"]}
    HP_TAKER_MAX = {params["HP_TAKER_MAX"]}
    HP_TAKER_SPREAD_MAX = {params["HP_TAKER_SPREAD_MAX"]}
    HP_TAKER_COOLDOWN_TS = {params["HP_TAKER_COOLDOWN_TS"]}
    VEV_Z_ENTRY = {params["VEV_Z_ENTRY"]}
    VFE_TAKER_EDGE = {params["VFE_TAKER_EDGE"]}
'''
    path.write_text(body, encoding="utf-8")
    return path


def _build_param_space():
    grid = {
        "HP_MAKER_EDGE": [2.1, 2.3],
        "HP_TAKER_EDGE": [2.6, 3.1, 3.6],
        "HP_TAKER_MAX": [12, 16, 20],
        "HP_TAKER_SPREAD_MAX": [10, 12, 14],
        "HP_TAKER_COOLDOWN_TS": [300, 700],
        "VEV_Z_ENTRY": [1.65, 1.8],
        "VFE_TAKER_EDGE": [4.5, 5.0],
    }
    keys = list(grid.keys())
    vals = [grid[k] for k in keys]
    for combo in itertools.product(*vals):
        d = dict(zip(keys, combo))
        # prune obviously aggressive combos
        if d["HP_TAKER_EDGE"] <= 2.6 and d["HP_TAKER_MAX"] >= 20 and d["HP_TAKER_COOLDOWN_TS"] <= 300:
            continue
        yield d


def _parse_compare_output(stdout: str):
    # lines:
    # [prosperity4bt] trader_xyz.py ... day=0
    # -> ... PnL=19,565 trades=416
    patt = re.compile(r"\[prosperity4bt\]\s+([^\s]+)\s+.*?day=(-?\d+).*?PnL=([-\d,]+)", re.S)
    rows = []
    for m in patt.finditer(stdout):
        trader = m.group(1)
        day = int(m.group(2))
        pnl = int(m.group(3).replace(",", ""))
        rows.append((trader, day, pnl))
    totals = {}
    for t, _d, p in rows:
        totals[t] = totals.get(t, 0) + p
    return totals


def main():
    # Keep sweep size manageable for iterative runs.
    params = list(_build_param_space())[:36]
    cand_files = []
    for i, p in enumerate(params):
        name = f"trader_ken_v50s_{i:02d}"
        cand_files.append(_write_candidate(name, p))

    baseline = TRADERS_DIR / "trader_ken_v41_standalone.py"
    cmd = [
        "python",
        "tools/compare_rust.py",
        str(baseline.relative_to(REPO_ROOT)),
    ] + [str(p.relative_to(REPO_ROOT)) for p in cand_files] + [
        "--dataset",
        str(DATASET.relative_to(REPO_ROOT)),
        "--p4bt-only",
    ]

    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
    )
    print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr)
        raise SystemExit(proc.returncode)

    totals = _parse_compare_output(proc.stdout)
    if not totals:
        print("No totals parsed.")
        return

    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    print("\n=== SWEEP LEADERBOARD (TOTAL PnL) ===")
    for t, v in ranked[:12]:
        print(f"{t:32s} {v:8d}")

    out = REPO_ROOT / "tools" / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "sweep_v50_last.txt").write_text(
        "\n".join(f"{t},{v}" for t, v in ranked),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

