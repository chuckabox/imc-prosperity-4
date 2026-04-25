"""Two-stage optimizer for trader2 with finite-difference stability check.

Stage 1: coarse grid over key params (HP + VEV).
Stage 2: refine local neighborhood of top-3.
Stage 3: finite-difference sensitivity at best point — flat = robust, sharp = brittle.

Days 0+1 ONLY. Day 2 hidden.
"""
from __future__ import annotations
import importlib.util, io, itertools, json, sys, time
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRADER_PATH = REPO_ROOT / "ROUND 3" / "traders" / "peter" / "trader2.py"
DATASET = REPO_ROOT / "ROUND 3" / "data_capsule"
OUT = REPO_ROOT / "ROUND 3" / "scratch" / "optimize_trader2.json"
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
    spec = importlib.util.spec_from_file_location("opt_t2", TRADER_PATH)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def evaluate(Tr, params, reader, mode):
    from prosperity4bt.runner import run_backtest
    for k, v in params.items():
        setattr(Tr, k, v)
    total = 0.0
    for d in TRAIN_DAYS:
        trader = Tr()
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            r = run_backtest(trader=trader, file_reader=reader, round_num=3, day_num=d,
                             print_output=False, trade_matching_mode=mode,
                             no_names=False, show_progress_bar=False)
        total += per_pnl(r)
    return total


def coarse_grid(Tr, reader, mode):
    grid = {
        "HP_TAKE_EDGE": [1, 2],
        "HP_QUOTE_FRONT": [15, 20],
        "HP_EWMA_ALPHA": [0.20],
        "VEV_SIGMA_MODEL": [0.014, 0.018],
        "VEV_GAMMA_EDGE_REQ": [1.5],
        "VEV_TAKE_SIZE": [10, 30],
    }
    keys = list(grid.keys())
    combos = list(itertools.product(*grid.values()))
    print(f"Coarse: {len(combos)} combos x {len(TRAIN_DAYS)} days = {len(combos)*len(TRAIN_DAYS)} runs")
    rows = []
    t0 = time.time()
    for i, vals in enumerate(combos):
        params = dict(zip(keys, vals))
        # reset enables to baseline
        params.update({"ENABLE_HYDROGEL": True, "ENABLE_VFE_REVERSION": False,
                       "ENABLE_VEV_GAMMA": True, "ENABLE_IV_SCALP": False, "ENABLE_HEDGE": True})
        pnl = evaluate(Tr, params, reader, mode)
        rows.append({"pnl": pnl, "params": params})
        if (i + 1) % 5 == 0:
            print(f"  {i+1}/{len(combos)}  elapsed {time.time()-t0:.0f}s  best={max(r['pnl'] for r in rows):+,.0f}")
    rows.sort(key=lambda x: -x["pnl"])
    return rows


def fd_sensitivity(Tr, base_params, reader, mode, deltas):
    """Finite differences: tweak each param ±, measure PnL change.
    Flat region = robust. Sharp = brittle."""
    base_pnl = evaluate(Tr, base_params, reader, mode)
    print(f"\n=== FD sensitivity (base PnL = {base_pnl:+,.0f}) ===")
    out = {"base_pnl": base_pnl, "perturbations": {}}
    for k, dv in deltas.items():
        if k not in base_params:
            continue
        v0 = base_params[k]
        results = {}
        for sign in (-1, +1):
            p = dict(base_params); p[k] = v0 + sign * dv
            pnl = evaluate(Tr, p, reader, mode)
            results[f"{sign:+d}*{dv}"] = {"value": p[k], "pnl": pnl, "delta_vs_base": pnl - base_pnl}
        out["perturbations"][k] = results
        deltas_str = " | ".join(f"{s}: {r['pnl']:+,.0f} ({r['delta_vs_base']:+,.0f})" for s, r in results.items())
        print(f"  {k} = {v0}  ->  {deltas_str}")
    return out


def main():
    setup()
    from prosperity4bt.models import TradeMatchingMode
    mod = load()
    Tr = mod.Trader
    reader = FR(DATASET); mode = TradeMatchingMode.all

    print("=" * 60)
    print("STAGE 1: coarse grid")
    print("=" * 60)
    rows = coarse_grid(Tr, reader, mode)
    print("\nTop 5:")
    for r in rows[:5]:
        print(f"  PnL {r['pnl']:+,.0f}  {r['params']}")

    best = rows[0]
    print("\n" + "=" * 60)
    print("STAGE 2: FD sensitivity at best")
    print("=" * 60)
    deltas = {
        "HP_TAKE_EDGE": 1,
        "HP_QUOTE_FRONT": 5,
        "HP_EWMA_ALPHA": 0.05,
        "VEV_SIGMA_MODEL": 0.002,
        "VEV_GAMMA_EDGE_REQ": 0.5,
        "VEV_TAKE_SIZE": 10,
    }
    sens = fd_sensitivity(Tr, best["params"], reader, mode, deltas)

    # robustness score: avg of |delta_vs_base| -- LOWER = more robust
    avg_abs = []
    for k, perts in sens["perturbations"].items():
        for r in perts.values():
            avg_abs.append(abs(r["delta_vs_base"]))
    robust_score = sum(avg_abs) / len(avg_abs) if avg_abs else 0
    print(f"\nRobustness (mean |dPnL| across perturbations): {robust_score:,.0f}")
    print(f"  -> SMALLER is better (flat region, low sensitivity).")

    payload = {"best_params": best["params"], "best_pnl": best["pnl"],
               "robustness_score": robust_score, "fd": sens, "top5": rows[:5]}
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"\nSaved -> {OUT}")


if __name__ == "__main__":
    main()
