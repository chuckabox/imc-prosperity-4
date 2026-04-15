# Round 1 Portfolio: Overall Strategy Comparison

This document provides a high-level summary of the "Champion" traders from each development series (Ken, Peter, and Adin). By comparing the best-performing variants side-by-side, we identify the optimal candidate for top-tier competitive placement.

## 🏆 Champion Leaderboard

Performance metrics verified via `backtest_cli.py` across Days -2, -1, and 0.

| Series | Champion Filename | Style Category | Total PnL (Shells) | Key Edge |
| :--- | :--- | :--- | :--- | :--- |
| **Ken** | `trader_ken_v6_1.py` | **High-Fidelity MM** | **$301,481.00** | Adaptive mid-pull & split-level passive fills. |
| **Peter** | `trader_peter_aggressive.py` | **Aggressive Taker** | **$272,842.00** | Greedy volume capture in Pepper Root trends. |
| **Adin** | `trader_adin.py` | **Biased Accumulator** | **$243,504.00** | One-sided greedy asks with spike-only exits. |

---

## 🔍 Detailed Archetype Analysis

### 1. The Ken Series (`v6.1`) - *The Technical Standard*
- **Best For**: Maximum consistency and risk-adjusted returns.
- **Why it wins**: It is the most sophisticated market-maker in the repository. It uses a "mid-pull" adjustment to drift the anchor around 10k and splits its passive orders into two levels (62/38 split). This ensures it captures the queue efficiently and resists toxic flow.
- **Risk**: Moderate complexity; sensitive to specific parameter tuning.

### 2. The Peter Series (`aggressive`) - *The Volume King*
- **Best For**: High-volatility regimes and strong trends.
- **Why it wins**: It prioritizes time-in-market and total turnover. While it uses the same 10k anchor as Ken, it is much more aggressive in "taking" liquidity. This allows it to capture price movements faster than a passive maker.
- **Risk**: Prone to inventory pin-risk at the limits (80 units) during fast reversals.

### 3. The Adin Series (`adin`) - *The Trend Opportunist*
- **Best For**: Strong directional Pepper Root markets.
- **Why it wins**: Its "all-in" approach to buying asks ensures it stays fully loaded during upward drifts. It only exits on significant "spikes," maximizing profit-per-trade.
- **Risk**: Extremely vulnerable to mean-reversion crashes. If the market peaks and then drops, `trader_adin` will be holding max-inventory at the top.

---

## 🏛️ Final Conclusion & Selection

The **`trader_ken_v6_1.py`** is the current **Absolute Champion** of the repository with a $301k+ historical PnL. It balances the aggression of the Peter series with the technical precision required to handle varying market widths.

*For deeper analysis of each series, refer to:*
- [**ken_comparisons.md**](ken_comparisons.md) (Detailed Ken vs. 10k breakdown)
- [**peter_comparisons.md**](peter_comparisons.md) (Detailed Peter categorical audit)
