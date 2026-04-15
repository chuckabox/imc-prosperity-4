import json
import math
import random
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Any
from datamodel import Order, OrderDepth, TradingState, Symbol, Trade, Listing, Observation
import importlib.util

from monte_carlo_backtester import MarketSimulator, MonteCarloBacktester

class SlowCrashSimulator(MarketSimulator):
    """Simulates a sustained downward trend (reversal) for Pepper Root."""
    def __init__(self, reversal_step: int = 300, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reversal_step = reversal_step

    def generate_fair_price(self, product: str, step: int, history: Dict) -> float:
        if product == 'INTARIAN_PEPPER_ROOT':
            if 'pepper_fair' not in history:
                history['pepper_fair'] = 12500.0
            
            # Normal drift (Before 300)
            drift = 0.5 if step < self.reversal_step else -1.5 # SUSTAINED CRASH
            
            shock = np.random.normal(drift, self.pepper_volatility)
            history['pepper_fair'] = max(100, history['pepper_fair'] + shock)
            return history['pepper_fair']
            
        return super().generate_fair_price(product, step, history)

def run_reversal_test(trader_file: str, name: str):
    print(f"\n[RUNNING] Running Reversal Test for {name}")
    
    backtester = MonteCarloBacktester(trader_file, num_sessions=50, steps_per_session=1000)
    backtester.simulator = SlowCrashSimulator(reversal_step=300)
    
    stats = backtester.run()
    
    # Calculate Avg Final Position for Pepper to see if they unwound
    avg_pos = np.mean([r['max_position_pepper'] for r in backtester.results])
    
    print(f"\n--- Results for {name} ---")
    print(f"Mean PnL: ${stats['mean_pnl']:,.2f}")
    print(f"Worst DD: ${stats['worst_drawdown']:,.2f}")
    print(f"Avg Max Pos: {avg_pos:.1f}")
    
    return stats

if __name__ == "__main__":
    traders = {
        "v3 (Champion)": "ROUND 1/traders/peter/trader_peter_v3.py",
        "v4 (Institutional)": "ROUND 1/traders/peter/trader_peter_v4.py"
    }
    
    results = {}
    for name, path in traders.items():
        results[name] = run_reversal_test(path, name)
    
    print("\n" + "="*40)
    print("REVERSAL SURVIVAL RANKING")
    print("="*40)
    for name, stats in results.items():
        score = stats['mean_pnl']
        status = "!!! WIPED OUT" if score < -20000 else "### SURVIVED"
        print(f"{name}: Mean PnL ${score:,.2f} | {status}")
    print("="*40)
