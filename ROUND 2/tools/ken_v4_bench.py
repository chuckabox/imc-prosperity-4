"""Benchmark ken_v4 (with AR(3) osmium alpha) vs v3 / suvin_test across all IMC days."""
import sys
from pathlib import Path
R2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R2 / "tools"))
sys.path.insert(0, str(R2 / "config"))
from robust_backtester import run_backtest_on_csv

TRADERS = [
    ("ken_v4",        str(R2 / "traders" / "ken"   / "trader_ken_v4.py")),
    ("ken_v3",        str(R2 / "traders" / "ken"   / "trader_ken_v3.py")),
    ("suvin_test_v1", str(R2 / "traders" / "suvin" / "trader_test_suvin_v1.py")),
]
days = sorted((R2 / "data_capsule").glob("prices_round_*_day_*.csv"))

print(f"\n{'day':<26s} {'trader':<16s} {'total':>10s}  {'osmium':>9s}  {'pepper':>9s}  "
      f"{'trades':>6s}  {'RT':>4s}")
totals = {t[0]: [0.0, 0.0, 0.0] for t in TRADERS}  # total, osmium, pepper
for f in days:
    for tname, tpath in TRADERS:
        r = run_backtest_on_csv(tpath, str(f), f.stem, "imc")
        if not r: continue
        totals[tname][0] += r.final_pnl
        totals[tname][1] += r.pnl_osmium
        totals[tname][2] += r.pnl_pepper
        tag = f.stem.replace("prices_", "")
        print(f"{tag:<26s} {tname:<16s} ${r.final_pnl:>9,.0f}  ${r.pnl_osmium:>8,.0f}  "
              f"${r.pnl_pepper:>8,.0f}  {r.trade_count:>6d}  {r.rt_wins+r.rt_losses:>4d}")
    print("-" * 90)

print(f"\n{'TOTALS':<42s} {'total':>10s}  {'osmium':>9s}  {'pepper':>9s}  {'mean':>9s}")
n = len(days)
for tname, _ in TRADERS:
    t, o, p = totals[tname]
    print(f"{tname:<42s} ${t:>9,.0f}  ${o:>8,.0f}  ${p:>8,.0f}  ${t/max(1,n):>8,.0f}")
