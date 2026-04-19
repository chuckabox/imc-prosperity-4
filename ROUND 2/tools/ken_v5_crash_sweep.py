"""
Grid sweep for trader_ken_v5 Pepper crash-gate knobs only.
Writes CSV to ROUND 2/tools/sweep_results/ken_v5_crash_sweep.csv

IMC: round 2 days only. Scenarios: v_recovery_drift + bear_volatile + crash_normal (subset).
"""
import os
import re
import sys
import tempfile
from pathlib import Path

R2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R2 / "tools"))
sys.path.insert(0, str(R2 / "config"))

from robust_backtester import run_backtest_on_csv

TRADER_SRC = R2 / "traders" / "ken" / "trader_ken_v5.py"
IMC_R2 = sorted((R2 / "data_capsule").glob("prices_round_2_day_*.csv"))
SCEN_DIR = R2 / "data_capsule" / "scenarios"
SCEN_SUBSET = [
    SCEN_DIR / "prices_v_recovery_drift_s0.csv",
    SCEN_DIR / "prices_v_recovery_drift_s1.csv",
    SCEN_DIR / "prices_v_recovery_drift_s2.csv",
    SCEN_DIR / "prices_bear_volatile_s0.csv",
    SCEN_DIR / "prices_crash_normal_s0.csv",
]
OUT = R2 / "tools" / "sweep_results"
OUT.mkdir(parents=True, exist_ok=True)


def patch_src(src: str, drop: int, breach: int, lockout: int) -> str:
    src = re.sub(
        r"PEPPER_CRASH_BASE_DROP = \d+",
        f"PEPPER_CRASH_BASE_DROP = {drop}",
        src,
        count=1,
    )
    src = re.sub(
        r"PEPPER_CRASH_BREACH = \d+",
        f"PEPPER_CRASH_BREACH = {breach}",
        src,
        count=1,
    )
    src = re.sub(
        r"PEPPER_CRASH_LOCKOUT = \d+",
        f"PEPPER_CRASH_LOCKOUT = {lockout}",
        src,
        count=1,
    )
    return src


def eval_combo(drop: int, breach: int, lockout: int) -> dict:
    base = TRADER_SRC.read_text(encoding="utf-8")
    patched = patch_src(base, drop, breach, lockout)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(patched)
        tmp = f.name
    try:
        imc_pnls = []
        for f in IMC_R2:
            if f.exists():
                r = run_backtest_on_csv(tmp, str(f), f.stem, "imc")
                imc_pnls.append(r.final_pnl if r else float("nan"))
        scen_pnls = []
        for f in SCEN_SUBSET:
            if f.exists():
                r = run_backtest_on_csv(tmp, str(f), f.stem, "scenario")
                scen_pnls.append(r.final_pnl if r else float("nan"))
        imc_sum = sum(imc_pnls)
        min_scen = min(scen_pnls) if scen_pnls else float("nan")
        return {
            "drop": drop,
            "breach": breach,
            "lockout": lockout,
            "imc_sum": imc_sum,
            "min_scenario": min_scen,
            "v_recovery_sum": sum(scen_pnls[:3]) if len(scen_pnls) >= 3 else float("nan"),
        }
    finally:
        os.unlink(tmp)


def main():
    drops = [6, 8, 10, 12]
    breaches = [3, 5, 7]
    lockouts = [250, 400, 600]
    rows = []
    baseline_imc = None
    for drop in drops:
        for breach in breaches:
            for lockout in lockouts:
                row = eval_combo(drop, breach, lockout)
                rows.append(row)
                print(row)
                if drop == 8 and breach == 5 and lockout == 400:
                    baseline_imc = row["imc_sum"]

    # Pick: max min_scenario subject to imc_sum >= baseline - 2000 (default knobs)
    baseline_imc = baseline_imc or next(
        (r["imc_sum"] for r in rows if r["drop"] == 8 and r["breach"] == 5 and r["lockout"] == 400),
        rows[0]["imc_sum"],
    )
    feasible = [r for r in rows if r["imc_sum"] >= baseline_imc - 2000]
    if not feasible:
        feasible = rows
    best = max(feasible, key=lambda r: (r["min_scenario"], r["imc_sum"]))
    print("\n=== BEST (max min_scenario, imc_sum within -2k of default 8/5/400) ===")
    print(best)

    import csv

    out_path = OUT / "ken_v5_crash_sweep.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
