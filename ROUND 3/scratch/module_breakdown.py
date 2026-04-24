"""module_breakdown.py — PnL attribution per module (HP/VFE/VEV).

Runs trader1 with each module solo + all combined on day 0+1.
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
DAYS = [0, 1]


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
    spec = importlib.util.spec_from_file_location("user_trader1_breakdown", TRADER_PATH)
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
    _install_datamodel_alias()
    _patch_position_limits()
    from prosperity4bt.models import TradeMatchingMode

    trader_mod = _load_trader_module()
    Trader = trader_mod.Trader
    reader = _DirectFileReader(DATASET)
    match_mode = TradeMatchingMode.all

    # Best params from fast sweep
    Trader.HP_TAKE_EDGE = 1
    Trader.HP_OBI_THRESHOLD = 0.10
    Trader.HP_NEUTRAL_FRONT = 12

    configs = [
        ("ALL",          dict(ENABLE_HYDROGEL=True,  ENABLE_VFE=True,  ENABLE_VEV=True)),
        ("HYDROGEL_ONLY",dict(ENABLE_HYDROGEL=True,  ENABLE_VFE=False, ENABLE_VEV=False)),
        ("VFE_ONLY",     dict(ENABLE_HYDROGEL=False, ENABLE_VFE=True,  ENABLE_VEV=False)),
        ("VEV_ONLY",     dict(ENABLE_HYDROGEL=False, ENABLE_VFE=False, ENABLE_VEV=True)),
    ]

    for name, flags in configs:
        Trader.apply_params(flags)
        pnls = {}
        for d in DAYS:
            pnls[d] = _run_one_day(trader_mod, d, reader, match_mode)
        total = sum(pnls.values())
        day_str = " ".join(f"d{d}={pnls[d]:+.0f}" for d in DAYS)
        print(f"{name:20s} | {day_str}  TOTAL={total:+.0f}")

    # Reset
    Trader.ENABLE_HYDROGEL = True
    Trader.ENABLE_VFE = True
    Trader.ENABLE_VEV = True


if __name__ == "__main__":
    main()
