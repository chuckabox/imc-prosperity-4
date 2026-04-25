"""validate_trader1.py — Final validation of optimized trader1.py.
Runs on Day 0+1 (Train) and Day 2 (Validation).
"""
from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout, redirect_stderr, contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRADER_PATH = REPO_ROOT / "ROUND 3" / "traders" / "peter" / "trader1.py"
DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"
ROUND_NUM = 3

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
    spec = importlib.util.spec_from_file_location("user_trader1_val", TRADER_PATH)
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

def _run_backtest(trader_module, day, reader):
    from prosperity4bt.runner import run_backtest
    from prosperity4bt.models import TradeMatchingMode
    trader = trader_module.Trader()
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        result = run_backtest(
            trader=trader,
            file_reader=reader,
            round_num=ROUND_NUM,
            day_num=day,
            print_output=False,
            trade_matching_mode=TradeMatchingMode.all,
            no_names=False,
            show_progress_bar=False,
        )
    return _summarise_pnl(result)

def main():
    _setup()
    trader_mod = _load_trader_module()
    reader = _DirectFileReader(DATASET)
    
    print("=== Validation: trader1.py (Optimized) ===")
    
    days = [0, 1, 2]
    pnls = {}
    for d in days:
        pnls[d] = _run_backtest(trader_mod, d, reader)
        tag = "(TRAIN)" if d in [0, 1] else "(VAL)"
        print(f"  Day {d} {tag:7s}: {pnls[d]:+10.0f}")
        
    train_total = pnls[0] + pnls[1]
    print("-" * 40)
    print(f"  TRAIN TOTAL (d0+1): {train_total:+10.0f}")
    print(f"  VALIDATION (d2):   {pnls[2]:+10.0f}")
    print(f"  FULL TOTAL:        {sum(pnls.values()):+10.0f}")

if __name__ == "__main__":
    main()
