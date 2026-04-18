"""Diagnose Osmium vs Pepper split for each trader on one IMC day."""
import sys
from pathlib import Path
R2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R2 / "tools"))
sys.path.insert(0, str(R2 / "config"))
from robust_backtester import run_backtest_on_csv

DAY = R2 / "data_capsule" / "prices_round_2_day_0.csv"
TRADERS = [
    ("ken_v3",         str(R2 / "traders" / "ken"   / "trader_ken_v3.py")),
    ("ken_v2_agg",     str(R2 / "traders" / "ken"   / "trader_ken_v2_agg.py")),
    ("suvin_test_v1",  str(R2 / "traders" / "suvin" / "trader_test_suvin_v1.py")),
    ("suvin_stable",   str(R2 / "traders" / "suvin" / "trader_stable_suvin_v1.py")),
    ("ken_v6_1",       str(R2.parent / "ROUND 1" / "archive" / "old_10k_traders" / "ken" / "trader_ken_v6_1.py")),
    ("peter_v2d",      str(R2.parent / "ROUND 1" / "traders" / "peter" / "archive" / "trader_peter_v2d.py")),
]
print(f"\n{'trader':<16s} {'total':>10s}  {'osmium':>10s}  {'pepper':>10s}  {'trades':>7s}  "
      f"{'RT':>4s}  {'WR':>5s}  {'avg_w':>7s}  {'avg_l':>8s}  {'PF':>5s}")
for tname, tpath in TRADERS:
    if not Path(tpath).exists(): continue
    r = run_backtest_on_csv(tpath, str(DAY), DAY.stem, "imc")
    if not r: continue
    print(f"{tname:<16s} ${r.final_pnl:>9,.0f}  ${r.pnl_osmium:>9,.0f}  ${r.pnl_pepper:>9,.0f}  "
          f"{r.trade_count:>7d}  {r.rt_wins+r.rt_losses:>4d}  "
          f"{r.trade_win_rate*100:>4.1f}%  ${r.avg_win:>6,.1f}  ${r.avg_loss:>7,.1f}  {r.profit_factor:>5.2f}")
