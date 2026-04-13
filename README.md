# 🏛️ IMC Prosperity 4: High-Performance HFT Trading Suite

![Status](https://img.shields.io/badge/Status-Leaderboard_Ready-success)
![PnL](https://img.shields.io/badge/Best_PnL-%241%2C556.86_per_day-blue)
![Architecture](https://img.shields.io/badge/Algo-Polynomial_Drift_|_Volatility_Z--Scores-orange)

Welcome to the **Prosperity 4 Master Suite**. This repository contains a production-grade algorithmic trading bot, a high-fidelity local backtester, and an interactive Streamlit dashboard designed to dominate the IMC Prosperity competition.

## 🚀 Key Features

*   **Alpha-Focused Trader**: A multi-asset HFT bot utilizing 2nd-order local polynomial fitting for drift estimation and adaptive volatility-aware Z-score filters.
*   **Visual Command Center**: A Streamlit-based dashboard for real-time strategy visualization, parameter forging, and one-click backtesting.
*   **High-Fidelity Backtester**: A CLI and Dashboard simulation engine that accurately models both **Aggressive Takes** and **Passive Market-Making fills** by cross-referencing historical trade data.
*   **Proven Results**: Currently benchmarking at **$1,556.86/day** on historical Day -1 data, rivaling global rank #1 performance.

---

## 🛠️ Components

### 1. `trader.py` (The 'Golden' Engine)
The heart of the suite. It features:
- **Emerald Anchoring**: 95% confidence weighting to the 10k peg for ultra-stable returns.
- **Starfruit Drift**: Predictive trend-following for volatile assets.
- **Dynamic Inventory Squashing**: Aggressive position management to maintain neutrality.
- **Pennying Logic**: Ensuring top-of-book priority at all times.

### 2. `dashboard.py` (The Cockpit)
Run with: `streamlit run 4/dashboard.py`
- **One-Click Forge**: Automatically derive optimal parameters from historical data.
- **Visual Backtester**: View tick-by-tick PnL growth and fill logs.
- **Live Overlays**: See your bot's fair value estimates overlaid on raw market prices.

### 3. Backtesting Suite
Run CLI with: `python 4/backtest_cli.py`
- Accurate simulation of pasive fills.
- Support for multi-day historical analysis.

---

## 🚦 How to Backtest Locally (Step-by-Step)

Avoid the queue and test your strategies instantly. You have two primary ways to run backtests:

### Option A: The Rapid CLI (Fastest)
Use this for quick PnL checks after code changes.
1.  **Open your terminal** in the project root.
2.  **Run the command:**
    ```powershell
    python 4/backtest_cli.py
    ```
3.  **Review the output:** It will iterate through `Day -1` and `Day -2` data, calculating your fills and final PnL.

### Option B: The Visual Dashboard (Best for Analysis)
Use this to see trade charts, inventory levels, and price-versus-fair-value overlays.
1.  **Start the Dashboard:**
    ```powershell
    streamlit run 4/dashboard.py
    ```
2.  **Open the URL:** Streamlit will provide a link (usually `http://localhost:8501`).
3.  **Interact:**
    - Choose the **Round/Day** from the sidebar.
    - Click **"Run Backtest"** to see the PnL curve.
    - **Tweak Parameters:** Adjust limits or thresholds in the sidebar and re-run to see the impact immediately.

### Option C: The High-Speed Rust Engine (Advanced)
If you are processing millions of ticks or optimizing parameters via grid search:
1. Navigate to use WSL2 (Ubuntu): `cd backtester_rust`
2. Run with optimized speed: `make backtest`

---

## 📂 Project Structure
...

```bash
├── 4/
│   ├── trader.py              # Active 'Golden' strategy
│   ├── STRATEGY_LOG.md        # Detailed 'Alpha' evolution history
│   ├── dashboard.py           # Streamlit control center
│   ├── backtest_cli.py        # High-fidelity CLI simulator
│   ├── data_capsule/          # Historical market data (prices & trades)
│   └── versions/              # Archive of previous bot iterations
├── images/                    # Visual assets and performance charts
└── README.md                  # You are here
```

## 📈 Performance Log
Detailed breakdowns of our path from $0 to $1,500+ can be found in [**4/STRATEGY_LOG.md**](4/STRATEGY_LOG.md).

---

*“In Prosperity, edge is found at the intersection of speed and safety.”*
