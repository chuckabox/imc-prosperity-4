"""Sweep HYDROGEL knobs on trader2 (VEV/IV/hedge OFF). Days 0+1."""
from __future__ import annotations
import importlib.util, io, itertools, sys, time
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRADER_PATH = REPO_ROOT / "ROUND 3" / "traders" / "peter" / "trader2.py"
DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"
TRAIN_DAYS = [0, 1]


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
    if not r.activity_logs: return 0.0
    last = r.activity_logs[-1].timestamp
    out = 0.0
    for row in reversed(r.activity_logs):
        if row.timestamp != last: break
        out += float(row.columns[-1])
    return out


def load():
    sys.path.insert(0, str(TRADER_PATH.parent))
    spec = importlib.util.spec_from_file_location("sweep_hp", TRADER_PATH)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def main():
    setup()
    from prosperity4bt.runner import run_backtest
    from prosperity4bt.models import TradeMatchingMode
    mod = load()
    Tr = mod.Trader
    Tr.ENABLE_HYDROGEL = True
    Tr.ENABLE_VFE_REVERSION = False
    Tr.ENABLE_VEV_GAMMA = False
    Tr.ENABLE_IV_SCALP = False
    Tr.ENABLE_HEDGE = False
    reader = FR(DATASET); mode = TradeMatchingMode.all

    grid = {
        "HP_TAKE_EDGE": [1, 2, 3],
        "HP_QUOTE_FRONT": [15, 20, 25],
        "HP_EWMA_ALPHA": [0.10, 0.20, 0.35],
    }
    keys = list(grid.keys())
    combos = list(itertools.product(*grid.values()))
    print(f"{len(combos)} combos x {len(TRAIN_DAYS)} days = {len(combos)*len(TRAIN_DAYS)} runs")
    rows = []
    t0 = time.time()
    for i, vals in enumerate(combos):
        for k, v in zip(keys, vals): setattr(Tr, k, v)
        total = 0
        for d in TRAIN_DAYS:
            trader = Tr()
            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                r = run_backtest(trader=trader, file_reader=reader, round_num=3, day_num=d,
                                 print_output=False, trade_matching_mode=mode,
                                 no_names=False, show_progress_bar=False)
            total += per_pnl(r)
        rows.append((total, dict(zip(keys, vals))))
        if (i + 1) % 5 == 0:
            print(f"  {i+1}/{len(combos)}  {time.time()-t0:.0f}s  best={max(r[0] for r in rows):+,.0f}", flush=True)
    rows.sort(key=lambda x: -x[0])
    print("\nTop 10:")
    for r in rows[:10]:
        print(f"  {r[0]:>+10,.0f}  {r[1]}")


if __name__ == "__main__":
    main()
