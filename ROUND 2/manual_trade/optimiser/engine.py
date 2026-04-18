"""ProsperityOptimizer core math.

Pillars: x=Research, y=Scale, z=Speed. Budget x+y+z=100.

Formulas:
    Research pnl:     R(x) = 200_000 * ln(1+x) / ln(101)
    Scale multiplier: S(y) = 1 + 0.07 * y
    Speed multiplier: M(z) rank-based in [0.1, 0.9] vs population

    Gross(x,y,z) = R(x) * S(y) * M(z)
    Net          = Gross - 50_000
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


LN_101 = math.log(101)
FIXED_COST = 50_000.0
POP_SIZE = 10_000
BETA_A = 2.0
BETA_B = 5.0


def research_pnl(x: float) -> float:
    # R(x) = 200000 * ln(1+x) / ln(101)
    return 200_000.0 * math.log1p(x) / LN_101


def scale_multiplier(y: float) -> float:
    # S(y) = 1 + 0.07 * y
    return 1.0 + 0.07 * y


def rank_to_multiplier(rank_pct: float) -> float:
    # rank_pct in [0,1], 0 = best (top). Map to [0.9 ... 0.1]
    return 0.9 - 0.8 * rank_pct


def sample_competitor_speeds(n: int = POP_SIZE, rng: np.random.Generator | None = None) -> np.ndarray:
    # Competitor z ~ Beta(2,5) * 100. Skewed low, few high bidders.
    rng = rng or np.random.default_rng()
    return rng.beta(BETA_A, BETA_B, size=n) * 100.0


def speed_multiplier_vs_pop(z: float, pop: np.ndarray) -> float:
    # Rank among pop+self. rank_pct = (# strictly better) / total.
    total = pop.size + 1
    better = int(np.sum(pop > z))
    # ties share rank — take midpoint
    ties = int(np.sum(pop == z))
    rank_pct = (better + 0.5 * ties) / total
    return rank_to_multiplier(rank_pct)


@dataclass
class Allocation:
    x: float
    y: float
    z: float

    def valid(self) -> bool:
        return abs(self.x + self.y + self.z - 100) < 1e-6 and min(self.x, self.y, self.z) >= 0


@dataclass
class PnLBreakdown:
    research: float
    scale_mult: float
    speed_mult: float
    gross: float
    net: float


class ProsperityOptimizer:
    """Core calculator. Stateless math; pop injected for determinism."""

    def __init__(self, pop: np.ndarray | None = None, seed: int = 42):
        self.rng = np.random.default_rng(seed)
        self.pop = pop if pop is not None else sample_competitor_speeds(rng=self.rng)

    def pnl(self, x: float, y: float, z: float, pop: np.ndarray | None = None) -> PnLBreakdown:
        r = research_pnl(x)
        s = scale_multiplier(y)
        m = speed_multiplier_vs_pop(z, pop if pop is not None else self.pop)
        gross = r * s * m
        return PnLBreakdown(research=r, scale_mult=s, speed_mult=m, gross=gross, net=gross - FIXED_COST)

    def expected_speed_mult(self, z: float) -> float:
        return speed_multiplier_vs_pop(z, self.pop)
