import sys
from pathlib import Path

R2 = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(R2 / "tools"), str(R2 / "config")]
from robust_backtester import run_backtest_on_csv

imc = sorted((R2 / "data_capsule").glob("prices_round_2_day_*.csv"))
traders = [
    ("Holy_graill", str(R2 / "traders" / "Holy_graill.py")),
    ("ken_v5", str(R2 / "traders" / "ken" / "trader_ken_v5.py")),
    ("chimera_safe", str(R2 / "traders" / "chimera_safe.py")),
]
out = []
for name, path in traders:
    tot = 0.0
    rows = []
    for f in imc:
        r = run_backtest_on_csv(path, str(f), f.stem, "imc")
        v = r.final_pnl if r else 0.0
        tot += v
        rows.append((f.stem, v, r.pnl_pepper if r else 0, r.pnl_osmium if r else 0))
    out.append((name, tot, rows))
    print(f"{name} IMC_R2_sum={tot:,.0f}")
    for row in rows:
        print(f"  {row}")

Path(R2 / "scratch" / "compare_three_out.txt").write_text(
    "\n".join(f"{n}\t{t}" for n, t, _ in out), encoding="utf-8"
)
