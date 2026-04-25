"""Quick smoke test for trader2.py — runs days 0+1 only (Day 2 hidden)."""
from __future__ import annotations

import importlib.util
import io
import sys
import time
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRADER_PATH = REPO_ROOT / "ROUND 3" / "traders" / "peter" / "trader2.py"
DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"
ROUND_NUM = 3
TRAIN_DAYS = [0, 1]  # NEVER include 2


def _install_datamodel_alias():
    from prosperity4bt import datamodel as p4_datamodel
    sys.modules.setdefault("datamodel", p4_datamodel)


def _patch_position_limits():
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
    def __init__(self, root): self._root = root
    def file(self, parts):
        target = self._root
        for p in parts[1:]:
            target = target / p
        @contextmanager
        def _ctx(): yield target if target.is_file() else None
        return _ctx()


def _per_product_pnl(result):
    """Extract final PnL per product from last timestamp of activity_logs."""
    if not result.activity_logs:
        return {}
    last_ts = result.activity_logs[-1].timestamp
    out = {}
    for row in reversed(result.activity_logs):
        if row.timestamp != last_ts:
            break
        # row.columns: [day, ts, product, ..., pnl]
        prod = row.columns[2]
        pnl = float(row.columns[-1])
        out[prod] = out.get(prod, 0.0) + pnl
    return out


def _load_trader():
    sys.path.insert(0, str(TRADER_PATH.parent))
    spec = importlib.util.spec_from_file_location("trader2_test", TRADER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    _install_datamodel_alias()
    _patch_position_limits()
    from prosperity4bt.runner import run_backtest
    from prosperity4bt.models import TradeMatchingMode

    mod = _load_trader()
    reader = _DirectFileReader(DATASET)
    match_mode = TradeMatchingMode.all

    print(f"Trader: {TRADER_PATH.name}")
    print(f"Train days: {TRAIN_DAYS}\n")

    total = 0.0
    by_day = {}
    for d in TRAIN_DAYS:
        t0 = time.time()
        trader = mod.Trader()
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            r = run_backtest(
                trader=trader, file_reader=reader,
                round_num=ROUND_NUM, day_num=d,
                print_output=False, trade_matching_mode=match_mode,
                no_names=False, show_progress_bar=False,
            )
        per = _per_product_pnl(r)
        day_total = sum(per.values())
        total += day_total
        by_day[d] = (day_total, per)
        elapsed = time.time() - t0
        print(f"Day {d}: total={day_total:>+12,.0f}  ({elapsed:.1f}s)")
        for prod in sorted(per.keys()):
            print(f"   {prod:25s} {per[prod]:>+12,.0f}")
        print()

    print(f"Train total (days {TRAIN_DAYS}): {total:+,.0f}")
    print("Sanity check: oracle ~155k. If > 200k -> suspect overfit.")


if __name__ == "__main__":
    main()
