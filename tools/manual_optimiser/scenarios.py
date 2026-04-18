"""Predefined competitor-speed distributions to stress-test allocations.

Each scenario returns a `Sampler`: `Callable[[np.random.Generator], np.ndarray]`
producing an array of competitor speed bids in [0, 100].
"""

from __future__ import annotations

import numpy as np

try:
    from .engine import POP_SIZE
except ImportError:
    from engine import POP_SIZE  # type: ignore


def _clip(a: np.ndarray) -> np.ndarray:
    return np.clip(a, 0, 100)


def beta_2_5(pop_size: int = POP_SIZE):
    """Most bid low, few outliers — original 'lazy market' assumption."""
    def _s(rng): return rng.beta(2, 5, pop_size) * 100.0
    return _s


def uniform(pop_size: int = POP_SIZE):
    """Everyone bids uniformly 0-100 — maximum chaos."""
    def _s(rng): return rng.uniform(0, 100, pop_size)
    return _s


def bimodal_lazy_and_herd(pop_size: int = POP_SIZE, lazy_frac: float = 0.4):
    """40% bid ~0 (lazy / newcomers), 60% cluster at 40 ± 8 (copy-cats)."""
    def _s(rng):
        n_lazy = int(pop_size * lazy_frac)
        lazy = rng.normal(2, 1.5, n_lazy)
        herd = rng.normal(40, 8, pop_size - n_lazy)
        return _clip(np.concatenate([lazy, herd]))
    return _s


def herd_midrange(pop_size: int = POP_SIZE, mu: float = 50.0, sigma: float = 12.0):
    """Everyone converges on mid-range 'obvious' answer ~50."""
    def _s(rng):
        return _clip(rng.normal(mu, sigma, pop_size))
    return _s


def aggressive_market(pop_size: int = POP_SIZE, mu: float = 70.0, sigma: float = 15.0):
    """Bidding war — most invest heavily in speed."""
    def _s(rng):
        return _clip(rng.normal(mu, sigma, pop_size))
    return _s


def normal_distribution(pop_size: int = POP_SIZE, mu: float = 50.0, sigma: float = 20.0):
    """Standard normal distribution — symmetrical around center."""
    def _s(rng):
        return _clip(rng.normal(mu, sigma, pop_size))
    return _s


def truncated_exponential(pop_size: int = POP_SIZE, scale: float = 15.0):
    """Heavy tail: many near 0, long tail up to 100."""
    def _s(rng):
        return _clip(rng.exponential(scale, pop_size))
    return _s


def three_camps(pop_size: int = POP_SIZE):
    """25% lazy(0), 50% midrange(45±8), 25% max-bidders(~85±5)."""
    def _s(rng):
        n1 = pop_size // 4
        n3 = pop_size // 4
        n2 = pop_size - n1 - n3
        a = rng.normal(2, 1, n1)
        b = rng.normal(45, 8, n2)
        c = rng.normal(85, 5, n3)
        return _clip(np.concatenate([a, b, c]))
    return _s


ALL_SCENARIOS = {
    "Beta(2,5) - lazy market":        beta_2_5(),
    "Uniform(0,100) - chaos":         uniform(),
    "Bimodal lazy+herd@40":           bimodal_lazy_and_herd(),
    "Normal (mu=50, sigma=20)":       normal_distribution(),
    "Herd at midrange (mu=50)":       herd_midrange(),
    "Aggressive market (mu=70)":      aggressive_market(),
    "Exponential (scale=15)":         truncated_exponential(),
    "Three camps (0/45/85)":          three_camps(),
}
