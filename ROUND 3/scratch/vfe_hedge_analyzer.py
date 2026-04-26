"""Analyze VFE hedge costs vs VEV option PnL from backtester trade logs.

Goal: Understand where the -505 VFE bleed comes from and find ways to reduce it.
"""
import csv
import json
from pathlib import Path
from collections import defaultdict

# Load the latest backtester run to analyze trades
RUNS_DIR = Path(r"c:\Users\ductv\Desktop\Projects\imc prosperity\imc-prosperity-4\external\prosperity_rust_backtester\runs")

# Find latest run
runs = sorted(RUNS_DIR.iterdir(), key=lambda p: p.name, reverse=True)
full_day_runs = [r for r in runs if "data-capsule-day-2" in r.name and "first10pct" not in r.name]

if not full_day_runs:
    print("No full-day runs found. Using latest run.")
    run_dir = runs[0]
else:
    run_dir = full_day_runs[0]

print(f"Analyzing run: {run_dir.name}")

# Find trade log
trade_files = list(run_dir.glob("*trades*.csv"))
activity_files = list(run_dir.glob("*activities*.csv"))
log_files = list(run_dir.glob("*.log"))

print(f"Trade files: {[f.name for f in trade_files]}")
print(f"Activity files: {[f.name for f in activity_files]}")
print(f"Log files: {[f.name for f in log_files]}")

# List all files
print(f"\nAll files in run dir:")
for f in sorted(run_dir.iterdir()):
    print(f"  {f.name} ({f.stat().st_size:,} bytes)")
