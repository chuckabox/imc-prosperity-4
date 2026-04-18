"""CLI: run MC, print optima, write JSON. No Streamlit required."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from simulation import monte_carlo, find_optima
from engine import FIXED_COST


def main(n_iter: int = 1000, seed: int = 42, safety_thr: float = 0.5, safety_prob: float = 0.95):
    sim = monte_carlo(n_iter=n_iter, seed=seed, safety_threshold=safety_thr)
    optima = find_optima(sim, safety_prob=safety_prob)

    # Enrich: for each optimum, compute P(net>=200k) and P(net>=179k)
    grid = sim["grid"]
    ns = sim["net_samples"]
    for key in ("global", "safety"):
        o = optima[key]
        if o is None:
            continue
        a = o["alloc"]
        idx = np.where((grid[:, 0] == a[0]) & (grid[:, 1] == a[1]) & (grid[:, 2] == a[2]))[0][0]
        col = ns[:, idx]
        o["prob_net_ge_200k"] = float(np.mean(col >= 200_000))
        o["prob_net_ge_179k"] = float(np.mean(col >= 179_000))
        o["p05"] = float(np.percentile(col, 5))
        o["p50"] = float(np.percentile(col, 50))
        o["p95"] = float(np.percentile(col, 95))

    # Top-10 by mean_net
    top = np.argsort(-sim["mean_net"])[:10]
    top10 = []
    for i in top:
        a = tuple(int(v) for v in grid[i])
        top10.append({
            "alloc": a,
            "mean_net": float(sim["mean_net"][i]),
            "p05": float(sim["p05_net"][i]),
            "p95": float(sim["p95_net"][i]),
            "prob_safe": float(sim["prob_safe"][i]),
        })

    payload = {
        "params": {"n_iter": n_iter, "seed": seed,
                   "safety_threshold": safety_thr, "safety_prob": safety_prob,
                   "fixed_cost": FIXED_COST},
        "optima": optima,
        "top10_by_mean_net": top10,
    }

    out = Path(__file__).parent / "optimum_config.json"
    out.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--iter", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--safety-thr", type=float, default=0.5)
    p.add_argument("--safety-prob", type=float, default=0.95)
    a = p.parse_args()
    main(a.iter, a.seed, a.safety_thr, a.safety_prob)
