#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"

POSITION_LIMITS: dict[str, int] = {
    "HYDROGEL_PACK": 80,
    "VELVETFRUIT_EXTRACT": 80,
    "VEV_4000": 60,
    "VEV_4500": 60,
    "VEV_5000": 60,
    "VEV_5100": 60,
    "VEV_5200": 60,
    "VEV_5300": 60,
    "VEV_5400": 60,
    "VEV_5500": 60,
    "VEV_6000": 60,
    "VEV_6500": 60,
}


@dataclass
class DayRisk:
    day: int
    final_pnl: float
    max_dd: float
    rf: float


@dataclass
class TraderRisk:
    trader: str
    days: List[DayRisk]

    @property
    def total_pnl(self) -> float:
        return sum(d.final_pnl for d in self.days)

    @property
    def total_max_dd(self) -> float:
        return sum(d.max_dd for d in self.days)

    @property
    def total_rf(self) -> float:
        dd = self.total_max_dd
        if dd <= 1e-9:
            return math.inf
        return self.total_pnl / dd


def _ensure_prosperity4bt() -> None:
    try:
        import prosperity4bt  # noqa: F401
    except ImportError:
        print("ERROR: `prosperity4bt` missing. Install with: pip install prosperity4bt", file=sys.stderr)
        raise SystemExit(1)


def _install_datamodel_alias() -> None:
    from prosperity4bt import datamodel as p4_datamodel
    sys.modules.setdefault("datamodel", p4_datamodel)


def _patch_position_limits() -> None:
    from prosperity4bt import data as p4_data
    for sym, lim in POSITION_LIMITS.items():
        p4_data.LIMITS.setdefault(sym, lim)


def _load_trader(path: Path):
    sys.path.insert(0, str(path.parent))
    if (path.parent.parent / "datamodel.py").exists():
        sys.path.insert(0, str(path.parent.parent))
    spec = importlib.util.spec_from_file_location(f"user_trader_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "Trader"):
        raise AttributeError(f"{path} does not define Trader")
    return mod.Trader()


class DirectFileReader:
    def __init__(self, root: Path) -> None:
        self._root = root

    def file(self, path_parts):
        target = self._root
        for part in path_parts[1:]:
            target = target / part
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            yield target if target.is_file() else None

        return _ctx()


def _detect_days(dataset: Path) -> List[int]:
    out: List[int] = []
    for csv in dataset.glob("prices_round_3_day_*.csv"):
        name = csv.name
        day = int(name.replace("prices_round_3_day_", "").replace(".csv", ""))
        out.append(day)
    return sorted(set(out))


def _final_pnl_series(result) -> List[float]:
    # activity_logs has one row per product per timestamp.
    # Build a portfolio-level pnl series by summing final pnl across products each tick.
    by_ts: dict[int, float] = {}
    for row in result.activity_logs:
        ts = int(row.timestamp)
        by_ts[ts] = by_ts.get(ts, 0.0) + float(row.columns[-1])
    return [by_ts[t] for t in sorted(by_ts.keys())]


def _max_drawdown(series: List[float]) -> float:
    if not series:
        return 0.0
    peak = series[0]
    mdd = 0.0
    for x in series:
        if x > peak:
            peak = x
        dd = peak - x
        if dd > mdd:
            mdd = dd
    return mdd


def _run_day(trader_path: Path, dataset: Path, day: int) -> DayRisk:
    from prosperity4bt.models import TradeMatchingMode
    from prosperity4bt.runner import run_backtest

    trader = _load_trader(trader_path)
    result = run_backtest(
        trader=trader,
        file_reader=DirectFileReader(dataset),
        round_num=3,
        day_num=day,
        print_output=False,
        trade_matching_mode=TradeMatchingMode.all,
        no_names=False,
        show_progress_bar=False,
    )
    series = _final_pnl_series(result)
    final_pnl = series[-1] if series else 0.0
    mdd = _max_drawdown(series)
    rf = math.inf if mdd <= 1e-9 else final_pnl / mdd
    return DayRisk(day=day, final_pnl=final_pnl, max_dd=mdd, rf=rf)


def _fmtf(x: float) -> str:
    if math.isinf(x):
        return "inf"
    return f"{x:,.2f}"


def main() -> int:
    _ensure_prosperity4bt()
    _install_datamodel_alias()
    _patch_position_limits()

    parser = argparse.ArgumentParser(description="Compare Round 3 traders by PnL and recovery factor.")
    parser.add_argument(
        "--dataset",
        default=str(DEFAULT_DATASET.relative_to(REPO_ROOT)).replace("\\", "/"),
        help="Dataset dir relative to repo root (default: ROUND 3/data_capsule)",
    )
    parser.add_argument("traders", nargs="+", help="Trader paths relative to repo root")
    args = parser.parse_args()

    dataset = (REPO_ROOT / args.dataset).resolve()
    if not dataset.is_dir():
        print(f"ERROR: dataset not found: {dataset}", file=sys.stderr)
        return 1
    days = _detect_days(dataset)
    if not days:
        print("ERROR: no round 3 day files found", file=sys.stderr)
        return 1

    all_rows: List[TraderRisk] = []
    for trader_rel in args.traders:
        tp = (REPO_ROOT / trader_rel).resolve()
        rows = [_run_day(tp, dataset, d) for d in days]
        all_rows.append(TraderRisk(trader=trader_rel, days=rows))

    all_rows.sort(key=lambda r: (r.total_rf, r.total_pnl), reverse=True)
    print()
    print("Round 3 Recovery Comparison")
    print("-" * 122)
    print(f"{'Trader':55} {'TotalPnL':>10} {'TotalMDD':>10} {'TotalRF':>9} {'Day0 RF':>9} {'Day1 RF':>9} {'Day2 RF':>9}")
    print("-" * 122)
    for r in all_rows:
        by_day = {d.day: d for d in r.days}
        d0 = by_day.get(0)
        d1 = by_day.get(1)
        d2 = by_day.get(2)
        print(
            f"{r.trader[:55]:55} {r.total_pnl:>10.0f} {r.total_max_dd:>10.0f} {_fmtf(r.total_rf):>9} "
            f"{_fmtf(d0.rf if d0 else math.nan):>9} {_fmtf(d1.rf if d1 else math.nan):>9} {_fmtf(d2.rf if d2 else math.nan):>9}"
        )
    print("-" * 122)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

