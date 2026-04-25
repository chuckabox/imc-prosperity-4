"""Live-objective sweep.

Objective:
  score = total_pnl - lambda_fill * own_trade_count

This proxies live execution drag (taker-heavy behavior) while preserving backtest alpha.
Temporary candidate files are auto-cleaned at the end.
"""
from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TRADERS_DIR = REPO_ROOT / "ROUND 3" / "traders" / "ken"
RUNS_DIR = REPO_ROOT / "external" / "prosperity_rust_backtester" / "runs"
DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"


def write_candidate(name: str, p: dict) -> Path:
    fp = TRADERS_DIR / f"{name}.py"
    fp.write_text(
        f'''"""Auto-generated live-objective candidate: {name}."""
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
        "HP_MAKER_EDGE": [2.1, 2.3],
        "HP_TAKER_EDGE": [2.3, 2.6, 2.9],
        "HP_TAKER_MAX": [14, 18, 22],
        "VFE_TAKER_EDGE": [4.2, 4.6, 5.0],
        "VFE_TAKER_MAX": [10, 12],
        "VEV_Z_ENTRY": [1.6, 1.75],
        "VEV5000": [8, 9, 10],
        "VEV5100": [5, 6, 7],
    }
    keys = list(grid.keys())
    vals = [grid[k] for k in keys]
    for combo in itertools.product(*vals):
        d = dict(zip(keys, combo))
        if d["VEV5100"] > d["VEV5000"]:
            continue
        if d["HP_TAKER_EDGE"] <= 2.3 and d["HP_TAKER_MAX"] >= 22:
            continue
        yield d


def latest_run_id_by_trader(candidates: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    if not RUNS_DIR.exists():
        return out
    for d in sorted(RUNS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        mpath = d / "metrics.json"
        if not mpath.exists():
            continue
        try:
            m = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception:
            continue
        tp = str(m.get("trader_path", ""))
        name = os.path.basename(tp)
        if name in candidates and name not in out:
            out[name] = str(d)
        if len(out) == len(candidates):
            break
    return out


def load_metrics(run_dir: str) -> dict:
    mpath = Path(run_dir) / "metrics.json"
    if not mpath.exists():
        return {}
    try:
        return json.loads(mpath.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    lambda_fill = 35.0
    params = list(param_space())[:24]
    temp_files: list[Path] = []
    cands: list[str] = []

    try:
        for i, p in enumerate(params):
            name = f"trader_ken_liveobj_{i:02d}"
            fp = write_candidate(name, p)
            temp_files.append(fp)
            cands.append(fp.name)

        baseline = TRADERS_DIR / "trader_ken_v41_standalone.py"
        cmd = [
            "python",
            "tools/compare_rust.py",
            str(baseline.relative_to(REPO_ROOT)),
        ] + [str(p.relative_to(REPO_ROOT)) for p in temp_files] + [
            "--dataset",
            str(DATASET.relative_to(REPO_ROOT)),
            "--p4bt-only",
        ]
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, capture_output=True)
        print(proc.stdout)
        if proc.returncode != 0:
            print(proc.stderr)
            raise SystemExit(proc.returncode)

        run_map = latest_run_id_by_trader(set(cands + [baseline.name]))
        rows = []
        for tname, rdir in run_map.items():
            m = load_metrics(rdir)
            pnl = float(m.get("final_pnl_total", 0.0))
            own_trades = float(m.get("own_trade_count", 0.0))
            score = pnl - lambda_fill * own_trades
            rows.append((tname, pnl, own_trades, score, rdir))
        rows.sort(key=lambda x: x[3], reverse=True)

        print("\n=== LIVE-OBJECTIVE LEADERBOARD ===")
        print(f"(lambda_fill={lambda_fill})")
        for t, pnl, ntr, sc, _r in rows[:12]:
            print(f"{t:32s} pnl={pnl:8.0f} trades={ntr:6.0f} score={sc:9.0f}")

        out_dir = REPO_ROOT / "tools" / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "sweep_live_objective_last.txt").write_text(
            "\n".join(f"{t},{pnl},{ntr},{sc}" for t, pnl, ntr, sc, _ in rows),
            encoding="utf-8",
        )
    finally:
        # Always cleanup temp candidate files.
        for fp in temp_files:
            if fp.exists():
                fp.unlink()


if __name__ == "__main__":
    main()

