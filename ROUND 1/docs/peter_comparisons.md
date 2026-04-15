# Peter & 10k Trader Portfolio: Technical Audit & Comparison

This document provides a deep-dive technical analysis of the "Peter" and "10k" series traders. Following the standard comparative auditing format, we analyze the structural edges, regime adaptability, and backtest-validated performance.

## 📊 Backtest Results Breakdown

Verified results using `backtest_cli.py` on Round 1 historical data.

| Category | Filename | Day -2 | Day -1 | Day 0 | **Total PnL** |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **PnL King** | `trader_peter_aggressive.py` | 90,885.00 | 92,362.00 | 89,595.00 | **$272,842.00** |
| **Most Stable** | `trader_peter_safe.py` | 82,705.00 | 85,270.00 | 78,089.00 | **$246,064.00** |
| **Trend Mastery** | `trader_peter_trend.py` | 84,115.00 | 84,651.00 | 40,736.00 | **$209,502.00** |

### Product PnL Attribution (Cumulative)
- **`trader_peter_aggressive.py`**: Dominant in Pepper Root due to greedy volume intake.
- **`trader_peter_safe.py`**: Stable across both products; best resilience against adverse selection.
- **`trader_peter_trend.py`**: Strong Osmium performance in low-volatility regimes; uses dynamic EMA.

---

## 🔬 Technical Strategy Evolution

| Version | Edge Hypothesis | Structural Logic | Risk Profile |
| :--- | :--- | :--- | :--- |
| **Aggressive** | Market Stationarity | `Price = 10000 + Tape`. Assumes any deviation from 10k is a mean-reverting opportunity unless confirmed by tape volume. | **High**: Can be run over by structural shifts. |
| **Safe** | Liquidity Provision | Fixed anchors + wide margins. Profit comes from the bid-ask spread. | **Low**: High survival, lower yield. |
| **Trend Adaptive** | EMA Momentum | `Price = EMA(20) + Tape`. Assumes the mean itself drifts and tracks it with exponential weighting. | **Medium**: Prone to whipsaws in fast mean-reversion. |

---

## 🕵️ Technical Grandmaster Deep-Dive

### 1. The "Anchor" vs. "Drift" Dilemma (Osmium Analysis)
In Technical Analysis, the choice of a "Fair Value" is everything. 
- **`trader_peter_aggressive`** treats Osmium as a **Rangebound Oscillator** (Wyckoff Accumulation/Distribution around 10k). It snipes anything >2.5 ticks from the anchor. This worked best because Osmium is effectively stationary around 10,000.
- **`trader_peter_trend`** treats it as a **Trending Asset** using a 20-tick EMA. In Day 0, Osmium's volatility caused the EMA to lag, leading to poor entry timing. 

### 2. Volume Profile & Tape Confirmation
- **`trader_peter_aggressive`** uses a `tape_adj` with a cap of 2.5. This effectively acts as a "Momentum Burst" filter. 
- **`trader_peter_aggressive`**'s outperformance in Pepper Root is due to its **Greedy Taker** logic, ensuring it stays long during upward drifts by accepting any ask price that meets its regression criteria.

---

## ⚔️ Pairwise Comparison: `Aggressive` vs `Trend`

| Factor | `trader_peter_aggressive.py` | `trader_peter_trend.py` | Technical Impact |
| :--- | :--- | :--- | :--- |
| **Fair Price Basis** | Hard Anchor (10000) | EMA(20) | `Aggressive` wins on mean-reverting assets. |
| **Execution Alpha** | Aggressive Pennying | Skewed MM | `Aggressive` stays at the front of the queue. |
| **Tape Sensitivity** | High (0.15 coeff) | Medium (0.10 coeff) | `Aggressive` catches breakouts faster. |
| **PnL Efficiency** | **1.30x** vs Trend | 1.00x | Aggressive taker logic is currently the dominant factor. |

---

## 🚩 Risk Audit (Technical Warnings)
> [!WARNING]
> **Overfitting to Stationarity**: `trader_peter_aggressive` is heavily optimized for a market that returns to 10,000. If the market fundamentally shifts its benchmark, this bot will fight the trend.

---

## 🏛️ Recommendation & Next Steps

1. **Current Production Selection**: **`trader_peter_aggressive.py`** is the winner for pure volume/PnL.
2. **Hybrid Opportunity**: Integrate **Panic Exits** from `peter_v1` into the `aggressive` logic for risk protection.
3. **Indicator Optimization**: Shorten the EMA window (e.g., EMA 8) for `trader_peter_trend.py` to reduce lag in fast regimes.

*Historical traders have been moved to `ROUND 1/archive/old_peter` to prevent version confusion.*
