"""Batch sweep around v41_standalone core parameters."""
from __future__ import annotations

import itertools
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TRADERS_DIR = REPO_ROOT / "ROUND 3" / "traders" / "ken"
DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"


def write_candidate(name: str, p: dict) -> Path:
    fp = TRADERS_DIR / f"{name}.py"
    fp.write_text(
        f'''"""Auto-generated v41 core sweep: {name}."""
from __future__ import annotations
from trader_ken_v41_standalone import Trader as _Base


class Trader(_Base):
    HP_MAKER_EDGE = {p["HP_MAKER_EDGE"]}
    HP_TAKER_EDGE = {p["HP_TAKER_EDGE"]}
    HP_TAKER_MAX = {p["HP_TAKER_MAX"]}
    VFE_TAKER_EDGE = {p["VFE_TAKER_EDGE"]}
    VFE_TAKER_MAX = {p["VFE_TAKER_MAX"]}
    VEV_Z_ENTRY = {p["VEV_Z_ENTRY"]}
    VEV_TAKER_MAX_BY_STRIKE = {{5000: {p["VEV5000"]}, 5100: {p["VEV5100"]}}}
''',
        encoding="utf-8",
    )
    return fp


def param_space():
    grid = {
        "HP_MAKER_EDGE": [2.1, 2.3, 2.5],
        "HP_TAKER_EDGE": [2.2, 2.5, 2.8],
        "HP_TAKER_MAX": [16, 20, 24],
        "VFE_TAKER_EDGE": [4.0, 4.5, 5.0],
        "VFE_TAKER_MAX": [10, 12, 14],
        "VEV_Z_ENTRY": [1.5, 1.65, 1.8],
        "VEV5000": [8, 9, 10],
        "VEV5100": [5, 6, 7],
    }
    keys = list(grid.keys())
    vals = [grid[k] for k in keys]
    for c in itertools.product(*vals):
        d = dict(zip(keys, c))
        # prune to keep runtime sane
        if d["HP_MAKER_EDGE"] > d["HP_TAKER_EDGE"]:
            continue
        if d["VEV5100"] > d["VEV5000"]:
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
    params = list(param_space())[:28]
    cands = []
    for i, p in enumerate(params):
        cands.append(write_candidate(f"trader_ken_v41s_{i:02d}", p))

    baseline = TRADERS_DIR / "trader_ken_v41_standalone.py"
    cmd = [
        "python",
        "tools/compare_rust.py",
        str(baseline.relative_to(REPO_ROOT)),
    ] + [str(c.relative_to(REPO_ROOT)) for c in cands] + [
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
    print("\n=== SWEEP V41 CORE LEADERBOARD ===")
    for t, v in ranked[:12]:
        print(f"{t:32s} {v:8d}")

    out = REPO_ROOT / "tools" / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "sweep_v41_core_last.txt").write_text(
        "\n".join(f"{t},{v}" for t, v in ranked),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

