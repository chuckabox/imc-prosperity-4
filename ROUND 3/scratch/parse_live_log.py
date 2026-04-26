"""Parse epsilon live log to extract final PnL by product."""
import json
from pathlib import Path

log_path = Path(r"ROUND 3/live_logs/we found epsilon/we found epsilon.log")
with open(log_path, "r") as f:
    data = json.load(f)

# Parse the activities log
log = data["activitiesLog"]
lines = log.strip().split("\n")
header = lines[0].split(";")

# Get last PnL per product
last_pnl = {}
last_ts = 0
for line in lines[1:]:
    parts = line.split(";")
    day = int(parts[0])
    ts = int(parts[1])
    product = parts[2]
    pnl_str = parts[-1].strip()
    pnl = float(pnl_str) if pnl_str else 0.0
    last_pnl[product] = pnl
    last_ts = max(last_ts, ts)

# Also print header to verify columns
print(f"Header: {header}")
print(f"PnL column index: {len(header)-1} ('{header[-1].strip()}')")

print(f"\nFinal timestamp: {last_ts}")
print(f"\nFinal PnL by product:")
print(f"{'Product':<25} {'PnL':>12}")
print("-" * 40)
total = 0
for prod in sorted(last_pnl.keys()):
    pnl = last_pnl[prod]
    total += pnl
    if abs(pnl) > 0.01:
        print(f"{prod:<25} {pnl:>12.2f}")
print("-" * 40)
print(f"{'TOTAL':<25} {total:>12.2f}")

# Also look at PnL at ts=100000 (upload slice)
upload_pnl = {}
for line in lines[1:]:
    parts = line.split(";")
    ts = int(parts[1])
    if ts <= 100000:
        product = parts[2]
        pnl_str = parts[-1].strip()
        pnl = float(pnl_str) if pnl_str else 0.0
        upload_pnl[product] = pnl

print(f"\n\nUpload Slice PnL (ts<=100000):")
print(f"{'Product':<25} {'PnL':>12}")
print("-" * 40)
utotal = 0
for prod in sorted(upload_pnl.keys()):
    pnl = upload_pnl[prod]
    utotal += pnl
    if abs(pnl) > 0.01:
        print(f"{prod:<25} {pnl:>12.2f}")
print("-" * 40)
print(f"{'TOTAL':<25} {utotal:>12.2f}")
