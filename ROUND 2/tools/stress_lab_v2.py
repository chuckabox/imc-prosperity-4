import sys
import os
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from advanced_backtest_engine import AdvancedMatchingEngine

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data_capsule"

def run_stress_test(trader_file: str, data_file: str):
    print(f"\nSTRESS LAB V2: {trader_file}")
    print("=" * 60)
    print(f"Base Dataset: {data_file}")
    
    results = []
    
    # 1. Latency Stress
    print("\n[Phase 1] Latency Sensitivity")
    for lat in [0, 1, 2]:
        engine = AdvancedMatchingEngine(latency_ticks=lat)
        res = engine.run_backtest(trader_file, data_file)
        results.append({
            "test": "Latency",
            "value": lat,
            "pnl": res.final_pnl,
            "sharpe": res.sharpe,
            "drawdown": res.max_drawdown
        })
        print(f"  Latency {lat} ticks: PnL=${res.final_pnl:,.2f}, Sharpe={res.sharpe:.3f}")

    # 2. Slippage Stress
    print("\n[Phase 2] Execution Slip (Slippage)")
    for slip in [0.0, 0.05, 0.1]:
        engine = AdvancedMatchingEngine(slippage_prob=slip)
        res = engine.run_backtest(trader_file, data_file)
        results.append({
            "test": "Slippage",
            "value": slip,
            "pnl": res.final_pnl,
            "sharpe": res.sharpe,
            "drawdown": res.max_drawdown
        })
        print(f"  Slippage {slip*100}%: PnL=${res.final_pnl:,.2f}, Sharpe={res.sharpe:.3f}")

    # 3. Combined Worst Case
    print("\n[Phase 3] Nightmare Scenario (Latency 1 + Slippage 5%)")
    engine = AdvancedMatchingEngine(latency_ticks=1, slippage_prob=0.05)
    res = engine.run_backtest(trader_file, data_file)
    results.append({
        "test": "Nightmare",
        "value": "L1+S5",
        "pnl": res.final_pnl,
        "sharpe": res.sharpe,
        "drawdown": res.max_drawdown
    })
    print(f"  Nightmare: PnL=${res.final_pnl:,.2f}, Sharpe={res.sharpe:.3f}")

    # Save results
    df = pd.DataFrame(results)
    out_file = Path(trader_file).stem + "_stress_results.csv"
    df.to_csv(SCRIPT_DIR / out_file, index=False)
    print(f"\nStress lab results saved to: {out_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("trader", help="Trader file")
    parser.add_argument("--data", default=None, help="Base data file for stress testing")
    args = parser.parse_args()
    
    data_file = args.data
    if not data_file:
        # Default to Round 1 Day 0
        data_file = str(DATA_DIR / "prices_round_1_day_0.csv")
        
    run_stress_test(args.trader, data_file)
