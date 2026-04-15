# Peter & 10k Trader Portfolio: Technical Audit & Comparison

This document provides a deep-dive technical analysis of the "Peter" and "10k" series traders. Following the standard comparative auditing format, we analyze the structural edges, regime adaptability, and backtest-validated performance.

## 📊 Backtest Results Breakdown

Verified results using `backtest_cli.py` on Round 1 historical data.

| Trader | Day -2 | Day -1 | Day 0 | **Total PnL** |
| :--- | :--- | :--- | :--- | :--- |
| **`trader_10k.py`** | 90,885.00 | 92,362.00 | 89,595.00 | **$272,842.00** |
| **`trader_10k_clean.py`** | 82,705.00 | 85,270.00 | 78,089.00 | **$246,064.00** |
| **`trader_peter_v2.py`** | 84,115.00 | 84,651.00 | 40,736.00 | **$209,502.00** |

### Product PnL Attribution (Cumulative)
- **Aggressive (10k)**: dominant in Pepper Root due to greedy volume intake.
- **Safe (10k Clean)**: stable across both products but misses "tail" opportunities.
- **Trend (Peter v2)**: strong Osmium performance but struggled with Pepper Root directionality on Day 0.

---

## 🔬 Technical Strategy Evolution

| Version | Edge Hypothesis | Structural Logic | Risk Profile |
| :--- | :--- | :--- | :--- |
| **10k (Baseline)** | Market Stationarity | `Price = 10000 + Tape`. Assumes any deviation from 10k is a mean-reverting opportunity unless confirmed by tape volume. | **High**: Can be run over by structural shifts. |
| **10k Clean** | Liquidity Provision | Fixed anchors + wide margins. Profit comes from the bid-ask spread. | **Low**: High survival, lower yield. |
| **Peter v2** | EMA Momentum | `Price = EMA(20) + Tape`. Assumes the mean itself drifts and tracks it with exponential weighting. | **Medium**: Prone to whipsaws in fast mean-reversion. |

---

## 🕵️ Technical Grandmaster Deep-Dive

### 1. The "Anchor" vs. "Drift" Dilemma (Osmium Analysis)
In Technical Analysis, the choice of a "Fair Value" is everything. 
- **`trader_10k`** treats Osmium as a **Rangebound Oscillator**. It snipes anything >2.5 ticks from the anchor. This worked best because Osmium is effectively stationary around 10,000.
- **`trader_peter_v2`** treats it as a **Trending Asset**. On Day 0, Osmium's volatility caused the EMA to lag, leading to poor entry timing. 

### 2. Volume Profile & Tape Confirmation
- **`trader_10k`** uses a `tape_adj` with a cap of 2.5. This effectively acts as a "Momentum Burst" filter. 
- **`trader_10k`**'s outperformance in Pepper Root is due to its **Greedy Taker** logic, ensuring it stays long during upward drifts by accepting any ask price that meets its regression criteria.

---

## ⚔️ Pairwise Comparison: `trader_10k` vs `trader_peter_v2`

| Factor | `trader_10k` | `trader_peter_v2` | Technical Impact |
| :--- | :--- | :--- | :--- |
| **Fair Price Basis** | Hard Anchor (10000) | EMA(20) | `10k` wins on mean-reverting assets; `EMA` wins on trending ones. |
| **Execution Alpha** | Aggressive Pennying | Skewed MM | `10k` stays at the front of the queue. |
| **Tape Sensitivity** | High (0.15 coeff) | Medium (0.10 coeff) | `10k` catches breakouts faster. |
| **PnL Efficiency** | **1.30x** vs v2 | 1.00x | Aggressive taker logic is currently the dominant factor. |

---

## 🚩 Risk Audit (Technical Warnings)
> [!WARNING]
> **Overfitting to Stationarity**: `trader_10k` is heavily optimized for a market that returns to 10,000. If the market fundamentally shifts its benchmark, this bot will fight the trend.

---

## 🏛️ Recommendation & Next Steps

1. **Current Production Selection**: **`trader_10k.py`** is the winner for pure volume/PnL.
2. **Hybrid Opportunity**: Integrate **Panic Exits** from `peter_v1` into the `10k` logic for risk protection.
3. **Indicator Optimization**: Shorten the EMA window (e.g., EMA 8) for `peter_v2` to reduce lag in fast regimes.

*Legacy traders have been moved to `ROUND 1/archive/old_peter`.*
