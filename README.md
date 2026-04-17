# 🏛️ IMC Prosperity 4 Trading Suite

![Status](https://img.shields.io/badge/Status-Round_2_Active-success)
![Total PnL](https://img.shields.io/badge/R1_PnL-%24272k-blue)

This repository contains high-fidelity backtesting tools and production strategies for the IMC Prosperity 4 challenge.

---

## 📂 Project Structure

- **[ROUND 1](./ROUND%201)**: Completed tasks for Ash-coated Osmium and Intarian Pepper Root.
- **[ROUND 2](./ROUND%202)**: Current development round.
- **[tools](./ROUND%202/tools)**: Standard backtesting and analysis tools (shared codebase).
- **[imc-prosperity-4-backtester](./imc-prosperity-4-backtester)**: Core backtesting engine.

---

## 🚀 Round 2 Quick Start

Follow these steps to begin development for Round 2.

### 1️⃣ Setup Strategy
Place your trade logic in `ROUND 2/traders/`.
- **Baseline:** Start by copying the best performer from Round 1 or use the template in `ROUND 2/traders/trader.py`.

### 2️⃣ Run Backtests
Use the robust backtester to validate signals and risk management.
- **Run:** `python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/<your_file>.py" --quick`

### 3️⃣ Launch Visual Dashboard
Analyze fills, positions, and PnL distributions.
- **Run:** `streamlit run "ROUND 2/tools/dashboard.py"`

---

## 🏆 Round 1 Retrospective
- **Champion Bot:** `ROUND 1/traders/ken/trader_robust_ken_v2.py`
- **Total PnL (Backtest):** $272,000
- **Key Products:** Osmium, Pepper Root.

---

_“In Prosperity, edge is found at the intersection of speed and safety.”_

