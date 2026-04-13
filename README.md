# 🏛️ IMC Prosperity 4: High-Performance HFT Trading Suite

![Status](https://img.shields.io/badge/Status-Leaderboard_Ready-success)
![PnL](https://img.shields.io/badge/Best_PnL-%241%2C556.86_per_day-blue)
![Architecture](https://img.shields.io/badge/Algo-Polynomial_Drift_|_Volatility_Z--Scores-orange)

Welcome to the **Prosperity 4 Master Suite**. This repository contains a production-grade algorithmic trading bot, a high-fidelity local backtester, and an interactive Streamlit dashboard designed to dominate the IMC Prosperity competition.

---

## 🚦 Quick Start Guide

Follow these steps to get your first bot ready for upload:

### 📥 1. Setup Data
- **Drop your CSV files**: Place the historical price and trade data you downloaded from the IMC website into the `4/data_capsule/` folder.
- The dashboard and backtesters will automatically detect files named like `prices_round_0_day_-1.csv`.

### 🔍 2. Analysis & Forging
1. **Open the Dashboard**: Run `streamlit run 4/dashboard.py`.
2. **Auto-Analyze**: Navigate to the **One-Click Forge** tab and click **Run Auto-Analysis**. This calculates the optimal "Fair Value" (e.g., 10,000 for Emeralds).
3. **Configure**: Use the sidebar sliders to set your position limits (recommend 15-20) and aggressiveness.
4. **Forge**: Click the **Forge Final Trader.py** button to save your settings into the main trading script.

### 🧪 3. Local Backtesting (Test before you upload!)
Avoid the queue and test your strategies instantly.

#### **Option A: The Rapid CLI (Fastest)**
Best for quick PnL checks after code changes.
- **Run command:** `python 4/backtest_cli.py`
- **Review:** Check the `Final PnL` at the bottom.

#### **Option B: The Visual Dashboard (Best for Analysis)**
Best for seeing charts, inventory, and fair value overlays.
1. **Start:** `streamlit run 4/dashboard.py`.
2. **Simulate:** Switch to the **Backtester** tab and click **"Run Full Simulation"**.

#### **Option C: High-Speed Rust Engine (Advanced)**
For processing millions of ticks or large grid searches.
1. Navigate to `backtester_rust/`.
2. Use **WSL2** to run `make backtest`.

### 📤 4. Upload to IMC
Once happy with your backtest results, take the `4/trader.py` file and upload it to the **A.R.I.A. Uplink** on the IMC portal.

---

## 🛠️ Suite Components

*   **Alpha-Focused Trader (`4/trader.py`)**: A multi-asset HFT bot utilizing 2nd-order local polynomial fitting for drift estimation and adaptive volatility-aware Z-score filters.
*   **Visual Dashboard (`4/dashboard.py`)**: Interactive Streamlit app for real-time strategy visualization and parameter forging.
*   **Backtesting Suite**: CLI and Dashboard simulation engine that accurately models both Aggressive Takes and Passive fills.

---

## 🧠 Trading Strategies Explained

- **Mean Reversion (The 'Rubber Band')**: Assumes prices always snap back to a central value. We buy when the price is low and sell when it's high. Perfect for stable assets like **Emeralds**.
- **Market Making**: Placing both Buy and Sell orders simultaneously to profit from the "Spread" (the gap between buyers and sellers).
- **Drift Prediction**: Using math (polynomial fitting) to guess where the price is headed in the next few ticks. Used for **Tomatoes**.
- **Dynamic Squashing**: Automatically adjusting prices to reduce inventory when we are too "long" or too "short," keeping us safe from big market swings.

---

## 📂 Project Structure

```bash
├── 4/
│   ├── trader.py              # Active 'Golden' strategy script
│   ├── dashboard.py           # Streamlit control center
│   ├── backtest_cli.py        # High-fidelity CLI simulator
│   ├── data_capsule/          # Place your CSV data here
│   ├── config.json            # Saved dashboard configurations
│   └── STRATEGY_LOG.md        # Detailed history of PnL and logic shifts
├── backtester_rust/           # High-performance Rust engine
└── README.md                  # Main documentation
```

---

*“In Prosperity, edge is found at the intersection of speed and safety.”*
