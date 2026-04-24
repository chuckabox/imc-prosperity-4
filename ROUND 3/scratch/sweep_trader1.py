"""sweep_trader1.py — grid sweep for trader1.py (HYDROGEL + VFE + VEV).

Train on day 0+1 ONLY. Day 2 is hidden validation — run separately once.

Run from repo root:
    python "ROUND 3/scratch/sweep_trader1.py"

Optional flags:
    --validate        Also run day 2 (final eval only)
    --fast            Smaller grid for quick sanity check
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import itertools
import json
import sys
import time
from contextlib import redirect_stdout, redirect_stderr, contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRADER_PATH = REPO_ROOT / "ROUND 3" / "traders" / "peter" / "trader1.py"
DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"
ROUND_NUM = 3
TRAIN_DAYS = [0, 1]
VAL_DAYS = [2]

LOG_PATH = REPO_ROOT / "ROUND 3" / "scratch" / "sweep_trader1.log"
RESULTS_PATH = REPO_ROOT / "ROUND 3" / "scratch" / "sweep_trader1_results.json"


# ── prosperity4bt setup ────────────────────────────────────────────────────
def _install_datamodel_alias() -> None:
    from prosperity4bt import datamodel as p4_datamodel
    sys.modules.setdefault("datamodel", p4_datamodel)


def _patch_position_limits() -> None:
    from prosperity4bt import data as p4_data
    extra = {
        "HYDROGEL_PACK": 80, "VELVETFRUIT_EXTRACT": 80,
        "VEV_4000": 60, "VEV_4500": 60, "VEV_5000": 60, "VEV_5100": 60,
        "VEV_5200": 60, "VEV_5300": 60, "VEV_5400": 60, "VEV_5500": 60,
        "VEV_6000": 60, "VEV_6500": 60,
    }
    for k, v in extra.items():
        p4_data.LIMITS.setdefault(k, v)


class _DirectFileReader:
    def __init__(self, root: Path):
        self._root = root

    def file(self, parts):
        target = self._root
        for p in parts[1:]:
            target = target / p

        @contextmanager
        def _ctx():
            yield target if target.is_file() else None
        return _ctx()


def _load_trader_module():
    sys.path.insert(0, str(TRADER_PATH.parent))
    spec = importlib.util.spec_from_file_location("user_trader1_sweep", TRADER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _summarise_pnl(result) -> float:
    if not result.activity_logs:
        return 0.0
    last_ts = result.activity_logs[-1].timestamp
    total = 0.0
    for row in reversed(result.activity_logs):
        if row.timestamp != last_ts:
            break
        total += float(row.columns[-1])
    return total


def _run_one_day(trader_module, day: int, reader, match_mode) -> float:
    from prosperity4bt.runner import run_backtest
    trader = trader_module.Trader()
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        result = run_backtest(
            trader=trader,
            file_reader=reader,
            round_num=ROUND_NUM,
            day_num=day,
            print_output=False,
            trade_matching_mode=match_mode,
            no_names=False,
            show_progress_bar=False,
        )
    return _summarise_pnl(result)


def _log(msg: str) -> None:
    print(msg, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


# ── Grid definitions ───────────────────────────────────────────────────────
GRID_FULL = {
    # HYDROGEL knobs
    "HP_EWMA_ALPHA":    [0.10, 0.20, 0.35],
    "HP_TAKE_EDGE":     [1, 2, 3],
    "HP_OBI_THRESHOLD": [0.08, 0.12, 0.18],
    "HP_NEUTRAL_FRONT": [15, 20, 25],
    # VFE knobs
    "VFE_EWMA_ALPHA":   [0.15, 0.20, 0.30],
    "VFE_TAKE_EDGE":    [1, 2, 3],
    # VEV knobs
    "VEV_SIGMA":        [0.015, 0.018, 0.022],
    "VEV_TAKE_EDGE":    [5.0, 8.0, 12.0],
}

GRID_FAST = {
    "HP_TAKE_EDGE":     [1, 2, 3],
    "HP_OBI_THRESHOLD": [0.06, 0.10, 0.15, 0.20],
    "HP_NEUTRAL_FRONT": [12, 18, 25],
}


def _build_combos(grid: dict) -> list[dict]:
    keys = list(grid.keys())
    vals = [grid[k] for k in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*vals)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true",
                        help="Also run day 2 (final eval)")
    parser.add_argument("--fast", action="store_true",
                        help="Smaller grid for quick test")
    args = parser.parse_args()

    _install_datamodel_alias()
    _patch_position_limits()
    from prosperity4bt.models import TradeMatchingMode

    LOG_PATH.write_text("", encoding="utf-8")

    trader_mod = _load_trader_module()
    Trader = trader_mod.Trader
    reader = _DirectFileReader(DATASET)
    match_mode = TradeMatchingMode.all

    grid = GRID_FAST if args.fast else GRID_FULL
    combos = _build_combos(grid)
    days = TRAIN_DAYS + (VAL_DAYS if args.validate else [])

    _log(f"Grid: {len(combos)} combos x {len(days)} days = {len(combos)*len(days)} runs")
    _log(f"Days: {days} ({'VALIDATE' if args.validate else 'TRAIN ONLY'})")
    _log(f"Params swept: {list(grid.keys())}")

    # Save default params so we can reset between combos
    defaults = Trader.get_params()

    rows: list[dict] = []
    t0 = time.time()
    for i, params in enumerate(combos):
        # Reset to defaults, then apply this combo
        Trader.apply_params(defaults)
        Trader.apply_params(params)

        per_day = {}
        for d in days:
            per_day[d] = _run_one_day(trader_mod, d, reader, match_mode)

        train_pnl = sum(per_day.get(d, 0) for d in TRAIN_DAYS)
        val_pnl = per_day.get(2, None)

        row = {
            "params": params,
            "per_day": per_day,
            "train_pnl": train_pnl,
            "val_pnl": val_pnl,
        }
        rows.append(row)

        elapsed = time.time() - t0
        eta = elapsed / (i + 1) * (len(combos) - i - 1)
        p_str = " ".join(f"{k}={v}" for k, v in params.items())
        day_str = " ".join(f"d{d}={per_day[d]:+.0f}" for d in days)
        _log(f"  [{i+1:>4}/{len(combos)}] {p_str} | {day_str} "
             f"TRAIN={train_pnl:+.0f} (eta {eta:.0f}s)")

    # Sort by train PnL
    rows.sort(key=lambda r: r["train_pnl"], reverse=True)

    _log("\n=== TOP 15 (by train PnL d0+d1) ===")
    for r in rows[:15]:
        p_str = " ".join(f"{k}={v}" for k, v in r["params"].items())
        day_str = " ".join(f"d{d}={r['per_day'][d]:+.0f}" for d in days)
        val = f" VAL={r['val_pnl']:+.0f}" if r["val_pnl"] is not None else ""
        _log(f"  TRAIN={r['train_pnl']:+.0f} {day_str}{val}  | {p_str}")

    _log("\n=== BOTTOM 5 ===")
    for r in rows[-5:]:
        p_str = " ".join(f"{k}={v}" for k, v in r["params"].items())
        _log(f"  TRAIN={r['train_pnl']:+.0f}  | {p_str}")

    # Sensitivity: for top param set, show how each param perturbation affects PnL
    if len(rows) > 1:
        best = rows[0]
        _log("\n=== SENSITIVITY (top config) ===")
        _log(f"  Best params: {best['params']}")
        _log(f"  Best train PnL: {best['train_pnl']:+.0f}")
        # Find neighbors in grid that differ by exactly 1 param
        for r in rows[1:30]:
            diffs = {k: (best["params"].get(k), r["params"].get(k))
                     for k in best["params"]
                     if best["params"].get(k) != r["params"].get(k)}
            if len(diffs) == 1:
                k, (v_best, v_other) = list(diffs.items())[0]
                delta = r["train_pnl"] - best["train_pnl"]
                _log(f"    {k}: {v_best} -> {v_other}  dPnL={delta:+.0f}")

    # Save full results
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, default=str)
    _log(f"\nFull results saved to {RESULTS_PATH}")

    # Restore defaults
    Trader.apply_params(defaults)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
