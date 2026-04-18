"""ProsperityOptimizer core math — matches official R2 wiki.

Pillars: x=Research, y=Scale, z=Speed (each in %, 0..100).
Constraint: x+y+z <= 100 (partial allocation allowed).

Formulas (official):
    Research value:   R(x) = 200_000 * ln(1+x) / ln(101)        (0 → 200k at x=100)
    Scale value:      S(y) = 0.07 * y                           (0 → 7 at y=100)
    Speed multiplier: M(z) rank-based in [0.1, 0.9] vs full player pop

    Budget used:      C(x,y,z) = BUDGET * (x+y+z) / 100  = 500 * (x+y+z)    [XIRECs]
    Gross PnL:        G(x,y,z) = R(x) * S(y) * M(z)
    Net PnL:          Net = G − C

Budget total = 50_000 XIRECs. Each percent point costs 500 XIRECs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


LN_101 = math.log(101)
BUDGET_TOTAL = 50_000.0       # XIRECs
COST_PER_POINT = BUDGET_TOTAL / 100.0   # = 500 XIRECs per % invested
POP_SIZE = 10_000
BETA_A = 2.0
BETA_B = 5.0


def research_value(x: float) -> float:
    return 200_000.0 * math.log1p(x) / LN_101


def scale_value(y: float) -> float:
    return 0.07 * y


def budget_used(x: float, y: float, z: float) -> float:
    return COST_PER_POINT * (x + y + z)


def rank_to_multiplier(rank_pct: float) -> float:
    # rank_pct in [0,1], 0 = best rank. Linear map to [0.9 ... 0.1].
    return 0.9 - 0.8 * rank_pct


def sample_competitor_speeds(n: int = POP_SIZE, rng: np.random.Generator | None = None) -> np.ndarray:
    """Beta(2,5) × 100 — skewed-low baseline scenario."""
    rng = rng or np.random.default_rng()
    return rng.beta(BETA_A, BETA_B, size=n) * 100.0


def sample_cluster_speeds(clusters: list[dict], pop_size: int,
                          rng: np.random.Generator | None = None) -> np.ndarray:
    """Cluster mix: each {'center','spread','pct'}. Spread<=0 → delta."""
    rng = rng or np.random.default_rng()
    tot = sum(c["pct"] for c in clusters) or 1.0
    out = []
    for c in clusters:
        n = int(round((c["pct"] / tot) * pop_size))
        if n <= 0:
            continue
        if c["spread"] <= 0:
            out.append(np.full(n, c["center"], dtype=float))
        else:
            out.append(rng.normal(c["center"], c["spread"], n))
    if not out:
        return np.full(pop_size, 40.0)
    return np.clip(np.concatenate(out), 0, 100)


def speed_multiplier_vs_pop(z: float, pop: np.ndarray) -> float:
    total = pop.size + 1
    better = int(np.sum(pop > z))
    ties = int(np.sum(pop == z))
    rank_pct = (better + 0.5 * ties) / total
    return rank_to_multiplier(rank_pct)


@dataclass
class PnLBreakdown:
    research: float
    scale_value: float
    speed_mult: float
    gross: float
    cost: float
    net: float


class ProsperityOptimizer:
    def __init__(self, pop: np.ndarray | None = None, seed: int = 42):
        self.rng = np.random.default_rng(seed)
        self.pop = pop if pop is not None else sample_competitor_speeds(rng=self.rng)

    def pnl(self, x: float, y: float, z: float, pop: np.ndarray | None = None) -> PnLBreakdown:
        r = research_value(x)
        s = scale_value(y)
        m = speed_multiplier_vs_pop(z, pop if pop is not None else self.pop)
        gross = r * s * m
        cost = budget_used(x, y, z)
        return PnLBreakdown(research=r, scale_value=s, speed_mult=m,
                            gross=gross, cost=cost, net=gross - cost)

    def expected_speed_mult(self, z: float) -> float:
        return speed_multiplier_vs_pop(z, self.pop)


# Back-compat alias used by older plotting code paths
FIXED_COST = BUDGET_TOTAL
research_pnl = research_value
