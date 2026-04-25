"""Sweep VEV aggression knobs: cap, take_size, edge_req, sigma. Days 0+1."""
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
    if not r.activity_logs: return {}
    last = r.activity_logs[-1].timestamp
    out = {}
    for row in reversed(r.activity_logs):
        if row.timestamp != last: break
        out[row.columns[2]] = float(row.columns[-1])
    return out


def load():
    sys.path.insert(0, str(TRADER_PATH.parent))
    spec = importlib.util.spec_from_file_location("sweep_vev", TRADER_PATH)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def run_day(Tr, d, reader, mode):
    from prosperity4bt.runner import run_backtest
    trader = Tr()
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        return run_backtest(trader=trader, file_reader=reader, round_num=3, day_num=d,
                            print_output=False, trade_matching_mode=mode,
                            no_names=False, show_progress_bar=False)


def main():
    setup()
    from prosperity4bt.models import TradeMatchingMode
    mod = load()
    Tr = mod.Trader
    Tr.ENABLE_HYDROGEL = True
    Tr.ENABLE_VFE_REVERSION = False
    Tr.ENABLE_IV_SCALP = False
    Tr.ENABLE_VEV_GAMMA = True
    Tr.VEV_PRIMARY_STRIKES = [5400, 5500]   # cheap-spread only
    Tr.VEV_SECONDARY_STRIKES = []
    reader = FR(DATASET); mode = TradeMatchingMode.all

    SIGMA = [0.014, 0.016, 0.018, 0.020]
    EDGE  = [0.3, 0.5, 1.0]
    CAP   = [40, 60]
    SIZE  = [20, 40, 60]
    HEDGE = [True, False]

    rows = []
    combos = list(itertools.product(SIGMA, EDGE, CAP, SIZE, HEDGE))
    print(f"runs: {len(combos) * 2}")
    t0 = time.time()
    for i, (sig, edg, cap, sz, hg) in enumerate(combos):
        Tr.VEV_SIGMA_MODEL = sig
        Tr.VEV_GAMMA_EDGE_REQ = edg
        Tr.VEV_GAMMA_SELL_EDGE = edg
        Tr.VEV_PER_STRIKE_CAP = cap
        Tr.VEV_TAKE_SIZE = sz
        Tr.ENABLE_HEDGE = hg
        total = 0
        for d in TRAIN_DAYS:
            r = run_day(Tr, d, reader, mode)
            total += sum(per_pnl(r).values())
        rows.append((total, sig, edg, cap, sz, hg))
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(combos)}  elapsed {time.time()-t0:.0f}s")
    rows.sort(key=lambda x: -x[0])
    print("\nTop 15:")
    print(f"{'TOTAL':>10s}  {'sigma':>6s}  {'edge':>5s}  {'cap':>4s}  {'sz':>4s}  hedge")
    for r in rows[:15]:
        print(f"{r[0]:>+10,.0f}  {r[1]:>6.3f}  {r[2]:>5.2f}  {r[3]:>4d}  {r[4]:>4d}  {r[5]}")


if __name__ == "__main__":
    main()
