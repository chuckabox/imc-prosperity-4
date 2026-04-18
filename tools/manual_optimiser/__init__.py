"""Manual challenge optimiser — matches official R2 wiki.

Budget 50k XIRECs. x,y,z in %, x+y+z<=100. Cost = 500*(x+y+z).
Net = R(x)*S(y)*M(z) - cost.
"""

from .engine import (
    ProsperityOptimizer,
    research_value,
    scale_value,
    budget_used,
    rank_to_multiplier,
    sample_competitor_speeds,
    sample_cluster_speeds,
    speed_multiplier_vs_pop,
    BUDGET_TOTAL,
    COST_PER_POINT,
    POP_SIZE,
    BETA_A,
    BETA_B,
)
from .simulation import (
    monte_carlo,
    find_optima,
    grid_allocations,
    default_beta_sampler,
    run_scenarios,
    robust_optimum,
)
from . import scenarios

__all__ = [
    "ProsperityOptimizer", "research_value", "scale_value", "budget_used",
    "rank_to_multiplier", "sample_competitor_speeds", "sample_cluster_speeds",
    "speed_multiplier_vs_pop", "BUDGET_TOTAL", "COST_PER_POINT",
    "POP_SIZE", "BETA_A", "BETA_B",
    "monte_carlo", "find_optima", "grid_allocations", "default_beta_sampler",
    "run_scenarios", "robust_optimum", "scenarios",
]
