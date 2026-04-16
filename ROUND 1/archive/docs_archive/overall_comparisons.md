# Round 1 Portfolio: Overall Strategy Comparison

This document provides a high-level summary of the "Champion" traders from each development series. By comparing the best-performing variants side-by-side, we identify the optimal candidate for top-tier competitive placement.

## 🏆 Champion Leaderboard

Performance metrics verified via `backtest_cli.py` across Days -2, -1, and 0.

| Series | Champion Filename | Style Category | Total PnL (Shells) | Profit Factor |
| :--- | :--- | :--- | :--- | :--- |
| **Peter** | `trader_peter_v3.py` | **Ultra-Precision MM** | **$301,809.00** 🏆 | **2.21** |
| **Ken** | `trader_ken_v6_1.py` | **High-Fidelity MM** | **$301,481.00** | 2.18 |
| **Adin** | `trader_adin.py` | Biased Accumulator | $243,504.00 | 1.45 |

---

## 🔬 Head-to-Head: Peter v3 vs. Ken v6.1

While both traders are elite institutional-grade market makers, Peter v3 is the evolved version of the hybrid logic, successfully displacing Ken for the #1 spot.

### Key Technical Differences

| Feature | Ken v6.1 | Peter v3 | Strategic Impact |
| :--- | :--- | :--- | :--- |
| **Layer Allocation** | Fixed 62% / 38% | **Dynamic Imbalance-Weighted** | **Peter v3** shifts more size to the TOB (up to 72%) when order book pressure confirms a move, capturing more "hot" liquidity. |
| **Spread Handling** | Always Pennying | **Spread Clamping (Guardian)** | **Peter v3** joins the existing queue if the spread is already 1 tick. This prevents "Pennying Wars" that destroy the available edge. |
| **Fair Price Anchor** | Adaptive Mid-Pull | Adaptive Mid-Pull | Both track the drift around 10k, ensuring they aren't trapped by short-term imbalance. |
| **Pepper Logic** | Aggressive Taker | Aggressive Taker | Both use the dominant "Peter-Series" Pepper logic for maximum trend capture. |

### Why Peter v3 is the Superior Choice
The **+$328** PnL difference in local backtests is a signal of better **Microstructure Hygiene**. By "clamping" the spread and weighting its layers based on imbalance, Peter v3 acts more like a sophisticated HFT bot that respects its own profit margins. On the live leaderboard, where competition for the inside quote is fierce, Peter v3's "Guardian Mode" will prevent it from bidding away its own profit.

---

## 🏛️ Final Conclusion & Selection

The **`trader_peter_v3.py`** is the current **Absolute Champion** of the repository. It offers the highest PnL with the most advanced risk-management and spread-preservation features.

- **Primary Deployment**: `trader_peter_v3.py`
- **Secondary Deployment**: `trader_ken_v6_1.py` (for high-volatility scenarios)
