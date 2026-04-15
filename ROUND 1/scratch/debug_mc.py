import json
import os
import sys

# Add tools and traders to path
sys.path.append(os.path.abspath("ROUND 1/tools"))
sys.path.append(os.path.abspath("ROUND 1/traders/peter"))

from monte_carlo_backtester import MonteCarloBacktester

def debug_mc():
    trader_file = "ROUND 1/traders/peter/trader_10k.py"
    backtester = MonteCarloBacktester(trader_file, num_sessions=1, steps_per_session=10)
    
    # Patch run_session to print fills
    original_run_session = backtester.run_session
    def run_session_with_print(*args, **kwargs):
        res = original_run_session(*args, **kwargs)
        print(f"Final PnL for session: {res['final_pnl']}")
        return res
    
    backtester.run_session = run_session_with_print
    backtester.run()

if __name__ == "__main__":
    debug_mc()
