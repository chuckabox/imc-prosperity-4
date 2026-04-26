"""Analyze VEV_5300 trades from the latest backtest run."""
import csv
import json
from pathlib import Path
from collections import defaultdict

# Find latest run for 'we found vfe gold.py'
RUNS_DIR = Path(r"c:\Users\ductv\Desktop\Projects\imc prosperity\imc-prosperity-4\external\prosperity_rust_backtester\runs")
runs = sorted(RUNS_DIR.iterdir(), key=lambda p: p.name, reverse=True)
gold_runs = []
for r in runs:
    m_path = r / "metrics.json"
    if m_path.exists():
        with open(m_path) as f:
            m = json.load(f)
            if "we found vfe gold.py" in m.get("trader_path", "") and "temp-slice" not in r.name:
                gold_runs.append(r)

if not gold_runs:
    print("No VFE Gold runs found.")
    exit()

run_dir = gold_runs[0]
print(f"Analyzing run: {run_dir.name}")

# In prosperity4bt runs, trades are usually in activitiesLog or a separate file if we use a specific wrapper.
# Since I used tools/run_prosperity4bt.py, it doesn't emit a separate CSV by default unless jmerle's engine does.
# Actually, the result object in run_backtest has own_trades.
# But I can't access it here.

# Let's look at the metrics again to see the breakdown.
with open(run_dir / "metrics.json") as f:
    m = json.load(f)
    print(f"PnL Breakdown: {m['final_pnl_by_product']}")

# I need to run a special trace script to see the trades.
