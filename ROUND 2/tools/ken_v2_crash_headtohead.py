"""Quick head-to-head on pepper-crash scenarios. Compares ken_v2 vs suvin_stable."""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
R2 = SCRIPT_DIR.parent
sys.path.insert(0, str(R2 / "tools"))
sys.path.insert(0, str(R2 / "config"))

from robust_backtester import run_backtest_on_csv

DATA = R2 / "data_capsule" / "scenarios"
# Pick 2 seeds from each bear/crash regime
TARGETS = [
    ("bear_normal_s0",     DATA / "prices_bear_normal_s0.csv"),
    ("bear_normal_s1",     DATA / "prices_bear_normal_s1.csv"),
    ("bear_volatile_s0",   DATA / "prices_bear_volatile_s0.csv"),
    ("crash_normal_s0",    DATA / "prices_crash_normal_s0.csv"),
    ("crash_normal_s1",    DATA / "prices_crash_normal_s1.csv"),
    ("crash_volatile_s0",  DATA / "prices_crash_volatile_s0.csv"),
    ("v_recovery_s0",      DATA / "prices_v_recovery_normal_s0.csv"),
]

TRADERS = {
    "ken_safe":    str(R2 / "traders" / "ken"   / "trader_ken_v2_safe.py"),
    "ken_agg":     str(R2 / "traders" / "ken"   / "trader_ken_v2_agg.py"),
    "suvin_stable":str(R2 / "traders" / "suvin" / "trader_stable_suvin_v1.py"),
}

print(f"{'scenario':<22s} | {'ken_safe':>12s} | {'ken_agg':>12s} | {'suvin_stab':>12s}")
print("-" * 70)
blowups = {k: 0 for k in TRADERS}
totals  = {k: 0.0 for k in TRADERS}
worsts  = {k:  1e18 for k in TRADERS}
for name, path in TARGETS:
    if not path.exists():
        print(f"{name} missing")
        continue
    row = [name]
    for tname, tpath in TRADERS.items():
        r = run_backtest_on_csv(tpath, str(path), name, "scenario")
        v = r.final_pnl if r else float("nan")
        totals[tname] += v
        worsts[tname] = min(worsts[tname], v)
        if v < -10000:
            blowups[tname] += 1
        row.append(f"${v:>10,.0f}")
    print(f"{row[0]:<22s} | {row[1]:>12s} | {row[2]:>12s} | {row[3]:>12s}")

print("-" * 70)
n = len([p for _, p in TARGETS if p.exists()])
for k in TRADERS:
    avg = totals[k]/n if n else 0
    print(f"  {k:<14s} mean=${avg:>10,.0f}  worst=${worsts[k]:>10,.0f}  blowups={blowups[k]}/{n}")
