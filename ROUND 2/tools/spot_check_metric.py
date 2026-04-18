"""Spot-check trade_win_rate metric on a bear/crash scenario."""
import sys
from pathlib import Path

R2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R2 / "tools"))
sys.path.insert(0, str(R2 / "config"))

from robust_backtester import run_backtest_on_csv

DATA = R2 / "data_capsule" / "scenarios"
for scen in ["prices_bear_normal_s0.csv", "prices_crash_normal_s0.csv"]:
    p = DATA / scen
    if not p.exists():
        continue
    print(f"\n=== {scen} ===")
    for tname, tpath in [
        ("ken_safe",     str(R2 / "traders" / "ken"   / "trader_ken_v2_safe.py")),
        ("ken_agg",      str(R2 / "traders" / "ken"   / "trader_ken_v2_agg.py")),
        ("suvin_stable", str(R2 / "traders" / "suvin" / "trader_stable_suvin_v1.py")),
    ]:
        r = run_backtest_on_csv(tpath, str(p), scen, "scenario")
        if not r:
            continue
        print(f"{tname:14s}  PnL=${r.final_pnl:>10,.0f}  RTs={r.rt_wins+r.rt_losses:>4d}"
              f"  W:{r.rt_wins:>4d} L:{r.rt_losses:>4d}"
              f"  WR={r.trade_win_rate*100:>5.1f}%"
              f"  avg_win=${r.avg_win:>7,.1f}  avg_loss=${r.avg_loss:>7,.1f}"
              f"  PF={r.profit_factor:>5.2f}")
