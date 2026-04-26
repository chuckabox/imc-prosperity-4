#!/usr/bin/env python3
"""Run jmerle-style `prosperity4bt` against a trader and emit a metrics.json
that the Rust Backtester dashboard tab can aggregate alongside native Rust runs.

    python tools/run_prosperity4bt.py
    python tools/run_prosperity4bt.py --trader "ROUND 2/traders/ken/trader_ken_v6.py" \
        --dataset "ROUND 2/data_capsule" --day 1

Output goes to ``external/prosperity_rust_backtester/runs/p4bt-<ts>-<dataset>-day-<d>/metrics.json``
so the existing dashboard walker picks it up automatically. Each JSON carries
``"engine": "prosperity4bt"`` to distinguish it from native Rust runs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRADER = REPO_ROOT / "ROUND 3" / "traders" / "ken" / "we_found_vfe_gold2.py"
DEFAULT_DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"
DEFAULT_RUNS_DIR = REPO_ROOT / "external" / "prosperity_rust_backtester" / "runs"


def _ensure_prosperity4bt() -> None:
    try:
        import prosperity4bt  # noqa: F401
    except ImportError:
        print("ERROR: `prosperity4bt` is not installed. Run: pip install prosperity4bt", file=sys.stderr)
        sys.exit(1)


def _install_datamodel_alias() -> None:
    from prosperity4bt import datamodel as p4_datamodel
    sys.modules.setdefault("datamodel", p4_datamodel)


# Position limits mirrored from external/prosperity_rust_backtester/src/runner.rs
# so both engines enforce the same caps. prosperity4bt's bundled LIMITS only
# covers round-0 tutorial products, which makes it crash on R1/R2 symbols.
POSITION_LIMITS: dict[str, int] = {
    "EMERALDS": 80,
    "TOMATOES": 80,
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM": 80,
    "RAINFOREST_RESIN": 50,
    "KELP": 50,
    "SQUID_INK": 50,
    "CROISSANTS": 250,
    "JAMS": 350,
    "DJEMBES": 60,
    "PICNIC_BASKET1": 60,
    "PICNIC_BASKET2": 100,
    "VOLCANIC_ROCK": 400,
    "VOLCANIC_ROCK_VOUCHER_9500": 200,
    "VOLCANIC_ROCK_VOUCHER_9750": 200,
    "VOLCANIC_ROCK_VOUCHER_10000": 200,
    "VOLCANIC_ROCK_VOUCHER_10250": 200,
    "VOLCANIC_ROCK_VOUCHER_10500": 200,
    "MAGNIFICENT_MACARONS": 75,
    # Round 3 — confirmed from live first-tick logs and trader LIMITS dicts.
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 100,
    "VEV_4500": 100,
    "VEV_5000": 100,
    "VEV_5100": 100,
    "VEV_5200": 100,
    "VEV_5300": 100,
    "VEV_5400": 100,
    "VEV_5500": 100,
    "VEV_6000": 100,
    "VEV_6500": 100,
}


def _patch_position_limits() -> None:
    """Override prosperity4bt LIMITS with confirmed round-specific values."""
    from prosperity4bt import data as p4_data
    for sym, lim in POSITION_LIMITS.items():
        p4_data.LIMITS[sym] = lim


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
        raise AttributeError(f"{path} does not define a Trader class")
    return mod.Trader()


class DirectFileReader:
    """FileReader that points at a flat directory containing ``prices_round_N_day_D.csv``.

    prosperity4bt asks for ``[f"round{N}", f"prices_round_{N}_day_{D}.csv"]``; we
    ignore the first component so a directory like ``ROUND 2/data_capsule`` works.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def file(self, path_parts):
        target = self._root
        for part in path_parts[1:]:
            target = target / part

        @contextmanager
        def _ctx():
            yield target if target.is_file() else None

        return _ctx()


def _detect_round_and_days(dataset: Path):
    days: list[int] = []
    round_num: int | None = None
    for csv in dataset.glob("prices_round_*_day_*.csv"):
        m = re.match(r"prices_round_(-?\d+)_day_(-?\d+)\.csv", csv.name)
        if not m:
            continue
        round_num = int(m.group(1))
        days.append(int(m.group(2)))
    return round_num, sorted(set(days))


def _summarise(result) -> tuple[dict, float, int]:
    if not result.activity_logs:
        return {}, 0.0, 0
    last_ts = result.activity_logs[-1].timestamp
    pnl_by_product: dict[str, float] = {}
    for row in reversed(result.activity_logs):
        if row.timestamp != last_ts:
            break
        product = row.columns[2]
        pnl_by_product[product] = float(row.columns[-1])
    own_trade_count = 0
    for trade_row in result.trades:
        t = trade_row.trade
        if getattr(t, "buyer", "") == "SUBMISSION" or getattr(t, "seller", "") == "SUBMISSION":
            own_trade_count += 1
    return pnl_by_product, sum(pnl_by_product.values()), own_trade_count


def main() -> int:
    _ensure_prosperity4bt()
    _install_datamodel_alias()
    _patch_position_limits()

    parser = argparse.ArgumentParser(description="Run prosperity4bt and emit a Rust-dashboard-compatible metrics.json.")
    parser.add_argument("--trader", type=Path, default=DEFAULT_TRADER)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--day", type=int, default=None, help="Single day to run (default: every day found).")
    parser.add_argument("--round", type=int, default=None, help="Round number (auto-detected from filenames if omitted).")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--match-trades", choices=["all", "worse", "none"], default="all")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args()

    trader_path = args.trader.resolve()
    dataset_path = args.dataset.resolve()
    if not trader_path.is_file():
        print(f"ERROR: Trader file not found: {trader_path}", file=sys.stderr)
        return 1
    if not dataset_path.is_dir():
        print(f"ERROR: Dataset directory not found: {dataset_path}", file=sys.stderr)
        return 1

    round_num, all_days = _detect_round_and_days(dataset_path)
    if args.round is not None:
        round_num = args.round
    if round_num is None:
        print(f"ERROR: could not detect round from {dataset_path}; pass --round", file=sys.stderr)
        return 1
    days = [args.day] if args.day is not None else all_days
    if not days:
        print(f"ERROR: no prices_round_{round_num}_day_*.csv files in {dataset_path}", file=sys.stderr)
        return 1

    from prosperity4bt.models import TradeMatchingMode
    from prosperity4bt.runner import run_backtest

    match_mode = {
        "all": TradeMatchingMode.all,
        "worse": TradeMatchingMode.worse,
        "none": TradeMatchingMode.none,
    }[args.match_trades]

    reader = DirectFileReader(dataset_path)
    ts_ms = int(time.time() * 1000)
    dataset_tag = dataset_path.name.replace("_", "-")
    runs_root = args.output_dir.resolve()
    runs_root.mkdir(parents=True, exist_ok=True)

    rc = 0
    for day in days:
        try:
            trader = _load_trader(trader_path)
        except Exception as e:
            print(f"ERROR: failed to load trader {trader_path}: {e}", file=sys.stderr)
            return 1

        print(f"[prosperity4bt] {trader_path.name} round={round_num} day={day}")
        try:
            result = run_backtest(
                trader=trader,
                file_reader=reader,
                round_num=round_num,
                day_num=day,
                print_output=False,
                trade_matching_mode=match_mode,
                no_names=False,
                show_progress_bar=not args.no_progress,
            )
        except Exception as e:
            print(f"  run_backtest failed: {e}", file=sys.stderr)
            rc = 1
            continue

        pnl_by_product, pnl_total, own_trades = _summarise(result)
        run_id = f"p4bt-{ts_ms}-{dataset_tag}-day-{day}"
        out_dir = runs_root / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        metrics = {
            "engine": "prosperity4bt",
            "run_id": run_id,
            "trader_path": str(trader_path),
            "dataset_id": f"prices_round_{round_num}_day_{day}",
            "dataset_path": str((dataset_path / f"prices_round_{round_num}_day_{day}.csv").resolve()),
            "day": day,
            "tick_count": len(result.activity_logs),
            "own_trade_count": own_trades,
            "final_pnl_total": float(pnl_total),
            "final_pnl_by_product": {k: float(v) for k, v in pnl_by_product.items()},
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "matching": {"trade_match_mode": args.match_trades},
        }
        (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
        print(f"  -> {out_dir.relative_to(REPO_ROOT)}  PnL={pnl_total:,.0f}  trades={own_trades}")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
