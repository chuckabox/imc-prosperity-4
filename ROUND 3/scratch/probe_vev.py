"""Inspect actual VEV positions/trades day 0+1 with current trader2 config."""
from __future__ import annotations
import importlib.util, io, sys
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRADER_PATH = REPO_ROOT / "ROUND 3" / "traders" / "peter" / "trader2.py"
DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"

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

def load():
    sys.path.insert(0, str(TRADER_PATH.parent))
    spec = importlib.util.spec_from_file_location("probe", TRADER_PATH)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def main():
    setup()
    from prosperity4bt.runner import run_backtest
    from prosperity4bt.models import TradeMatchingMode
    mod = load()
    Tr = mod.Trader
    Tr.ENABLE_VFE_REVERSION = False
    reader = FR(DATASET)
    for d in [0]:
        trader = Tr()
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            r = run_backtest(trader=trader, file_reader=reader, round_num=3, day_num=d,
                             print_output=False, trade_matching_mode=TradeMatchingMode.all,
                             no_names=False, show_progress_bar=False)
        # tally trade volume per product (TradeRow wraps a datamodel.Trade)
        vol = {}
        for tr in (r.trades if hasattr(r, 'trades') else []):
            sym = getattr(tr, 'symbol', None) or getattr(getattr(tr, 'trade', None), 'symbol', None)
            qty = getattr(tr, 'quantity', None) or getattr(getattr(tr, 'trade', None), 'quantity', 0)
            if sym is None: continue
            vol[sym] = vol.get(sym, 0) + abs(qty)
        # extract per-product PnL final
        last_ts = r.activity_logs[-1].timestamp
        ppnl = {}
        for row in reversed(r.activity_logs):
            if row.timestamp != last_ts: break
            ppnl[row.columns[2]] = float(row.columns[-1])
        # also extract final-pos by walking activity logs (mid_price col not pos, skip)
        print(f"Day {d}:")
        print(f"{'Product':25s}  {'PnL':>10s}  {'Vol':>8s}")
        for p in sorted(ppnl):
            print(f"  {p:25s}  {ppnl[p]:>+10,.0f}  {vol.get(p,0):>8d}")

if __name__ == "__main__":
    main()
