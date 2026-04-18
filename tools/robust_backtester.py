"""
Unified Robust Multi-Scenario Backtester for IMC Prosperity 4
============================================================
Combined backtester that runs against data from ALL rounds:
  1. IMC historical days from Round 1, Round 2, and beyond
  2. Real-world normalized days (from Round 1 data capsule)
  3. Synthetic regime scenarios (from Round 1 data capsule)

Usage:
    python tools/robust_backtester.py <trader_file>
    python tools/robust_backtester.py <trader_file> --quick
    python tools/robust_backtester.py <trader_file> --rounds 1 2
    python tools/robust_backtester.py <trader_file> --imc  # Run only IMC historical days
"""

import sys
import os
import json
import math
import argparse
import importlib.util
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field

# Identify Repo Root
TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
RESULTS_DIR = REPO_ROOT / "ROUND 2" / "results" / "robust"

# Add config to sys.path for datamodel
# We'll prefer Round 2's config as it's the latest, but they should be the same
sys.path.insert(0, str(REPO_ROOT / "ROUND 2" / "config"))
try:
    from datamodel import Listing, OrderDepth, TradingState, Observation, Order
except ImportError:
    # Fallback to Round 1 if Round 2 doesn't exist for some reason
    sys.path.insert(0, str(REPO_ROOT / "ROUND 1" / "config"))
    from datamodel import Listing, OrderDepth, TradingState, Observation, Order

@dataclass
class BacktestResult:
    name: str
    category: str
    final_pnl: float
    product_pnls: Dict[str, float] = field(default_factory=dict)
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_position: Dict[str, int] = field(default_factory=dict)
    trade_count: int = 0
    pnl_curve: List[float] = field(default_factory=list)

def load_trader(trader_file: str):
    trader_path = Path(trader_file).resolve()
    trader_dir = str(trader_path.parent)
    
    if trader_dir not in sys.path:
        sys.path.insert(0, trader_dir)
        
    module_name = f"trader_{trader_path.stem}_{id(trader_file)}"
    spec = importlib.util.spec_from_file_location(module_name, str(trader_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    trader = module.Trader()
    
    # We leave sys.path as is to support nested imports during trader run
    return trader

def run_backtest_on_csv(trader_file: str, csv_path: str, name: str, category: str) -> Optional[BacktestResult]:
    try:
        df = pd.read_csv(csv_path, sep=";")
    except Exception as e:
        print(f"    SKIP {name}: {e}")
        return None

    if "product" not in df.columns:
        print(f"    SKIP {name}: No 'product' column found.")
        return None

    df = df.dropna(subset=["bid_price_1", "ask_price_1"])
    
    # Identify products in this dataset
    unique_products = df["product"].unique()
    
    trader = load_trader(trader_file)
    
    # Setup listings
    listings = {p: Listing(p, p, "SEASHELLS") for p in unique_products}

    cash_per_product = {p: 0.0 for p in unique_products}
    positions = {p: 0 for p in unique_products}
    pnl_history = []
    trade_count = 0
    max_pos = {p: 0 for p in unique_products}
    trader_data = ""

    grouped = df.groupby("timestamp")
    last_known_prices = {}

    for ts, group in grouped:
        order_depths = {}
        mid_prices = {}
        for _, row in group.iterrows():
            product = row["product"]
            depth = OrderDepth()
            
            # Populate bid orders
            for i in range(1, 4):
                p_col = f"bid_price_{i}"
                v_col = f"bid_volume_{i}"
                if p_col in row and not pd.isna(row[p_col]):
                    depth.buy_orders[int(row[p_col])] = int(row[v_col])
            
            # Populate ask orders
            for i in range(1, 4):
                p_col = f"ask_price_{i}"
                v_col = f"ask_volume_{i}"
                if p_col in row and not pd.isna(row[p_col]):
                    depth.sell_orders[int(row[p_col])] = -int(row[v_col])
                    
            order_depths[product] = depth
            
            if not pd.isna(row.get("mid_price")):
                mid = row["mid_price"]
            else:
                mid = (int(row["bid_price_1"]) + int(row["ask_price_1"])) / 2.0
            
            mid_prices[product] = mid
            last_known_prices[product] = mid

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
            # st.error(f"Trader failed at ts {ts}")
            continue

        for product, order_list in orders.items():
            if product not in order_depths:
                continue
            depth = order_depths[product]
            limit = getattr(trader, "LIMIT", 80) # Use trader's limit if defined, else 80

            for order in order_list:
                qty = order.quantity
                price = order.price

                if qty > 0: # BUY
                    for ask in sorted(depth.sell_orders.keys()):
                        if price >= ask and qty > 0:
                            avail = -depth.sell_orders[ask]
                            fill = min(qty, avail, limit - positions[product])
                            if fill > 0:
                                positions[product] += fill
                                cash_per_product[product] -= fill * ask
                                qty -= fill
                                trade_count += 1
                elif qty < 0: # SELL
                    for bid in sorted(depth.buy_orders.keys(), reverse=True):
                        if price <= bid and qty < 0:
                            avail = depth.buy_orders[bid]
                            fill = min(-qty, avail, limit + positions[product])
                            if fill > 0:
                                positions[product] -= fill
                                cash_per_product[product] += fill * bid
                                qty += fill
                                trade_count += 1

            max_pos[product] = max(max_pos[product], abs(positions[product]))

        mtm = sum(cash_per_product.values())
        for product, pos in positions.items():
            if product in last_known_prices:
                mtm += pos * last_known_prices[product]
        pnl_history.append(mtm)

    if not pnl_history:
        return None

    # Calculate PnL per product
    product_pnls = {}
    for product in unique_products:
        p_pnl = cash_per_product[product]
        if product in last_known_prices:
            p_pnl += positions[product] * last_known_prices[product]
        product_pnls[product] = p_pnl

    # Stats
    returns = np.diff(pnl_history)
    peak = 0.0
    max_dd = 0.0
    for pnl in pnl_history:
        peak = max(peak, pnl)
        max_dd = max(max_dd, peak - pnl)

    if len(returns) > 1:
        std = np.std(returns)
        sharpe = (np.mean(returns) / std * np.sqrt(len(returns))) if std > 0 else 0
        downside_returns = returns[returns < 0]
        downside_std = np.std(downside_returns) if len(downside_returns) > 1 else std
        sortino = (np.mean(returns) / downside_std * np.sqrt(len(returns))) if downside_std > 0 else 0
        calmar = (pnl_history[-1] / max_dd) if max_dd > 0 else 0
    else:
        sharpe = sortino = calmar = 0

    return BacktestResult(
        name=name,
        category=category,
        final_pnl=pnl_history[-1],
        product_pnls=product_pnls,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        max_position=max_pos,
        trade_count=trade_count,
        pnl_curve=pnl_history,
    )

def discover_datasets(rounds: List[int], quick: bool = False) -> List[Tuple[str, str, str]]:
    datasets = []
    
    # 1. IMC Historical Data
    for r in rounds:
        round_dir = REPO_ROOT / f"ROUND {r}"
        if not round_dir.exists():
            # Try ROUND%202 or similar if common
            round_dir = REPO_ROOT / f"ROUND%20{r}"
        
        data_dir = round_dir / "data_capsule"
        if data_dir.exists():
            price_files = sorted(data_dir.glob(f"prices_round_{r}_day_*.csv"))
            # Also check if they named it without the round in price_files (older convention)
            if not price_files:
                price_files = sorted(data_dir.glob("prices_day_*.csv"))
            
            for p in price_files:
                name = p.stem.replace("prices_", f"imc_r{r}_")
                datasets.append((name, str(p), f"round_{r}"))

    # 2. Real World and Scenarios
    processed_files = set()
    for r in rounds:
        round_dir = REPO_ROOT / f"ROUND {r}"
        if not round_dir.exists():
            round_dir = REPO_ROOT / f"ROUND%20{r}"
        
        round_capsule = round_dir / "data_capsule"
        if round_capsule.exists():
            # Real World
            real_dir = round_capsule / "real_world" / "normalized"
            if real_dir.exists():
                real_files = sorted(real_dir.glob("prices_*.csv"))
                if quick:
                    real_files = real_files[::5]
                for f in real_files:
                    path_str = str(f)
                    if path_str not in processed_files:
                        datasets.append((f.stem.replace("prices_", "real_"), path_str, "real_world"))
                        processed_files.add(path_str)
            
            # Scenarios
            scen_dir = round_capsule / "scenarios"
            if scen_dir.exists():
                scen_files = sorted(scen_dir.glob("prices_*.csv"))
                if quick:
                    # One per regime
                    seen_regimes = set()
                    filtered = []
                    for f in scen_files:
                        regime = "_".join(f.stem.replace("prices_", "").split("_")[:-1])
                        if regime not in seen_regimes:
                            seen_regimes.add(regime)
                            filtered.append(f)
                    scen_files = filtered
                for f in scen_files:
                    path_str = str(f)
                    if path_str not in processed_files:
                        datasets.append((f.stem.replace("prices_", "scen_"), path_str, "scenario"))
                        processed_files.add(path_str)

    return datasets

def run_unified_backtest(trader_file: str, datasets: List[Tuple[str, str, str]], tag: str = "robust") -> Dict:
    results: List[BacktestResult] = []

    print(f"\nUNIFIED ROBUST BACKTEST: {trader_file}")
    print(f"Testing across {len(datasets)} datasets")
    print("=" * 80)

    for i, (name, path, category) in enumerate(datasets):
        progress = f"[{i+1}/{len(datasets)}]"
        res = run_backtest_on_csv(trader_file, path, name, category)
        if res:
            marker = ""
            if res.final_pnl < -10000: marker = " !!! BLOW UP !!!"
            elif res.final_pnl < 0: marker = " (LOSS)"
            print(f"  {progress:9s} {name:40s} | PnL: ${res.final_pnl:>11,.1f} | DD: ${res.max_drawdown:>9.1f}{marker}")
            results.append(res)
        else:
            print(f"  {progress:9s} {name:40s} | SKIPPED")

    if not results:
        print("\nNo successful backtests run.")
        return {}

    # Aggregated Stats
    pnls = [r.final_pnl for r in results]
    dds = [r.max_drawdown for r in results]
    
    stats = {
        "trader": trader_file,
        "count": len(results),
        "mean_pnl": float(np.mean(pnls)),
        "median_pnl": float(np.median(pnls)),
        "min_pnl": float(np.min(pnls)),
        "max_pnl": float(np.max(pnls)),
        "p5_pnl": float(np.percentile(pnls, 5)),
        "p95_pnl": float(np.percentile(pnls, 95)),
        "mean_sharpe": float(np.mean([r.sharpe_ratio for r in results])),
        "mean_sortino": float(np.mean([r.sortino_ratio for r in results])),
        "worst_dd": float(np.max(dds)),
        "win_rate": sum(1 for p in pnls if p > 0) / len(pnls),
        "blow_up_rate": sum(1 for p in pnls if p < -10000) / len(pnls),
    }

    print("\n" + "=" * 80)
    print("UNIFIED ROBUSTNESS SUMMARY")
    print("=" * 80)
    print(f"Mean PnL:      ${stats['mean_pnl']:>12,.2f}")
    print(f"Median PnL:    ${stats['median_pnl']:>12,.2f}")
    print(f"Win Rate:       {stats['win_rate']*100:>11.1f}%")
    print(f"Worst Case:    ${stats['min_pnl']:>12,.2f}")
    print(f"Worst DD:      ${stats['worst_dd']:>12,.2f}")
    print(f"Mean Sharpe:    {stats['mean_sharpe']:>12.4f}")
    print("-" * 80)

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = RESULTS_DIR / f"{Path(trader_file).stem}_{tag}_results.csv"
    
    rows = []
    for r in results:
        d = {
            "name": r.name,
            "category": r.category,
            "final_pnl": r.final_pnl,
            "max_drawdown": r.max_drawdown,
            "sharpe": r.sharpe_ratio,
            "trade_count": r.trade_count
        }
        for p, p_pnl in r.product_pnls.items():
            d[f"pnl_{p}"] = p_pnl
        rows.append(d)
    
    pd.DataFrame(rows).to_csv(out_file, index=False)
    print(f"Detailed results saved to: {out_file}")

    return stats

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified Robust Backtester")
    parser.add_argument("trader", help="Path to trader .py file")
    parser.add_argument("extra_tag", nargs="?", help="Optional tag for results filename")
    parser.add_argument("--rounds", type=int, nargs="+", default=[1, 2], help="Rounds to include (default: 1 2)")
    parser.add_argument("--quick", action="store_true", help="Subset for speed")
    parser.add_argument("--tag", type=str, default=None, help="Tag for results file")
    parser.add_argument("--imc", action="store_true", help="Only run IMC historical days")
    parser.add_argument("--real", action="store_true", help="Only run real-world normalized data")
    parser.add_argument("--scen", action="store_true", help="Only run synthetic scenarios")
    args = parser.parse_args()

    datasets = discover_datasets(args.rounds, quick=args.quick)
    
    # Filter by category if requested
    if args.imc or args.real or args.scen:
        filtered = []
        if args.imc:
            filtered.extend([d for d in datasets if d[2].startswith("round_")])
        if args.real:
            filtered.extend([d for d in datasets if d[2] == "real_world"])
        if args.scen:
            filtered.extend([d for d in datasets if d[2] == "scenario"])
        datasets = filtered

    if args.tag:
        run_tag = args.tag
    elif args.extra_tag:
        run_tag = args.extra_tag
    elif args.imc and not args.real and not args.scen:
        run_tag = "imc"
    elif args.quick:
        run_tag = "quick"
    else:
        run_tag = "robust"

    run_unified_backtest(args.trader, datasets, tag=run_tag)
