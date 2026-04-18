"""Ken v5 vs Holy_grail vs peter_v1000 vs ken_v3 vs suvin_stable — IMC R2 + stress scenarios."""
import sys
from pathlib import Path

R2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R2 / "tools"))
sys.path.insert(0, str(R2 / "config"))

from robust_backtester import run_backtest_on_csv

TRADERS = [
    ("ken_v5", str(R2 / "traders" / "ken" / "trader_ken_v5.py")),
    ("Holy_grail", str(R2 / "traders" / "Holy_grail.py")),
    ("peter_v1000", str(R2 / "traders" / "peter" / "trader_peter_v1000.py")),
    ("ken_v3", str(R2 / "traders" / "ken" / "trader_ken_v3.py")),
    ("suvin_stable", str(R2 / "traders" / "suvin" / "trader_stable_suvin_v1.py")),
]

IMC_R2 = sorted((R2 / "data_capsule").glob("prices_round_2_day_*.csv"))
SCEN_DIR = R2 / "data_capsule" / "scenarios"
SCENARIOS = sorted(
    [
        SCEN_DIR / "prices_bear_normal_s0.csv",
        SCEN_DIR / "prices_bear_volatile_s0.csv",
        SCEN_DIR / "prices_crash_normal_s0.csv",
        SCEN_DIR / "prices_crash_volatile_s0.csv",
        SCEN_DIR / "prices_v_recovery_drift_s0.csv",
        SCEN_DIR / "prices_v_recovery_normal_s0.csv",
    ]
)


def run_group(title, files, category):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")
    print(f"{'scenario':<32s}" + "".join(f"{t[0]:>14s}" for t in TRADERS))
    totals = {t[0]: 0.0 for t in TRADERS}
    worsts = {t[0]: 1e18 for t in TRADERS}
    n = 0
    for f in files:
        if not f.exists():
            continue
        n += 1
        row = f"{f.stem.replace('prices_', ''):<32s}"
        for tname, tpath in TRADERS:
            r = run_backtest_on_csv(tpath, str(f), f.stem, category)
            v = r.final_pnl if r else float("nan")
            totals[tname] += v
            worsts[tname] = min(worsts[tname], v)
            row += f"{v:>14,.0f}"
        print(row)
    print("-" * 90)
    for tname, _ in TRADERS:
        avg = totals[tname] / n if n else 0
        print(
            f"  {tname:<14s}  total=${totals[tname]:>12,.0f}  mean=${avg:>11,.0f}  "
            f"worst_single=${worsts[tname]:>11,.0f}"
        )


run_group("IMC ROUND 2 HISTORICAL", IMC_R2, "imc")
run_group("STRESS (bear / crash / v-recovery)", SCENARIOS, "scenario")
