# 🏛️ IMC Prosperity 4: Round 1 Trading Suite

![Status](https://img.shields.io/badge/Status-Leaderboard_Ready-success)
![PnL](https://img.shields.io/badge/Backtest_PnL-%24272k_total-blue)

Welcome to the **Round 1 Production Suite**. This repository contains high-fidelity backtesting tools and production strategies optimized for **Ash-coated Osmium** and **Intarian Pepper Root**.

---

## 🚀 Easy Start Guide

Follow these three steps to build and validate a winning strategy.

### 1️⃣ Develop Strategy
Place your trade logic in `ROUND 1/traders/`. 
- **Base Template:** Use `ken/trader_robust_ken_v2.py`. It is our current champion with the best risk-adjusted returns.

### 2️⃣ Run Robust Audit
Run this command to stress-test your strategy against **40+ market scenarios** (crashes, trends, and real historical data).
- **Run:** `python "ROUND 1/tools/robust_backtester.py" "ROUND 1/traders/ken/trader_robust_ken_v2.py" --quick`
- *This produces a `.csv` file that lets you compare this version on the leaderboard.*

### 3️⃣ Analyze in Dashboard
Launch the visual command center to see how your strategy behaves.
- **Command:** `streamlit run "ROUND 1/tools/dashboard.py"`

#### **📉 Visual Backtester**
Use this tab to **debug your fills**. It shows your orders hitting the book in real-time on historical data. Perfect for checking if your "passive" prices are actually being executed.

#### **🛡️ Robust Analysis & Leaderboard**
Use this to **compare strategies**. Check your win rate across all 40 scenarios and use the **🏆 Leaderboard** sub-tab to rank your new version against previous ones by Mean PnL and Max Drawdown.

---
*“In Prosperity, edge is found at the intersection of speed and safety.”*
