"""LOCKED Day 2 validation. Run ONCE with optimized params from optimize_trader2.json.

WARNING: this is the only place Day 2 should be touched. Do NOT loop / iterate.
"""
from __future__ import annotations
import importlib.util, io, json, sys
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRADER_PATH = REPO_ROOT / "ROUND 3" / "traders" / "peter" / "trader2.py"
DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"
PARAMS_FILE = REPO_ROOT / "ROUND 3" / "scratch" / "optimize_trader2.json"
HOLDOUT_DAY = 2  # NEVER train on this


def setup():
    from prosperity4bt import datamodel as p4dm
    sys.modules.setdefault("datamodel", p4dm)
    from prosperity4bt import data as p4d
    for k in ["HYDROGEL_PACK","VELVETFRUIT_EXTRACT"]: p4d.LIMITS.setdefault(k, 80)
    for K in [4000,4500,5000,5100,5200,5300,5400,5500,6000,6500]: p4d.LIMITS.setdefault(f"VEV_{K}", 60)


class FR:
    def __init__(self, root): self.r = root
    def file(self, parts):
        t = self.r
        for p in parts[1:]: t = t / p
        @contextmanager
        def c(): yield t if t.is_file() else None
        return c()


def per_pnl(r):
    if not r.activity_logs: return {}
    last = r.activity_logs[-1].timestamp
    out = {}
    for row in reversed(r.activity_logs):
        if row.timestamp != last: break
        out[row.columns[2]] = float(row.columns[-1])
    return out


def load():
    sys.path.insert(0, str(TRADER_PATH.parent))
    spec = importlib.util.spec_from_file_location("val_t2", TRADER_PATH)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def main():
    if not PARAMS_FILE.exists():
        print(f"No params file at {PARAMS_FILE}. Run optimize_trader2.py first.")
        return
    payload = json.loads(PARAMS_FILE.read_text())
    params = payload["best_params"]
    train_pnl = payload["best_pnl"]
    robustness = payload.get("robustness_score", 0)

    print("=" * 60)
    print(f"LOCKED VALIDATION ON DAY {HOLDOUT_DAY}")
    print("=" * 60)
    print(f"Train PnL (days 0+1): {train_pnl:+,.0f}")
    print(f"Robustness score: {robustness:,.0f}")
    print(f"Params: {json.dumps(params, indent=2)}")
    print()

    setup()
    from prosperity4bt.runner import run_backtest
    from prosperity4bt.models import TradeMatchingMode
    mod = load()
    Tr = mod.Trader
    for k, v in params.items():
        setattr(Tr, k, v)

    reader = FR(DATASET)
    trader = Tr()
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        r = run_backtest(trader=trader, file_reader=reader, round_num=3, day_num=HOLDOUT_DAY,
                         print_output=False, trade_matching_mode=TradeMatchingMode.all,
                         no_names=False, show_progress_bar=False)
    per = per_pnl(r)
    total = sum(per.values())
    print(f"VALIDATION DAY {HOLDOUT_DAY} PnL: {total:+,.0f}")
    for p in sorted(per):
        print(f"  {p:25s}  {per[p]:>+12,.0f}")
    train_avg = train_pnl / 2
    print(f"\nTrain avg/day: {train_avg:+,.0f}")
    print(f"Holdout day:   {total:+,.0f}")
    drift = (total - train_avg) / max(abs(train_avg), 1) * 100
    print(f"Holdout vs train avg: {drift:+.1f}%")
    if abs(drift) > 50:
        print("WARNING: large train-vs-holdout gap. Possible overfit.")


if __name__ == "__main__":
    main()
