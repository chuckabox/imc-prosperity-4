"""CLI: run ALL scenarios, print table + robust pick, write JSON."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

try:
    from . import scenarios as sc
    from .simulation import run_scenarios, robust_optimum
except ImportError:
    import scenarios as sc  # type: ignore
    from simulation import run_scenarios, robust_optimum  # type: ignore


def main(n_iter: int = 1000, seed: int = 42, safety_thr: float = 0.5,
         safety_prob: float = 0.95, grid_step: int = 1):
    out = run_scenarios(
        sc.ALL_SCENARIOS, n_iter=n_iter, seed=seed,
        safety_threshold=safety_thr, safety_prob=safety_prob,
        grid_step=grid_step, max_total=100,
    )
    robust = robust_optimum(out["sims"])

    # Table
    print(f"\n{'Scenario':<35} | {'Safety Alloc':<14} | {'mean_net':>10} | {'p05_net':>10} | safe%")
    print("-" * 90)
    for name, opt in out["optima"].items():
        o = opt["safety"] or opt["global"]
        a = tuple(o["alloc"])
        print(f"{name:<35} | {str(a):<14} | {o['mean_net']:>10,.0f} | "
              f"{o['p05_net']:>10,.0f} | {o['prob_speed_safe']:.2%}")

    print("\n=== ROBUST MAXIMIN (worst-case across all scenarios) ===")
    r = robust["maximin_mean"]
    print(f"alloc = {r['alloc']}   worst-case mean = {r['worst_case_mean_net']:,.0f}")
    print("per-scenario mean:")
    for k, v in r["per_scenario_mean_net"].items():
        print(f"  {k:<40} {v:>10,.0f}")

    r2 = robust["maximin_p05"]
    print(f"\nalloc (maximin P05) = {r2['alloc']}  worst-case P05 = {r2['worst_case_p05_net']:,.0f}")

    # Strip heavy arrays from payload
    clean_sims = {}
    for name, sim in out["sims"].items():
        clean_sims[name] = {
            "mean_net_top10": _top10(sim),
        }
    payload = {
        "params": {
            "n_iter": n_iter, "seed": seed,
            "safety_threshold": safety_thr, "safety_prob": safety_prob,
            "budget_total": 50000, "cost_per_point": 500,
        },
        "optima_per_scenario": out["optima"],
        "robust_maximin_mean": robust["maximin_mean"],
        "robust_maximin_p05": robust["maximin_p05"],
        "top10_per_scenario": clean_sims,
    }
    out_path = Path(__file__).parent / "optimum_config.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nWrote {out_path}")


def _top10(sim: dict):
    idx = np.argsort(-sim["mean_net"])[:10]
    grid = sim["grid"]
    return [
        {
            "alloc": [int(v) for v in grid[i]],
            "mean_net": float(sim["mean_net"][i]),
            "p05_net": float(sim["p05_net"][i]),
            "cost": float(sim["cost"][i]),
            "prob_safe": float(sim["prob_safe"][i]),
        }
        for i in idx
    ]


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--iter", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--safety-thr", type=float, default=0.5)
    p.add_argument("--safety-prob", type=float, default=0.95)
    p.add_argument("--grid-step", type=int, default=1)
    a = p.parse_args()
    main(a.iter, a.seed, a.safety_thr, a.safety_prob, a.grid_step)
