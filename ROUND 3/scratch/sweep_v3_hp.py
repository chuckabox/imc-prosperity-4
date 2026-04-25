"""sweep_v3_hp.py — coordinate-grid sweep of v3 HYDROGEL knobs.

Calls prosperity4bt's run_backtest in-process for each (param-combo x day)
and prints the top 10 configurations sorted by 3-day total PnL.

Run from repo root:
    python "ROUND 3/scratch/sweep_v3_hp.py"
"""
from __future__ import annotations

import importlib.util
import io
import itertools
import sys
import time
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRADER_PATH = REPO_ROOT / "ROUND 3" / "traders" / "ken" / "trader_ken_v3.py"
DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"
ROUND_NUM = 3
DAYS = [0, 1, 2]


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
    spec = importlib.util.spec_from_file_location("user_trader_v3_sweep", TRADER_PATH)
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
    # Silence prosperity4bt's tqdm + any prints from trader
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


def main() -> int:
    _install_datamodel_alias()
    _patch_position_limits()

    from prosperity4bt.models import TradeMatchingMode

    trader_mod = _load_trader_module()
    Trader = trader_mod.Trader
    reader = _DirectFileReader(DATASET)
    match_mode = TradeMatchingMode.all

    # Coordinate grid — small enough to finish in a few minutes.
    OBI_THR = [0.10, 0.15, 0.20]
    NEUTRAL = [15, 20, 25, 30]
    LEAN_AGG = [25, 30, 40]
    LEAN_OFF = [2, 3, 4]

    combos = list(itertools.product(OBI_THR, NEUTRAL, LEAN_AGG, LEAN_OFF))
    print(f"Sweeping {len(combos)} combos x {len(DAYS)} days "
          f"= {len(combos) * len(DAYS)} runs")

    rows: list[tuple[float, dict, dict]] = []
    t0 = time.time()
    for i, (thr, nf, lagg, loff) in enumerate(combos):
        Trader.HP_OBI_THRESHOLD = thr
        Trader.HP_NEUTRAL_FRONT = nf
        Trader.HP_LEAN_AGGRESSIVE = lagg
        Trader.HP_LEAN_OFFSET_DEFENSIVE = loff
        per_day = {}
        for d in DAYS:
            per_day[d] = _run_one_day(trader_mod, d, reader, match_mode)
        total = sum(per_day.values())
        params = dict(thr=thr, nf=nf, lagg=lagg, loff=loff)
        rows.append((total, params, per_day))
        elapsed = time.time() - t0
        eta = elapsed / (i + 1) * (len(combos) - i - 1)
        print(f"  [{i+1:>3}/{len(combos)}] thr={thr:.2f} nf={nf:>2} lagg={lagg:>2} "
              f"loff={loff} | d0={per_day[0]:>+7.0f} d1={per_day[1]:>+7.0f} "
              f"d2={per_day[2]:>+7.0f}  SUM={total:>+7.0f}  (eta {eta:.0f}s)")

    rows.sort(key=lambda r: r[0], reverse=True)
    print("\n=== TOP 10 ===")
    for total, params, per_day in rows[:10]:
        print(f"  SUM={total:>+7.0f}  d0={per_day[0]:>+7.0f} d1={per_day[1]:>+7.0f} "
              f"d2={per_day[2]:>+7.0f}  thr={params['thr']:.2f} nf={params['nf']:>2} "
              f"lagg={params['lagg']:>2} loff={params['loff']}")
    print("\n=== BOTTOM 5 ===")
    for total, params, per_day in rows[-5:]:
        print(f"  SUM={total:>+7.0f}  d0={per_day[0]:>+7.0f} d1={per_day[1]:>+7.0f} "
              f"d2={per_day[2]:>+7.0f}  thr={params['thr']:.2f} nf={params['nf']:>2} "
              f"lagg={params['lagg']:>2} loff={params['loff']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
