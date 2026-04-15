# 🏛️ IMC Prosperity 4: High-Performance Round 1 Suite

![Status](https://img.shields.io/badge/Status-Leaderboard_Ready-success)
![PnL](https://img.shields.io/badge/Backtest_PnL-%24272k_total-blue)
![Architecture](https://img.shields.io/badge/Algo-Categorical_Traders_|_Monte_Carlo_Validated-orange)

Welcome to the **Round 1 Production Suite**. This repository contains a production-grade algorithmic trading suite and high-fidelity backtesting tools optimized for **Ash-coated Osmium** and **Intarian Pepper Root**.

---

## 🚦 Quick Start Guide

### 📂 1. Select Your Strategy
We have categorized our top performers into three distinct trading archetypes located in `ROUND 1/traders/peter/`:
- **`trader_peter_aggressive.py`** ($272k): The PnL King. Greedily takes liquidity for maximum volume capture.
- **`trader_peter_safe.py`** ($246k): The Robust MM. Uses hard anchors and wide margins for risk-averse growth.
- **`trader_peter_trend.py`** ($209k): The Adaptive Core. Uses 20-period EMA to dynamically track fair price drifts.

### 🧪 2. Validate Locally
Before uploading to the portal, run a full verification cycle across historical and synthetic markets.

#### **A. Historical Backtest (The Truth)**
Check performance against the exact Round 1 tape.
- **Run command:** `python "ROUND 1/tools/backtest_cli.py" "ROUND 1/traders/peter/trader_peter_aggressive.py"`

#### **B. Monte Carlo Simulation (The Robustness)**
Test against 100+ synthetic market paths to ensure your strategy doesn't "blow up" in edge cases.
- **Run command:** `python "ROUND 1/tools/monte_carlo_cli.py" "ROUND 1/traders/peter/trader_peter_aggressive.py" --quick`

#### **C. Visual Debugging (The Microstructure)**
Watch your fills happen in real-time on the order book.
- **Run command:** `streamlit run "ROUND 1/tools/dashboard.py"`

---

## 📂 Documentation Index

Detailed audits and technical guides are located in the `ROUND 1/docs/` directory:

| Document | Purpose |
| :--- | :--- |
| [**peter_comparisons.md**](ROUND%201/docs/peter_comparisons.md) | Technical deep-dive and pairwise comparison of the categorical traders. |
| [**XIREC_ESTIMATION.md**](ROUND%201/docs/XIREC_ESTIMATION.md) | Consolidated profit estimation combining Manual Auction and Algo results. |
| [**TESTING_TOOLKIT.md**](ROUND%201/docs/TESTING_TOOLKIT.md) | One-page cheat sheet for all backtesting commands. |
| [**BACKTESTING_GUIDE.md**](ROUND%201/docs/BACKTESTING_GUIDE.md) | Comprehensive walkthrough of the 4 different backtesting engines. |
| [**STRATEGY_ANALYSIS.md**](ROUND%201/docs/STRATEGY_ANALYSIS.md) | Repository-wide audit explaining successes and failures of legacy models. |

---

## 📂 Project Structure

```bash
├── ROUND 1/
│   ├── traders/peter/         # Categorical Production Traders (Best 3)
│   ├── tools/                 # Backtesting, MC, and Dashboard engines
│   ├── config/                # Datamodel and environment config
│   ├── data_capsule/          # Raw Round 1 Price/Trade CSVs
│   ├── docs/                  # Strategy Audits and Technical Guides
│   └── archive/old_peter/     # Legacy and failed experiments
├── tutorial/                  # Historical data from previous rounds
└── README.md                  # Main documentation (You are here)
```

---

## ⚖️ Portfolio Estimation
Our current project target is **200,000 XIRECs**. Following our latest audit:
- **Manual Auction (Arbitrage)**: 376,700 XIRECs (Risk-Free)
- **Algorithmic (10k Series)**: 272,842 shells (Local High-Fidelity)
- **Total Combined**: **~649,542 Estimated XIRECs**.

*“In Prosperity, edge is found at the intersection of speed and safety.”*
