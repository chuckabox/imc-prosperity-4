# 🏛️ IMC Prosperity 4: High-Performance Round 1 Suite

![Status](https://img.shields.io/badge/Status-Leaderboard_Ready-success)
![PnL](https://img.shields.io/badge/Backtest_PnL-%2473k_total-blue)
![Architecture](https://img.shields.io/badge/Algo-Anchor_MM_|_Dynamic_EMA-orange)

Welcome to the **Round 1 Production Suite**. This repository contains a production-grade algorithmic trading bot, a high-fidelity local backtester, and an interactive Streamlit dashboard optimized for **Ash-coated Osmium** and **Intarian Pepper Root**.

---

## 🚦 Quick Start Guide

Follow these steps to get your Round 1 bot ready for upload:

### 📥 1. Setup Data
- **Drop your CSV files**: Ensure your historical data is in the `ROUND 1/data_capsule/` folder.
- The system expects filenames like `prices_round_1_day_0.csv`.

### 🔍 2. Analysis & Forging
1. **Open the Dashboard**: Run `streamlit run "ROUND 1/dashboard.py"`.
2. **Auto-Analyze**: Navigate to the **One-Click Forge** tab and click **Run Auto-Analysis**. This calculates the optimal anchor for Osmium (~10,000) based on provided data.
3. **Configure**: Use the sidebar sliders to set your position limits (20 max) and aggressiveness.
4. **Forge**: Click the **Forge Final Trader.py** button to generate a tuned version of your script.

### 🧪 3. Local Backtesting
Validate your strategy locally before using up your portal upload slots.

#### **Option A: The Rapid CLI (Fastest)**
Best for quick PnL checks after code changes.
- **Run command:** `python "ROUND 1/backtest_cli.py"`
- **Review:** Optimized strategy targets ~$25k per test day.

#### **Option B: The Visual Dashboard**
Best for seeing charts, inventory, and fair value overlays.
1. **Start:** `streamlit run "ROUND 1/dashboard.py"`.
2. **Simulate:** Switch to the **Visual Backtester** tab.

### 📤 4. Upload to IMC
Take the final `ROUND 1/trader.py` file and upload it to the **A.R.I.A. Uplink** on the IMC portal.

---

## 🛠️ Suite Components

*   **Leaderboard Trader (`ROUND 1/trader.py`)**: HFT bot utilizing anchored mean-reversion for Osmium and dynamic EMA tracking for Pepper Root. Includes persistent state via `traderData`.
*   **Operations Console (`ROUND 1/dashboard.py`)**: Interactive Streamlit app for real-time visualization and parameter forging.
*   **Backtesting Engine**: High-fidelity simulation that models both Aggressive Takes and Passive Maker fills using historical trade tapes.

---

## 📂 Project Structure

```bash
├── ROUND 1/
│   ├── trader.py              # Active production strategy
│   ├── dashboard.py           # Streamlit control center
│   ├── backtest_cli.py        # High-fidelity CLI simulator
│   ├── data_capsule/          # CSV prices and trades
│   └── config.json            # Dashboard settings
├── tutorial/                  # Archived previous rounds (0/4/3)
├── backtester_rust/           # High-performance engine
└── README.md                  # Main documentation
```

---

*“In Prosperity, edge is found at the intersection of speed and safety.”*
