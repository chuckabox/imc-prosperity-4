"""sweep_vev_sigma.py — Find profitable VEV sigma in backtest.
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
    spec = importlib.util.spec_from_file_location("user_trader1_vev_sweep", TRADER_PATH)
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

def _run_one_day(trader_module, day, reader):
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
    Trader = trader_mod.Trader
    reader = _DirectFileReader(DATASET)
    
    # Best HP/VFE fixed
    Trader.HP_TAKE_EDGE = 1
    Trader.HP_OBI_THRESHOLD = 0.10
    Trader.HP_NEUTRAL_FRONT = 12
    Trader.VFE_EWMA_ALPHA = 0.35
    Trader.VFE_TAKE_EDGE = 1
    Trader.VFE_NEUTRAL_FRONT = 8
    Trader.VFE_TREND_THRESHOLD = 0.05
    
    Trader.ENABLE_HYDROGEL = True
    Trader.ENABLE_VFE = True
    Trader.ENABLE_VEV = True
    Trader.ENABLE_HEDGE = True
    
    sigmas = [0.010, 0.012, 0.014, 0.016, 0.018, 0.020]
    take_edges = [2.0, 4.0, 6.0, 10.0]
    
    print(f"Sweeping VEV: {len(sigmas)*len(take_edges)} combos")
    
    results = []
    for sigma, edge in itertools.product(sigmas, take_edges):
        Trader.VEV_SIGMA = sigma
        Trader.VEV_TAKE_EDGE = edge
        Trader.VEV_SELL_EDGE = edge
        
        pnls = {}
        for d in DAYS:
            pnls[d] = _run_one_day(trader_mod, d, reader)
        total = sum(pnls.values())
        print(f"  sigma={sigma:.3f} edge={edge:4.1f} | d0={pnls[0]:+7.0f} d1={pnls[1]:+7.0f} T={total:+7.0f}", flush=True)
        results.append((total, sigma, edge))
        
    results.sort(reverse=True)
    print("\n=== BEST VEV CONFIG ===")
    for t, s, e in results[:5]:
        print(f"  T={t:+7.0f} | sigma={s:.3f} edge={e:.1f}")

if __name__ == "__main__":
    main()
