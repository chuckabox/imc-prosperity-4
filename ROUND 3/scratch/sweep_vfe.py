"""sweep_vfe.py — sweep VFE params with best HP fixed.

HP+VFE combined was 29k. HP alone is 23k. VFE adds ~6k.
Goal: maximize VFE contribution without hurting HP.
"""
from __future__ import annotations

import importlib.util
import io
import itertools
import sys
import time
from contextlib import redirect_stdout, redirect_stderr, contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRADER_PATH = REPO_ROOT / "ROUND 3" / "traders" / "peter" / "trader1.py"
DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"
ROUND_NUM = 3
DAYS = [0, 1]


def _setup():
    from prosperity4bt import datamodel as p4_datamodel
    sys.modules.setdefault("datamodel", p4_datamodel)
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
    spec = importlib.util.spec_from_file_location("user_trader1_vfe_sweep", TRADER_PATH)
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


def _run_one_day(trader_module, day, reader, match_mode) -> float:
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


def main():
    _setup()
    from prosperity4bt.models import TradeMatchingMode

    trader_mod = _load_trader_module()
    Trader = trader_mod.Trader
    reader = _DirectFileReader(DATASET)
    match_mode = TradeMatchingMode.all

    # Fix best HP params, disable VEV
    Trader.HP_TAKE_EDGE = 1
    Trader.HP_OBI_THRESHOLD = 0.10
    Trader.HP_NEUTRAL_FRONT = 12
    Trader.ENABLE_VEV = False
    Trader.ENABLE_HEDGE = False
    Trader.ENABLE_VFE = True
    Trader.ENABLE_HYDROGEL = True

    grid = {
        "VFE_EWMA_ALPHA":     [0.10, 0.20, 0.35, 0.50],
        "VFE_TAKE_EDGE":      [1, 2, 3],
        "VFE_NEUTRAL_FRONT":  [10, 15, 20, 30],
        "VFE_TREND_THRESHOLD":[0.03, 0.05, 0.08, 0.15],
    }

    keys = list(grid.keys())
    vals = [grid[k] for k in keys]
    combos = [dict(zip(keys, c)) for c in itertools.product(*vals)]

    defaults = Trader.get_params()

    print(f"Sweeping {len(combos)} VFE combos x {len(DAYS)} days")

    rows = []
    t0 = time.time()
    for i, params in enumerate(combos):
        Trader.apply_params(defaults)
        Trader.apply_params(params)
        per_day = {}
        for d in DAYS:
            per_day[d] = _run_one_day(trader_mod, d, reader, match_mode)
        total = sum(per_day.values())
        rows.append((total, params, per_day))

        elapsed = time.time() - t0
        eta = elapsed / (i + 1) * (len(combos) - i - 1)
        p_str = " ".join(f"{k.split('_',1)[1]}={v}" for k, v in params.items())
        print(f"  [{i+1:>3}/{len(combos)}] {p_str} | d0={per_day[0]:+.0f} d1={per_day[1]:+.0f} "
              f"T={total:+.0f} (eta {eta:.0f}s)")

    rows.sort(key=lambda r: r[0], reverse=True)
    print("\n=== TOP 10 ===")
    for total, params, per_day in rows[:10]:
        p_str = " ".join(f"{k}={v}" for k, v in params.items())
        print(f"  T={total:+.0f} d0={per_day[0]:+.0f} d1={per_day[1]:+.0f}  | {p_str}")

    print("\n=== SENSITIVITY ===")
    best = rows[0]
    for total, params, per_day in rows[1:40]:
        diffs = {k: (best[1].get(k), params.get(k))
                 for k in best[1] if best[1].get(k) != params.get(k)}
        if len(diffs) == 1:
            k, (vb, vo) = list(diffs.items())[0]
            delta = total - best[0]
            print(f"    {k}: {vb} -> {vo}  dPnL={delta:+.0f}")


if __name__ == "__main__":
    main()
