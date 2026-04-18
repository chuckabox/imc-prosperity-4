"""Ken v3 vs Suvin test_v1 vs Ken v2 variants — IMC + bear/crash head-to-head."""
import sys
from pathlib import Path

R2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R2 / "tools"))
sys.path.insert(0, str(R2 / "config"))

from robust_backtester import run_backtest_on_csv

TRADERS = [
    ("ken_v2_safe",  str(R2 / "traders" / "ken"   / "trader_ken_v2_safe.py")),
    ("ken_v2_agg",   str(R2 / "traders" / "ken"   / "trader_ken_v2_agg.py")),
    ("ken_v3",       str(R2 / "traders" / "ken"   / "trader_ken_v3.py")),
    ("suvin_test",   str(R2 / "traders" / "suvin" / "trader_test_suvin_v1.py")),
    ("suvin_stable", str(R2 / "traders" / "suvin" / "trader_stable_suvin_v1.py")),
]

IMC = sorted((R2 / "data_capsule").glob("prices_round_*_day_*.csv"))
SCEN_DIR = R2 / "data_capsule" / "scenarios"
SCENARIOS = [
    SCEN_DIR / "prices_bear_normal_s0.csv",
    SCEN_DIR / "prices_bear_volatile_s0.csv",
    SCEN_DIR / "prices_crash_normal_s0.csv",
    SCEN_DIR / "prices_crash_volatile_s0.csv",
    SCEN_DIR / "prices_v_recovery_normal_s0.csv",
]

def run_group(title, files, category):
    print(f"\n{'='*90}\n{title}\n{'='*90}")
    print(f"{'scenario':<28s}" + "".join(f"{t[0]:>14s}" for t in TRADERS))
    totals = {t[0]: 0.0 for t in TRADERS}
    worsts = {t[0]:  1e18 for t in TRADERS}
    blows  = {t[0]: 0 for t in TRADERS}
    rt_w   = {t[0]: 0 for t in TRADERS}
    rt_l   = {t[0]: 0 for t in TRADERS}
    n = 0
    for f in files:
        if not f.exists():
            continue
        n += 1
        row = f"{f.stem.replace('prices_',''):<28s}"
        for tname, tpath in TRADERS:
            r = run_backtest_on_csv(tpath, str(f), f.stem, category)
            v = r.final_pnl if r else float("nan")
            totals[tname] += v
            worsts[tname] = min(worsts[tname], v)
            if v < -10000: blows[tname] += 1
            if r:
                rt_w[tname] += r.rt_wins
                rt_l[tname] += r.rt_losses
            row += f"{v:>14,.0f}"
        print(row)
    print("-"*90)
    for tname, _ in TRADERS:
        avg = totals[tname]/n if n else 0
        wr  = rt_w[tname]/max(1, rt_w[tname]+rt_l[tname])
        print(f"  {tname:<14s}  mean=${avg:>11,.0f}  worst=${worsts[tname]:>11,.0f}  "
              f"blowups={blows[tname]}/{n}  trade_wr={wr*100:>5.1f}%  (W:{rt_w[tname]:,}/L:{rt_l[tname]:,})")

run_group("IMC HISTORICAL DAYS", IMC, "imc")
run_group("STRESS SCENARIOS (bear / crash / v-recovery)", SCENARIOS, "scenario")
