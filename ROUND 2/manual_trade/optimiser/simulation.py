"""Monte Carlo + grid search over (x,y,z) with x+y+z=100."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable

import numpy as np

from engine import (
    ProsperityOptimizer,
    research_pnl,
    scale_multiplier,
    rank_to_multiplier,
    sample_competitor_speeds,
    FIXED_COST,
    POP_SIZE,
)


def grid_allocations(step: int = 1) -> np.ndarray:
    # All integer (x,y,z) with x+y+z=100, each >=0. Shape (N,3).
    out = []
    for x in range(0, 101, step):
        for y in range(0, 101 - x, step):
            z = 100 - x - y
            out.append((x, y, z))
    return np.asarray(out, dtype=np.int32)


def precompute_research(grid: np.ndarray) -> np.ndarray:
    xs = grid[:, 0].astype(float)
    return 200_000.0 * np.log1p(xs) / np.log(101.0)


def precompute_scale(grid: np.ndarray) -> np.ndarray:
    return 1.0 + 0.07 * grid[:, 1].astype(float)


def speed_mult_batch(zs: np.ndarray, pop: np.ndarray) -> np.ndarray:
    # Vectorised rank of each z vs pop. zs shape (M,), pop shape (N,).
    pop_sorted = np.sort(pop)
    # # strictly better = N - searchsorted(pop, z, 'right')
    right = np.searchsorted(pop_sorted, zs, side="right")
    left = np.searchsorted(pop_sorted, zs, side="left")
    better = pop_sorted.size - right
    ties = right - left
    total = pop_sorted.size + 1
    rank_pct = (better + 0.5 * ties) / total
    return rank_to_multiplier(rank_pct)


@dataclass
class SimResult:
    alloc: tuple
    mean_net: float
    median_net: float
    std_net: float
    p05_net: float
    p95_net: float
    prob_speed_above_0p5: float


def monte_carlo(
    n_iter: int = 1_000,
    grid_step: int = 1,
    pop_size: int = POP_SIZE,
    seed: int = 0,
    safety_threshold: float = 0.5,
) -> dict:
    """Run N_iter independent competitor pops across full grid.

    Returns dict with arrays indexed by allocation rows of `grid`.
    """
    rng = np.random.default_rng(seed)
    grid = grid_allocations(grid_step)
    R = precompute_research(grid)  # (G,)
    S = precompute_scale(grid)     # (G,)
    zs = grid[:, 2].astype(float)  # (G,)

    n_alloc = grid.shape[0]
    net_samples = np.zeros((n_iter, n_alloc), dtype=np.float32)
    speed_samples = np.zeros((n_iter, n_alloc), dtype=np.float32)

    for i in range(n_iter):
        pop = sample_competitor_speeds(pop_size, rng=rng)
        m = speed_mult_batch(zs, pop)  # (G,)
        speed_samples[i] = m
        gross = R * S * m
        net_samples[i] = gross - FIXED_COST

    mean_net = net_samples.mean(axis=0)
    median_net = np.median(net_samples, axis=0)
    std_net = net_samples.std(axis=0)
    p05 = np.percentile(net_samples, 5, axis=0)
    p95 = np.percentile(net_samples, 95, axis=0)
    prob_safe = (speed_samples >= safety_threshold).mean(axis=0)

    return {
        "grid": grid,
        "mean_net": mean_net,
        "median_net": median_net,
        "std_net": std_net,
        "p05_net": p05,
        "p95_net": p95,
        "prob_safe": prob_safe,
        "net_samples": net_samples,
        "speed_samples": speed_samples,
    }


def find_optima(sim: dict, safety_prob: float = 0.95) -> dict:
    grid = sim["grid"]
    mean_net = sim["mean_net"]
    prob_safe = sim["prob_safe"]

    # Global: argmax mean_net
    gi = int(np.argmax(mean_net))
    global_opt = {
        "alloc": tuple(int(v) for v in grid[gi]),
        "mean_net": float(mean_net[gi]),
        "p05_net": float(sim["p05_net"][gi]),
        "p95_net": float(sim["p95_net"][gi]),
        "prob_speed_safe": float(prob_safe[gi]),
    }

    # Safety: among those with prob_safe >= safety_prob, max mean_net
    mask = prob_safe >= safety_prob
    if mask.any():
        idx_sub = np.where(mask)[0]
        si = int(idx_sub[np.argmax(mean_net[idx_sub])])
        safety_opt = {
            "alloc": tuple(int(v) for v in grid[si]),
            "mean_net": float(mean_net[si]),
            "p05_net": float(sim["p05_net"][si]),
            "p95_net": float(sim["p95_net"][si]),
            "prob_speed_safe": float(prob_safe[si]),
        }
    else:
        safety_opt = None

    return {"global": global_opt, "safety": safety_opt, "safety_prob_threshold": safety_prob}
