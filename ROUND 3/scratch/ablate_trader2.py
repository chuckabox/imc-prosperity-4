"""Ablation: enable one module at a time. Days 0+1."""
from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRADER_PATH = REPO_ROOT / "ROUND 3" / "traders" / "peter" / "trader2.py"
DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"
ROUND_NUM = 3
TRAIN_DAYS = [0, 1]


def _setup():
    from prosperity4bt import datamodel as p4_datamodel
    sys.modules.setdefault("datamodel", p4_datamodel)
    from prosperity4bt import data as p4_data
    extra = {"HYDROGEL_PACK": 80, "VELVETFRUIT_EXTRACT": 80,
             **{f"VEV_{k}": 60 for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]}}
    for k, v in extra.items():
        p4_data.LIMITS.setdefault(k, v)


class _DirectFileReader:
    def __init__(self, root): self._root = root
    def file(self, parts):
        target = self._root
        for p in parts[1:]: target = target / p
        @contextmanager
        def _ctx(): yield target if target.is_file() else None
        return _ctx()


def _per_product_pnl(result):
    if not result.activity_logs: return {}
    last_ts = result.activity_logs[-1].timestamp
    out = {}
    for row in reversed(result.activity_logs):
        if row.timestamp != last_ts: break
        out[row.columns[2]] = out.get(row.columns[2], 0.0) + float(row.columns[-1])
    return out


def _load():
    sys.path.insert(0, str(TRADER_PATH.parent))
    spec = importlib.util.spec_from_file_location("ablate_t2", TRADER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_config(mod, cfg_name, flags):
    from prosperity4bt.runner import run_backtest
    from prosperity4bt.models import TradeMatchingMode
    Tr = mod.Trader
    for k, v in flags.items():
        setattr(Tr, k, v)
    reader = _DirectFileReader(DATASET)
    total = 0
    parts = []
    for d in TRAIN_DAYS:
        trader = Tr()
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            r = run_backtest(trader=trader, file_reader=reader, round_num=ROUND_NUM, day_num=d,
                             print_output=False, trade_matching_mode=TradeMatchingMode.all,
                             no_names=False, show_progress_bar=False)
        per = _per_product_pnl(r)
        day_pnl = sum(per.values())
        total += day_pnl
        parts.append(f"d{d}={day_pnl:+,.0f}")
    return total, parts


def main():
    _setup()
    mod = _load()

    configs = [
        ("HP only",         dict(ENABLE_HYDROGEL=True, ENABLE_VFE_REVERSION=False, ENABLE_VEV_GAMMA=False, ENABLE_IV_SCALP=False, ENABLE_HEDGE=False)),
        ("HP+VEV gamma",    dict(ENABLE_HYDROGEL=True, ENABLE_VFE_REVERSION=False, ENABLE_VEV_GAMMA=True,  ENABLE_IV_SCALP=False, ENABLE_HEDGE=False)),
        ("HP+VEV+IV",       dict(ENABLE_HYDROGEL=True, ENABLE_VFE_REVERSION=False, ENABLE_VEV_GAMMA=True,  ENABLE_IV_SCALP=True,  ENABLE_HEDGE=False)),
        ("HP+VEV+IV+hedge", dict(ENABLE_HYDROGEL=True, ENABLE_VFE_REVERSION=False, ENABLE_VEV_GAMMA=True,  ENABLE_IV_SCALP=True,  ENABLE_HEDGE=True)),
        ("HP+VFE rev",      dict(ENABLE_HYDROGEL=True, ENABLE_VFE_REVERSION=True,  ENABLE_VEV_GAMMA=False, ENABLE_IV_SCALP=False, ENABLE_HEDGE=False)),
        ("All on",          dict(ENABLE_HYDROGEL=True, ENABLE_VFE_REVERSION=True,  ENABLE_VEV_GAMMA=True,  ENABLE_IV_SCALP=True,  ENABLE_HEDGE=True)),
    ]
    print(f"{'Config':22s}  {'Total':>12s}  Per-day")
    for name, flags in configs:
        total, parts = run_config(mod, name, flags)
        print(f"{name:22s}  {total:>+12,.0f}  {' '.join(parts)}")


if __name__ == "__main__":
    main()
