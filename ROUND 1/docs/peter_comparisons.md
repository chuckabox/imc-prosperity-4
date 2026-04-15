# Peter & 10k Trader Comparison

This document summarizes the comparison of all "Peter" and "10k" series traders found in the repository. The evaluation focuses on three key metrics: PnL potential, aggressiveness, and safety/robustness.

## Evaluated Traders

### 1. `trader_10k.py` (Aggressive)
- **Strategy**: Hybrid Sniper + Aggressive Pennying for Osmium; Greedy Taker logic for Pepper Root.
- **Key Features**: 
    - Takes ALL available asks greedily for Pepper Root regardless of price, assuming regression edge.
    - Uses tape-aware fair price for Osmium with high sensitivity.
- **Verdict**: **Best for Aggressive**. High turnover, high liquidity capture, but higher risk of being adversely selected.

### 2. `trader_10k_clean.py` (Safe)
- **Strategy**: Conservative Market Making with locked fair values.
- **Key Features**:
    - Osmium fair price locked to 10,000.0 for maximum robustness.
    - Large safety margins (`take_margin = 5.0`).
    - No aggressive tape-dependent adjustments.
- **Verdict**: **Best for Safe**. Ideal for stable market conditions or as a baseline "fail-safe" trader.

### 3. `trader_peter_v2.py` (PnL Optimized)
- **Strategy**: Dynamic Mean Reversion + Trend Following.
- **Key Features**:
    - Uses 20-period EMA to follow trends in Osmium combined with tape momentum.
    - Regression-based trend following for Pepper Root with price-cap guards.
    - Balanced position-skewing factors.
- **Verdict**: **Best for PnL**. Most sophisticated fair price estimation, balancing momentum capture with mean reversion stability.

### 4. `trader_peter_v1.py` (Archived)
- **Highlights**: Included panic exits and stop-loss logic, but less refined fair price estimation than v2.

### 5. `trader_peter_2_2_2.py` (Archived)
- **Highlights**: Extremely complex dual-regime system with momentum analysis. High overhead and potential for overfitting.

---

## Final Selection

| Category | Selection | Rationale |
| :--- | :--- | :--- |
| **Best PnL** | `trader_peter_v2.py` | Superior trend tracking via EMA and regression convergence. |
| **Aggressive** | `trader_10k.py` | Greedy taker logic maximizes volume and turnover. |
| **Safe** | `trader_10k_clean.py` | Minimal assumptions; robust anchor at 10k prevents "fair price drift". |

*Legacy Peter and 10k traders have been moved to `ROUND 1/archive/old_peter`.*
