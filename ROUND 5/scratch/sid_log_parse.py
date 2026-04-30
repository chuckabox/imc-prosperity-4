"""Parse sid v1 backtest log: extract per-product PnL + trade activity."""
import json
import os
from collections import defaultdict

LOG = "/Users/siddhant/Desktop/prosperity/imc-prosperity-4/ROUND 5/live_logs/sid/v1.json"

with open(LOG, "r", encoding="utf-8") as f:
    blob = json.load(f)

print("Top-level keys:", list(blob.keys()))
print(f"Reported total profit: {blob.get('profit')}")
print(f"Status: {blob.get('status')}")
print()

act = blob.get("activitiesLog", "")
print(f"activitiesLog length: {len(act)} chars")
print(f"Estimated rows: ~{act.count(chr(10))}")
print()

# Look at last few rows to get final PnL state
lines = act.split("\n")
print(f"Lines: {len(lines)}")
print(f"Header: {lines[0]}")
print(f"First data line: {lines[1] if len(lines) > 1 else ''}")
print()

# Parse: extract per-product PnL trajectory
header = lines[0].split(";")
ts_idx = header.index("timestamp")
prod_idx = header.index("product")
pnl_idx = header.index("profit_and_loss")
day_idx = header.index("day")
mid_idx = header.index("mid_price")

# Track final PnL per product per day
last_pnl = defaultdict(lambda: defaultdict(float))  # product -> day -> last pnl
first_nonzero = {}  # product -> (day, ts) of first nonzero pnl
trades_count = defaultdict(int)  # rough trade count via pnl change

# Track trade events: when pnl changes from previous tick same-product
prev_pnl = defaultdict(float)
pnl_change_events = defaultdict(list)  # product -> [(day, ts, delta_pnl)]

for ln in lines[1:]:
    if not ln:
        continue
    parts = ln.split(";")
    if len(parts) < len(header):
        continue
    try:
        d = int(parts[day_idx])
        ts = int(parts[ts_idx])
        prod = parts[prod_idx]
        pnl_str = parts[pnl_idx]
        if not pnl_str:
            continue
        pnl = float(pnl_str)
    except Exception:
        continue
    last_pnl[prod][d] = pnl
    if pnl != 0 and prod not in first_nonzero:
        first_nonzero[prod] = (d, ts, pnl)
    pp = prev_pnl[prod]
    if abs(pnl - pp) > 1e-9:
        pnl_change_events[prod].append((d, ts, pnl - pp))
        trades_count[prod] += 1
    prev_pnl[prod] = pnl

print("=" * 80)
print("Final PnL per product per day:")
print("=" * 80)
all_prods = sorted(last_pnl.keys())
all_days = set()
for p in all_prods:
    all_days.update(last_pnl[p].keys())
all_days = sorted(all_days)
print(f"Days seen: {all_days}")
print()

for p in all_prods:
    if any(last_pnl[p][d] != 0 for d in all_days):
        line = f"  {p:30s}"
        total = 0.0
        for d in all_days:
            v = last_pnl[p][d]
            line += f" day{d}={v:>12.2f}"
            total += v
        line += f"  total≈{total:>12.2f}"
        print(line)

print()
print("=" * 80)
print("Trade activity (PnL changed events ≈ trade ticks):")
print("=" * 80)
for p in all_prods:
    if trades_count[p] > 0:
        events = pnl_change_events[p]
        deltas = [e[2] for e in events]
        wins = sum(1 for d in deltas if d > 0)
        losses = sum(1 for d in deltas if d < 0)
        avg_delta = sum(deltas) / len(deltas) if deltas else 0
        print(f"  {p:30s}  events={len(events):4d}  wins={wins:3d}  losses={losses:3d}  avg_delta={avg_delta:+.3f}")

print()
print("=" * 80)
print("First nonzero PnL per product:")
print("=" * 80)
for p in sorted(first_nonzero.keys()):
    d, ts, pnl = first_nonzero[p]
    print(f"  {p:30s}  day={d}  ts={ts}  first_nonzero_pnl={pnl:+.2f}")

# Check sandboxLog if present
sb = blob.get("sandboxLog")
if sb:
    print()
    print("=" * 80)
    print(f"sandboxLog length: {len(sb)}")
    # show last 1000 chars to see if any error / final summary
    print("Last chunk:")
    print(sb[-1500:])
