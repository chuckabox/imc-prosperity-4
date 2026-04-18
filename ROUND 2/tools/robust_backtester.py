"""
Robust Multi-Scenario Backtester for IMC Prosperity 4
======================================================
Runs a trader against available CSV sessions.

Default (no extra flags): **IMC historical days only** (``prices_round_*_day_*.csv`` in ``data_capsule``).

Optional:
  - ``--with-scenarios`` — synthetic regime scenarios
  - ``--with-real-world`` — normalized real-world cache under ``data_capsule/real_world/normalized`` (offline; no network)
  - ``--full-legacy`` — same as enabling both (old default mix)

Reports average, median, worst-case PNL and robustness metrics.

Usage:
    python robust_backtester.py <trader_file>
    python robust_backtester.py <trader_file> --with-scenarios
    python robust_backtester.py <trader_file> --full-legacy
    python robust_backtester.py <trader_file> --imc-only
    python robust_backtester.py <trader_file> --scenarios-only
    python robust_backtester.py <trader_file> --quick
    python robust_backtester.py <trader_file> --r2
    python robust_backtester.py <trader_file> --r1 --imc-only
    python robust_backtester.py <trader_file> --r1 --r2 --imc-only
"""

import sys
import os
import json
import math
import argparse
import importlib.util
import re
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data_capsule"
SCENARIO_DIR = DATA_DIR / "scenarios"
REAL_DIR = DATA_DIR / "real_world" / "normalized"
RESULTS_DIR = PROJECT_ROOT / "results" / "robust"

sys.path.insert(0, str(PROJECT_ROOT / "config"))
from datamodel import Listing, OrderDepth, TradingState, Observation, Order


@dataclass
class BacktestResult:
    name: str
    category: str
    final_pnl: float
    pnl_osmium: float
    pnl_pepper: float
    max_drawdown: float
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_position: Dict[str, int] = field(default_factory=dict)
    trade_count: int = 0
    pnl_curve: List[float] = field(default_factory=list)
    # --- trade-level stats (FIFO realized P&L per round-trip) ---
    rt_wins: int = 0            # closed round-trip chunks with realized PnL > 0
    rt_losses: int = 0          # closed round-trip chunks with realized PnL < 0
    rt_pushes: int = 0          # exactly zero PnL (scratches)
    avg_win: float = 0.0        # mean realized $ per winning round-trip
    avg_loss: float = 0.0       # mean realized $ per losing round-trip (negative)

    @property
    def trade_win_rate(self) -> float:
        """Win rate on CLOSED round-trips (pushes excluded). 0 if no closed trades."""
        denom = self.rt_wins + self.rt_losses
        return (self.rt_wins / denom) if denom > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        """Sum of winning $ / abs(sum of losing $). >1 = profitable system."""
        gross_win = self.rt_wins * self.avg_win
        gross_loss = abs(self.rt_losses * self.avg_loss)
        return (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0


class _FifoBook:
    """FIFO inventory tracker. Feed fills; it emits realized P&L per matched slice."""
    __slots__ = ("long_q", "short_q", "wins", "losses", "pushes", "win_sum", "loss_sum")

    def __init__(self):
        # each queue element = [entry_price, qty_remaining]
        self.long_q: List[List[float]] = []
        self.short_q: List[List[float]] = []
        self.wins = 0
        self.losses = 0
        self.pushes = 0
        self.win_sum = 0.0
        self.loss_sum = 0.0

    def fill(self, price: float, qty: int) -> None:
        """qty>0 = buy, qty<0 = sell."""
        if qty > 0:
            # close shorts first
            while qty > 0 and self.short_q:
                head = self.short_q[0]
                matched = min(qty, head[1])
                realized = (head[0] - price) * matched
                self._record(realized)
                head[1] -= matched
                qty -= matched
                if head[1] <= 0:
                    self.short_q.pop(0)
            if qty > 0:
                self.long_q.append([price, qty])
        elif qty < 0:
            qty = -qty
            while qty > 0 and self.long_q:
                head = self.long_q[0]
                matched = min(qty, head[1])
                realized = (price - head[0]) * matched
                self._record(realized)
                head[1] -= matched
                qty -= matched
                if head[1] <= 0:
                    self.long_q.pop(0)
            if qty > 0:
                self.short_q.append([price, qty])

    def _record(self, realized: float) -> None:
        if realized > 0:
            self.wins += 1
            self.win_sum += realized
        elif realized < 0:
            self.losses += 1
            self.loss_sum += realized
        else:
            self.pushes += 1


def load_trader(trader_file: str):
    module_name = f"trader_{Path(trader_file).stem}_{id(trader_file)}"
    spec = importlib.util.spec_from_file_location(module_name, trader_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    trader = module.Trader()
    del sys.modules[module_name]
    return trader


def run_backtest_on_csv(trader_file: str, csv_path: str, name: str, category: str) -> Optional[BacktestResult]:
    try:
        df = pd.read_csv(csv_path, sep=";")
    except Exception as e:
        print(f"    SKIP {name}: {e}")
        return None

    df = df.dropna(subset=["bid_price_1", "ask_price_1"])

    trader = load_trader(trader_file)
    listings = {
        "ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "SEASHELLS"),
        "INTARIAN_PEPPER_ROOT": Listing("INTARIAN_PEPPER_ROOT", "INTARIAN_PEPPER_ROOT", "SEASHELLS"),
    }

    cash_per_product = {"ASH_COATED_OSMIUM": 0.0, "INTARIAN_PEPPER_ROOT": 0.0}
    positions = {"ASH_COATED_OSMIUM": 0, "INTARIAN_PEPPER_ROOT": 0}
    fifo = {"ASH_COATED_OSMIUM": _FifoBook(), "INTARIAN_PEPPER_ROOT": _FifoBook()}
    pnl_history = []
    trade_count = 0
    max_pos = {"ASH_COATED_OSMIUM": 0, "INTARIAN_PEPPER_ROOT": 0}
    trader_data = ""

    grouped = df.groupby("timestamp")

    for ts, group in grouped:
        order_depths = {}
        mid_prices = {}
        for _, row in group.iterrows():
            product = row["product"]
            depth = OrderDepth()
            depth.buy_orders[int(row["bid_price_1"])] = int(row["bid_volume_1"])
            depth.sell_orders[int(row["ask_price_1"])] = -int(row["ask_volume_1"])
            if not pd.isna(row.get("bid_price_2", float("nan"))):
                try:
                    depth.buy_orders[int(row["bid_price_2"])] = int(row["bid_volume_2"])
                except (ValueError, TypeError):
                    pass
            if not pd.isna(row.get("ask_price_2", float("nan"))):
                try:
                    depth.sell_orders[int(row["ask_price_2"])] = -int(row["ask_volume_2"])
                except (ValueError, TypeError):
                    pass
            order_depths[product] = depth
            mid_prices[product] = (int(row["bid_price_1"]) + int(row["ask_price_1"])) / 2.0

        state = TradingState(
            traderData=trader_data,
            timestamp=ts,
            listings=listings,
            order_depths=order_depths,
            own_trades={},
            market_trades={},
            position=dict(positions),
            observations=Observation({}, {}),
        )

        try:
            orders, _, new_data = trader.run(state)
            trader_data = new_data
        except Exception:
            continue

        for product, order_list in orders.items():
            if product not in order_depths:
                continue
            depth = order_depths[product]
            limit = 80

            for order in order_list:
                qty = order.quantity
                price = order.price

                if qty > 0:
                    for ask in sorted(depth.sell_orders.keys()):
                        if price >= ask and qty > 0:
                            avail = -depth.sell_orders[ask]
                            fill = min(qty, avail, limit - positions[product])
                            if fill > 0:
                                positions[product] += fill
                                cash_per_product[product] -= fill * ask
                                fifo[product].fill(ask, fill)
                                qty -= fill
                                trade_count += 1
                elif qty < 0:
                    for bid in sorted(depth.buy_orders.keys(), reverse=True):
                        if price <= bid and qty < 0:
                            avail = depth.buy_orders[bid]
                            fill = min(-qty, avail, limit + positions[product])
                            if fill > 0:
                                positions[product] -= fill
                                cash_per_product[product] += fill * bid
                                fifo[product].fill(bid, -fill)
                                qty += fill
                                trade_count += 1

            max_pos[product] = max(max_pos[product], abs(positions[product]))

        mtm = sum(cash_per_product.values())
        for product, pos in positions.items():
            if product in mid_prices:
                mtm += pos * mid_prices[product]
        pnl_history.append(mtm)

    if not pnl_history:
        return None

    peak = 0.0
    max_dd = 0.0
    for pnl in pnl_history:
        if pnl > peak:
            peak = pnl
        dd = peak - pnl
        if dd > max_dd:
            max_dd = dd

    pnl_os = cash_per_product["ASH_COATED_OSMIUM"] + (positions["ASH_COATED_OSMIUM"] * mid_prices["ASH_COATED_OSMIUM"] if "ASH_COATED_OSMIUM" in mid_prices else 0)
    pnl_pp = cash_per_product["INTARIAN_PEPPER_ROOT"] + (positions["INTARIAN_PEPPER_ROOT"] * mid_prices["INTARIAN_PEPPER_ROOT"] if "INTARIAN_PEPPER_ROOT" in mid_prices else 0)

    # Calculate local Sharpe/Sortino for this specific run
    returns = np.diff(pnl_history)
    if len(returns) > 1:
        std = np.std(returns)
        sharpe = (np.mean(returns) / std * np.sqrt(len(returns))) if std > 0 else 0
        downside_returns = returns[returns < 0]
        downside_std = np.std(downside_returns) if len(downside_returns) > 1 else std
        sortino = (np.mean(returns) / downside_std * np.sqrt(len(returns))) if downside_std > 0 else 0
        calmar = (pnl_history[-1] / max_dd) if max_dd > 0 else 0
    else:
        sharpe = sortino = calmar = 0

    # aggregate FIFO round-trip stats across products
    rt_wins   = sum(b.wins for b in fifo.values())
    rt_losses = sum(b.losses for b in fifo.values())
    rt_pushes = sum(b.pushes for b in fifo.values())
    total_win_sum  = sum(b.win_sum for b in fifo.values())
    total_loss_sum = sum(b.loss_sum for b in fifo.values())
    avg_win  = (total_win_sum  / rt_wins)   if rt_wins   > 0 else 0.0
    avg_loss = (total_loss_sum / rt_losses) if rt_losses > 0 else 0.0

    return BacktestResult(
        name=name,
        category=category,
        final_pnl=pnl_history[-1],
        pnl_osmium=pnl_os,
        pnl_pepper=pnl_pp,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        max_position=max_pos,
        trade_count=trade_count,
        pnl_curve=pnl_history,
        rt_wins=rt_wins,
        rt_losses=rt_losses,
        rt_pushes=rt_pushes,
        avg_win=avg_win,
        avg_loss=avg_loss,
    )


def _imc_round_from_path(p: Path) -> Optional[int]:
    """Return 1 or 2 from ``prices_round_N_day_*.csv`` stem, else None."""
    m = re.search(r"round_(\d+)_day_", p.name, re.I)
    if not m:
        return None
    return int(m.group(1))


def discover_datasets(
    imc_only: bool = False,
    scenarios_only: bool = False,
    quick: bool = False,
    imc_rounds: Optional[Set[int]] = None,
    with_scenarios: bool = False,
    with_real_world: bool = False,
) -> List[Tuple[str, str, str]]:
    """Discover CSV paths. ``imc_rounds`` filters IMC files by round number when set.

    By default only **IMC** historical capsule files are included. Synthetic scenarios and
    normalized real-world CSVs are opt-in via ``with_scenarios`` / ``with_real_world``.
    """
    datasets = []

    if not scenarios_only:
        # Search for all IMC price files in DATA_DIR
        price_files = sorted(DATA_DIR.glob("prices_round_*_day_*.csv"))
        for p in price_files:
            if imc_rounds is not None:
                r = _imc_round_from_path(p)
                if r is None or r not in imc_rounds:
                    continue
            # Extract name like imc_round2_day_1
            name = p.stem.replace("prices_", "imc_")
            datasets.append((name, str(p), "imc"))

    if imc_only and not scenarios_only:
        return datasets

    if not scenarios_only and with_real_world:
        if REAL_DIR.exists():
            real_files = sorted(REAL_DIR.glob("prices_*.csv"))
            if quick:
                real_files = real_files[::5]
            for f in real_files:
                datasets.append((f.stem.replace("prices_", ""), str(f), "real"))

    if SCENARIO_DIR.exists() and (scenarios_only or with_scenarios):
        scen_files = sorted(SCENARIO_DIR.glob("prices_*.csv"))
        if quick:
            seen_regimes = set()
            filtered = []
            for f in scen_files:
                regime = "_".join(f.stem.replace("prices_", "").split("_")[:-1])
                if regime not in seen_regimes:
                    seen_regimes.add(regime)
                    filtered.append(f)
            scen_files = filtered
        for f in scen_files:
            datasets.append((f.stem.replace("prices_", ""), str(f), "scenario"))

    return datasets


def run_robust_backtest(trader_file: str, datasets: List[Tuple[str, str, str]], tag: str = "default") -> Dict:
    results: List[BacktestResult] = []

    print(f"\nRunning {len(datasets)} backtests for: {trader_file}")
    print("=" * 70)

    for i, (name, path, category) in enumerate(datasets):
        progress_tag = f"[{i+1}/{len(datasets)}]"
        result = run_backtest_on_csv(trader_file, path, name, category)
        if result:
            marker = ""
            if result.final_pnl < -10000:
                marker = " *** BLOW UP ***"
            elif result.final_pnl < 0:
                marker = " (LOSS)"
            print(f"  {progress_tag} {name:45s} PnL: ${result.final_pnl:>12,.2f}  DD: ${result.max_drawdown:>10,.2f}{marker}")
            results.append(result)
        else:
            print(f"  {progress_tag} {name:45s} SKIPPED")

    if not results:
        print("No results!")
        return {}

    pnls = [r.final_pnl for r in results]
    dds = [r.max_drawdown for r in results]

    by_category = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r.final_pnl)

    stats = {
        "trader": trader_file,
        "total_datasets": len(results),
        "mean_pnl": float(np.mean(pnls)),
        "median_pnl": float(np.median(pnls)),
        "std_pnl": float(np.std(pnls)),
        "min_pnl": float(np.min(pnls)),
        "max_pnl": float(np.max(pnls)),
        "mean_sharpe": float(np.mean([r.sharpe_ratio for r in results])),
        "mean_sortino": float(np.mean([r.sortino_ratio for r in results])),
        "mean_calmar": float(np.mean([r.calmar_ratio for r in results])),
        "p5_pnl": float(np.percentile(pnls, 5)),
        "p25_pnl": float(np.percentile(pnls, 25)),
        "p75_pnl": float(np.percentile(pnls, 75)),
        "p95_pnl": float(np.percentile(pnls, 95)),
        "mean_drawdown": float(np.mean(dds)),
        "worst_drawdown": float(np.max(dds)),
        # Dataset-level metric: what fraction of sessions ended profitable.
        # Saturates at 100% for robust strategies and is NOT a skill signal
        # once blow-ups are eliminated. Kept for backwards compatibility.
        "positive_sessions_rate": sum(1 for p in pnls if p > 0) / len(pnls),
        "blow_up_rate": sum(1 for p in pnls if p < -10000) / len(pnls),
        # --- Trade-level metrics (FIFO round-trip realized P&L) ---
        # Aggregated across every closed round-trip in every session.
        # This is the real "win rate": does the strategy close more winning
        # round-trips than losers? A 50% rate with avg_win > |avg_loss| is a
        # winning system.
        "total_round_trips": sum(r.rt_wins + r.rt_losses + r.rt_pushes for r in results),
        "total_rt_wins":    sum(r.rt_wins for r in results),
        "total_rt_losses":  sum(r.rt_losses for r in results),
        "total_rt_pushes":  sum(r.rt_pushes for r in results),
        "trade_win_rate": (
            sum(r.rt_wins for r in results)
            / max(1, sum(r.rt_wins + r.rt_losses for r in results))
        ),
        "avg_win_pnl":  (
            sum(r.rt_wins * r.avg_win for r in results)
            / max(1, sum(r.rt_wins for r in results))
        ),
        "avg_loss_pnl": (
            sum(r.rt_losses * r.avg_loss for r in results)
            / max(1, sum(r.rt_losses for r in results))
        ),
        "profit_factor": (
            sum(r.rt_wins * r.avg_win for r in results)
            / max(1e-9, abs(sum(r.rt_losses * r.avg_loss for r in results)))
        ),
        "by_category": {cat: {
            "count": len(vals),
            "mean": float(np.mean(vals)),
            "min": float(np.min(vals)),
            "max": float(np.max(vals)),
            "mean_sharpe": float(np.mean([r.sharpe_ratio for r in results if r.category == cat])),
            "trade_win_rate": (
                sum(r.rt_wins for r in results if r.category == cat)
                / max(1, sum(r.rt_wins + r.rt_losses for r in results if r.category == cat))
            ),
        } for cat, vals in by_category.items()},
    }

    print("\n" + "=" * 70)
    print("ROBUST BACKTEST SUMMARY")
    print("=" * 70)
    print(f"Trader:          {trader_file}")
    print(f"Datasets tested: {stats['total_datasets']}")
    print()
    print("PnL Distribution:")
    print(f"  Mean PnL:      ${stats['mean_pnl']:>12,.2f}  <-- THE TARGET METRIC")
    print(f"  Median PnL:    ${stats['median_pnl']:>12,.2f}")
    print(f"  Std Dev:       ${stats['std_pnl']:>12,.2f}")
    print()
    print("Risk-Adjusted Metrics (Averaged):")
    print(f"  Mean Sharpe:    {stats['mean_sharpe']:>12.4f}")
    print(f"  Mean Sortino:   {stats['mean_sortino']:>12.4f}")
    print(f"  Mean Calmar:    {stats['mean_calmar']:>12.4f}")
    print()
    print("Risk Metrics:")
    print(f"  Worst PnL:     ${stats['min_pnl']:>12,.2f}")
    print(f"  Best PnL:      ${stats['max_pnl']:>12,.2f}")
    print(f"  5th %ile:      ${stats['p5_pnl']:>12,.2f}")
    print(f"  95th %ile:     ${stats['p95_pnl']:>12,.2f}")
    print(f"  Positive Sessions:  {stats['positive_sessions_rate']*100:>6.1f}%  (sessions ending green; saturates at 100% for robust strats)")
    print(f"  Blow-up Rate:       {stats['blow_up_rate']*100:>6.1f}%")
    print(f"  Worst DD:      ${stats['worst_drawdown']:>12,.2f}")
    print()
    print("Trade-Level Stats (FIFO round-trip realized P&L):")
    print(f"  Round-trips:    {stats['total_round_trips']:>12,d}  "
          f"(W:{stats['total_rt_wins']:,}  L:{stats['total_rt_losses']:,}  "
          f"P:{stats['total_rt_pushes']:,})")
    print(f"  Trade Win Rate: {stats['trade_win_rate']*100:>11.2f}%  <-- real edge signal")
    print(f"  Avg Win:       ${stats['avg_win_pnl']:>12,.2f}")
    print(f"  Avg Loss:      ${stats['avg_loss_pnl']:>12,.2f}")
    print(f"  Profit Factor:  {stats['profit_factor']:>12.2f}  (>1 = winning system)")
    print()
    print("By Category:")
    for cat, cat_stats in stats["by_category"].items():
        print(f"  {cat:12s}: n={cat_stats['count']:>3d}  mean=${cat_stats['mean']:>10,.2f}  "
              f"Sharpe={cat_stats['mean_sharpe']:>6.2f}  "
              f"trade_wr={cat_stats['trade_win_rate']*100:>5.1f}%  "
              f"range=[${cat_stats['min']:>10,.2f}, ${cat_stats['max']:>10,.2f}]")
    print("=" * 70)

    out_tag = tag
    if out_tag == "default" and len(datasets) < 50: # Heuristic for manual overrides
        out_tag = "quick"
        
    out_csv = f"{Path(trader_file).stem}_{out_tag}_robust_results.csv"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / out_csv
    rows = []
    for r in results:
        rows.append({
            "name": r.name,
            "category": r.category,
            "final_pnl": r.final_pnl,
            "pnl_osmium": r.pnl_osmium,
            "pnl_pepper": r.pnl_pepper,
            "max_drawdown": r.max_drawdown,
            "sharpe": r.sharpe_ratio,
            "sortino": r.sortino_ratio,
            "calmar": r.calmar_ratio,
            "trade_count": r.trade_count,
            "rt_wins": r.rt_wins,
            "rt_losses": r.rt_losses,
            "rt_pushes": r.rt_pushes,
            "trade_win_rate": r.trade_win_rate,
            "avg_win": r.avg_win,
            "avg_loss": r.avg_loss,
            "profit_factor": r.profit_factor,
        })
    pd.DataFrame(rows).to_csv(out_path, index=False)
    print(f"\nDetailed results saved to: {out_path}")

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Robust multi-scenario backtester")
    parser.add_argument("trader", help="Path to trader .py file")
    parser.add_argument(
        "--imc-only",
        action="store_true",
        help="Only test IMC historical data (default already; kept for scripts)",
    )
    parser.add_argument("--scenarios-only", action="store_true", help="Only test synthetic scenarios")
    parser.add_argument(
        "--with-scenarios",
        action="store_true",
        help="Include synthetic scenario CSVs in addition to IMC days",
    )
    parser.add_argument(
        "--with-real-world",
        action="store_true",
        help="Include normalized real_world CSVs (local cache only; no network)",
    )
    parser.add_argument(
        "--full-legacy",
        action="store_true",
        help="IMC + scenarios + real-world (previous default dataset mix)",
    )
    parser.add_argument("--quick", action="store_true", help="Subset for speed (1 per regime)")
    parser.add_argument(
        "--r1",
        action="store_true",
        help="Include only Round 1 IMC days (prices_round_1_day_*.csv). Combine with --r2 for both.",
    )
    parser.add_argument(
        "--r2",
        action="store_true",
        help="Include only Round 2 IMC days (prices_round_2_day_*.csv). Combine with --r1 for both.",
    )
    parser.add_argument("--tag", type=str, default=None, help="Custom tag for this run (e.g. 'v4-beta')")
    args = parser.parse_args()

    imc_rounds: Optional[Set[int]] = None
    if args.r1 or args.r2:
        imc_rounds = set()
        if args.r1:
            imc_rounds.add(1)
        if args.r2:
            imc_rounds.add(2)

    # Determine automatic tag if none provided
    if args.tag:
        run_tag = args.tag
    elif args.quick:
        run_tag = "quick"
    elif args.imc_only and imc_rounds == {1}:
        run_tag = "imc_r1"
    elif args.imc_only and imc_rounds == {2}:
        run_tag = "imc_r2"
    elif args.imc_only and imc_rounds == {1, 2}:
        run_tag = "imc_r1_r2"
    elif imc_rounds == {1}:
        run_tag = "r1"
    elif imc_rounds == {2}:
        run_tag = "r2"
    elif imc_rounds == {1, 2}:
        run_tag = "r1_r2"
    elif args.imc_only:
        run_tag = "imc"
    elif args.scenarios_only:
        run_tag = "scenarios"
    elif args.full_legacy or (args.with_scenarios and args.with_real_world):
        run_tag = "full_legacy"
    elif args.with_scenarios:
        run_tag = "imc_scen"
    elif args.with_real_world:
        run_tag = "imc_real"
    else:
        run_tag = "imc"

    with_scenarios = args.scenarios_only or args.with_scenarios or args.full_legacy
    with_real_world = args.with_real_world or args.full_legacy

    datasets = discover_datasets(
        imc_only=args.imc_only,
        scenarios_only=args.scenarios_only,
        quick=args.quick,
        imc_rounds=imc_rounds,
        with_scenarios=with_scenarios,
        with_real_world=with_real_world,
    )
    if imc_rounds is not None:
        n_imc = sum(1 for _, _, c in datasets if c == "imc")
        print(
            f"IMC round filter {sorted(imc_rounds)}: {n_imc} historical day file(s); "
            f"total datasets this run: {len(datasets)}"
        )
    run_robust_backtest(args.trader, datasets, tag=run_tag)
