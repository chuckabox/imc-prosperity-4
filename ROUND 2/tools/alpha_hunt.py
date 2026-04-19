"""Alpha hunt: (1) verify Osmium AR(3), (2) test peter_v2d champion on R2 data."""
import sys
import pandas as pd
import numpy as np
from pathlib import Path

R2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R2 / "tools"))
sys.path.insert(0, str(R2 / "config"))

# ============================================================
# 1. Verify Osmium AR(3) on actual price data
# ============================================================
print("=" * 70)
print("PART 1: OSMIUM AR(3) MODEL VERIFICATION")
print("=" * 70)
print("Claimed: Fair(t) = 309.9 + 0.3616*Mid_{t-1} + 0.3148*Mid_{t-2} + 0.2925*Mid_{t-3}")
print()

for day_file in sorted((R2 / "data_capsule").glob("prices_round_*_day_*.csv")):
    df = pd.read_csv(day_file, sep=";")
    osm = df[df["product"] == "ASH_COATED_OSMIUM"].copy()
    osm["mid"] = (osm["bid_price_1"] + osm["ask_price_1"]) / 2.0
    osm = osm.dropna(subset=["mid"]).sort_values("timestamp").reset_index(drop=True)
    if len(osm) < 100:
        continue
    mids = osm["mid"].values

    # Fit OLS AR(3) ourselves
    y = mids[3:]
    X = np.column_stack([np.ones(len(y)), mids[2:-1], mids[1:-2], mids[0:-3]])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    intercept, w1, w2, w3 = beta

    # Claimed predictor
    pred_claim = 309.9 + 0.3616 * mids[2:-1] + 0.3148 * mids[1:-2] + 0.2925 * mids[0:-3]
    # Fitted predictor
    pred_fit = intercept + w1 * mids[2:-1] + w2 * mids[1:-2] + w3 * mids[0:-3]
    # Baseline: just use last mid
    pred_naive = mids[2:-1]
    # Baseline: 10000 anchor
    pred_anchor = 10000.0

    rmse_claim  = float(np.sqrt(np.mean((y - pred_claim)**2)))
    rmse_fit    = float(np.sqrt(np.mean((y - pred_fit)**2)))
    rmse_naive  = float(np.sqrt(np.mean((y - pred_naive)**2)))
    rmse_anchor = float(np.sqrt(np.mean((y - pred_anchor)**2)))

    hit_claim  = float(np.mean(np.sign(pred_claim  - pred_naive) == np.sign(y - pred_naive)))
    hit_fit    = float(np.mean(np.sign(pred_fit    - pred_naive) == np.sign(y - pred_naive)))

    name = day_file.stem.replace("prices_", "")
    print(f"\n  {name}  (n={len(mids)})")
    print(f"    fitted AR(3):  intercept={intercept:>8.2f}  w=[{w1:.4f}, {w2:.4f}, {w3:.4f}]  sum={w1+w2+w3:.4f}")
    print(f"    RMSE  anchor(10k)={rmse_anchor:.3f}   naive(last)={rmse_naive:.3f}   "
          f"claim={rmse_claim:.3f}   fitted_AR(3)={rmse_fit:.3f}")
    print(f"    direction hit-rate (vs naive): claim={hit_claim*100:.1f}%  fitted={hit_fit*100:.1f}%")

# ============================================================
# 2. Test peter_v2d champion on R2 data (new metrics)
# ============================================================
print("\n" + "=" * 70)
print("PART 2: PETER_V2D CHAMPION ON R2 DATA")
print("=" * 70)

from robust_backtester import run_backtest_on_csv

TRADERS = [
    ("peter_v2d",      str(R2.parent / "ROUND 1" / "traders" / "peter" / "archive" / "trader_peter_v2d.py")),
    ("ken_v3",         str(R2 / "traders" / "ken"   / "trader_ken_v3.py")),
    ("ken_v2_agg",     str(R2 / "traders" / "ken"   / "trader_ken_v2_agg.py")),
    ("suvin_test_v1",  str(R2 / "traders" / "suvin" / "trader_test_suvin_v1.py")),
]

imc_files = sorted((R2 / "data_capsule").glob("prices_round_*_day_*.csv"))
print(f"\n{'scenario':<28s}" + "".join(f"{t[0]:>16s}" for t in TRADERS))
totals = {t[0]: 0.0 for t in TRADERS}
for f in imc_files:
    if not f.exists(): continue
    row = f"{f.stem.replace('prices_',''):<28s}"
    for tname, tpath in TRADERS:
        if not Path(tpath).exists():
            row += f"{'MISSING':>16s}"
            continue
        r = run_backtest_on_csv(tpath, str(f), f.stem, "imc")
        v = r.final_pnl if r else float("nan")
        totals[tname] += v
        row += f"{v:>16,.0f}"
    print(row)
print("-" * 100)
n = len(imc_files)
for tname, _ in TRADERS:
    print(f"  {tname:<14s}  total=${totals[tname]:>11,.0f}  mean=${totals[tname]/max(1,n):>11,.0f}")
