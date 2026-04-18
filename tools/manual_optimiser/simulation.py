"""Monte Carlo + grid search over (x,y,z) with x+y+z <= 100.

Fast path: speed multiplier depends ONLY on z. Sample per-z distribution
across MC iterations, then compose analytically for every (x,y,z).

    Net(x,y,z) = R(x) * S(y) * M(z) − 500*(x+y+z)

R(x)*S(y) is a non-negative constant per (x,y), so any monotone stat of M(z)
(mean, p05, p95, P(M≥τ)) translates linearly to Net.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

try:
    from .engine import (
        rank_to_multiplier,
        sample_competitor_speeds,
        COST_PER_POINT,
        POP_SIZE,
    )
except ImportError:
    from engine import (  # type: ignore
        rank_to_multiplier,
        sample_competitor_speeds,
        COST_PER_POINT,
        POP_SIZE,
    )


Sampler = Callable[[np.random.Generator], np.ndarray]


def default_beta_sampler(pop_size: int = POP_SIZE) -> Sampler:
    def _s(rng: np.random.Generator) -> np.ndarray:
        return sample_competitor_speeds(pop_size, rng=rng)
    return _s


def grid_allocations(step: int = 1, max_total: int = 100) -> np.ndarray:
    """All integer (x,y,z) with x+y+z <= max_total, each >=0."""
    out = []
    for x in range(0, max_total + 1, step):
        for y in range(0, max_total - x + 1, step):
            for z in range(0, max_total - x - y + 1, step):
                out.append((x, y, z))
    return np.asarray(out, dtype=np.int32)


def speed_mult_batch(zs: np.ndarray, pop: np.ndarray) -> np.ndarray:
    pop_sorted = np.sort(pop)
    right = np.searchsorted(pop_sorted, zs, side="right")
    left = np.searchsorted(pop_sorted, zs, side="left")
    better = pop_sorted.size - right
    ties = right - left
    rank_pct = (better + 0.5 * ties) / (pop_sorted.size + 1)
    return rank_to_multiplier(rank_pct)


def _mc_per_z_stats(n_iter: int, seed: int, sampler: Sampler,
                    safety_threshold: float) -> dict:
    """Run MC. Return per-z stats of the speed multiplier."""
    zs = np.arange(0, 101, dtype=float)   # (101,)
    rng = np.random.default_rng(seed)
    M = np.zeros((n_iter, 101), dtype=np.float32)
    for i in range(n_iter):
        pop = sampler(rng)
        M[i] = speed_mult_batch(zs, pop)
    return {
        "zs": zs.astype(np.int32),
        "m_mean": M.mean(axis=0),
        "m_std": M.std(axis=0),
        "m_p05": np.percentile(M, 5, axis=0),
        "m_p50": np.percentile(M, 50, axis=0),
        "m_p95": np.percentile(M, 95, axis=0),
        "m_prob_safe": (M >= safety_threshold).mean(axis=0),
        "M_samples": M,   # optional, only used for per-alloc hist
    }


def monte_carlo(
    n_iter: int = 1000,
    seed: int = 0,
    safety_threshold: float = 0.5,
    sampler: Sampler | None = None,
    grid_step: int = 1,
    max_total: int = 100,
) -> dict:
    """Run MC and compose per-alloc stats analytically."""
    sampler = sampler or default_beta_sampler()
    zst = _mc_per_z_stats(n_iter, seed, sampler, safety_threshold)

    grid = grid_allocations(step=grid_step, max_total=max_total)
    xs = grid[:, 0].astype(float)
    ys = grid[:, 1].astype(float)
    zs = grid[:, 2].astype(int)
    R = 200_000.0 * np.log1p(xs) / np.log(101.0)
    S = 0.07 * ys
    RS = R * S
    cost = COST_PER_POINT * (xs + ys + zs.astype(float))

    mean_net = RS * zst["m_mean"][zs] - cost
    p05_net = RS * zst["m_p05"][zs] - cost
    p50_net = RS * zst["m_p50"][zs] - cost
    p95_net = RS * zst["m_p95"][zs] - cost
    std_net = RS * zst["m_std"][zs]
    prob_safe = zst["m_prob_safe"][zs]

    return {
        "grid": grid,
        "mean_net": mean_net,
        "p05_net": p05_net,
        "median_net": p50_net,
        "p95_net": p95_net,
        "std_net": std_net,
        "prob_safe": prob_safe,
        "cost": cost,
        "gross_mean": RS * zst["m_mean"][zs],
        "per_z": zst,
    }


def _pack(row: np.ndarray, stats: dict, i: int) -> dict:
    return {
        "alloc": [int(row[0]), int(row[1]), int(row[2])],
        "total": int(row.sum()),
        "cost": float(stats["cost"][i]),
        "mean_net": float(stats["mean_net"][i]),
        "p05_net": float(stats["p05_net"][i]),
        "p95_net": float(stats["p95_net"][i]),
        "prob_speed_safe": float(stats["prob_safe"][i]),
    }


def find_optima(sim: dict, safety_prob: float = 0.95) -> dict:
    grid = sim["grid"]
    gi = int(np.argmax(sim["mean_net"]))
    global_opt = _pack(grid[gi], sim, gi)

    mask = sim["prob_safe"] >= safety_prob
    if mask.any():
        sub = np.where(mask)[0]
        si = int(sub[np.argmax(sim["mean_net"][sub])])
        safety_opt = _pack(grid[si], sim, si)
    else:
        safety_opt = None

    pi = int(np.argmax(sim["p05_net"]))
    p05_opt = _pack(grid[pi], sim, pi)

    return {
        "global": global_opt,
        "safety": safety_opt,
        "p05_max": p05_opt,
        "safety_prob_threshold": safety_prob,
    }


# --- Multi-scenario ---

def run_scenarios(scenarios: dict[str, Sampler], n_iter: int = 1000,
                  seed: int = 42, safety_threshold: float = 0.5,
                  safety_prob: float = 0.95,
                  grid_step: int = 1, max_total: int = 100) -> dict:
    """Run MC for each named scenario. Returns sims + optima per scenario."""
    sims = {}
    optima = {}
    for name, sampler in scenarios.items():
        sim = monte_carlo(n_iter=n_iter, seed=seed,
                          safety_threshold=safety_threshold,
                          sampler=sampler, grid_step=grid_step,
                          max_total=max_total)
        sims[name] = sim
        optima[name] = find_optima(sim, safety_prob=safety_prob)
    return {"sims": sims, "optima": optima}


def robust_optimum(sims_by_scenario: dict) -> dict:
    """Allocation maximising MIN mean_net across scenarios (maximin).

    Requires all sims share the same grid.
    """
    names = list(sims_by_scenario.keys())
    grids = [sims_by_scenario[n]["grid"] for n in names]
    # sanity: same grid
    ref = grids[0]
    for g in grids[1:]:
        if g.shape != ref.shape or not np.array_equal(g, ref):
            raise ValueError("Scenarios have different grids")
    stacked_mean = np.stack([sims_by_scenario[n]["mean_net"] for n in names])  # (S, G)
    stacked_p05 = np.stack([sims_by_scenario[n]["p05_net"] for n in names])
    worst_mean = stacked_mean.min(axis=0)
    worst_p05 = stacked_p05.min(axis=0)
    best_worst_mean = int(np.argmax(worst_mean))
    best_worst_p05 = int(np.argmax(worst_p05))
    return {
        "maximin_mean": {
            "alloc": [int(v) for v in ref[best_worst_mean]],
            "worst_case_mean_net": float(worst_mean[best_worst_mean]),
            "per_scenario_mean_net": {
                n: float(sims_by_scenario[n]["mean_net"][best_worst_mean])
                for n in names
            },
            "per_scenario_p05_net": {
                n: float(sims_by_scenario[n]["p05_net"][best_worst_mean])
                for n in names
            },
        },
        "maximin_p05": {
            "alloc": [int(v) for v in ref[best_worst_p05]],
            "worst_case_p05_net": float(worst_p05[best_worst_p05]),
            "per_scenario_p05_net": {
                n: float(sims_by_scenario[n]["p05_net"][best_worst_p05])
                for n in names
            },
        },
    }
