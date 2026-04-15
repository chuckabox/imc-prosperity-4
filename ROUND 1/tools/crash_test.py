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

class CrashSimulator(MarketSimulator):
    """Simulates a market crash for Pepper Root."""
    def __init__(self, crash_step: int = 500, crash_magnitude: float = -500, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.crash_step = crash_step
        self.crash_magnitude = crash_magnitude

    def generate_fair_price(self, product: str, step: int, history: Dict) -> float:
        if product == 'INTARIAN_PEPPER_ROOT':
            if 'pepper_fair' not in history:
                history['pepper_fair'] = 12500.0 # Start at R1 peak
            
            # Normal walk
            drift = -0.05 # Natural downward drift
            
            # THE CRASH
            if step == self.crash_step:
                print(f"!!! CRASH EVENT AT STEP {step} !!!")
                history['pepper_fair'] += self.crash_magnitude
            
            # Post-crash panic drift
            if step > self.crash_step:
                drift = -0.5 
            
            shock = np.random.normal(drift, self.pepper_volatility)
            history['pepper_fair'] = max(100, history['pepper_fair'] + shock)
            return history['pepper_fair']
            
        return super().generate_fair_price(product, step, history)

def run_crash_test(trader_file: str, name: str):
    print(f"\n[RUNNING] Running Crash Test for {name} ({trader_file})")
    
    # Configure backtester
    backtester = MonteCarloBacktester(trader_file, num_sessions=50, steps_per_session=1000)
    # Inject our Crash Simulator
    backtester.simulator = CrashSimulator(crash_step=400, crash_magnitude=-800)
    
    stats = backtester.run()
    
    print(f"\n--- Results for {name} ---")
    print(f"Mean PnL: ${stats['mean_pnl']:,.2f}")
    print(f"Worst DD: ${stats['worst_drawdown']:,.2f}")
    print(f"Win Rate: {stats['win_rate']*100:.1f}%")
    
    return stats

if __name__ == "__main__":
    traders = {
        "v3 (Champion)": "ROUND 1/traders/peter/trader_peter_v3.py",
        "v4 (Institutional)": "ROUND 1/traders/peter/trader_peter_v4.py"
    }
    
    results = {}
    for name, path in traders.items():
        results[name] = run_crash_test(path, name)
    
    print("\n" + "="*40)
    print("FINAL CRASH SURVIVAL RANKING")
    print("="*40)
    for name, stats in results.items():
        status = "!!! WIPED OUT" if stats['mean_pnl'] < -1000 else "### SURVIVED"
        print(f"{name}: Mean PnL ${stats['mean_pnl']:,.2f} | {status}")
    print("="*40)
