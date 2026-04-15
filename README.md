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
Validate your strategy locally before using up your portal upload slots. High-fidelity results are essential for reaching the 10k PnL rank.

#### **Option A: The Strategy Audit (Highest Accuracy)**
Use this tool to compare multiple versions of your trader or benchmark against standard models.
- **Run command:** `python "ROUND 1/backtest_ultra.py"`
- **Interpret Results:**
    - **Total PnL:** Your target for Round 1 should be **7k-10k+** total.
    - **Takers vs Makers:** Top strategies usually have a balanced profile. If your **Taker** count is 0, you're missing out on fast price moves. If it's too high, you might be losing to "Adverse Selection" (Toxic fills).
    - **Max Drawdown:** Compare this in the `STRATEGY_AUDIT.md`. A healthy strategy for Round 1 should handle a drawdown of ~500 shells.

#### **Option B: The Rapid CLI**
Best for quick PnL checks after small code changes to a specific file.
- **Run command:** `python "ROUND 1/backtest_cli.py" "ROUND 1/trader_peter2.py"`
- **Review:** Quick-fire output of Day -2, -1, and 0 performance.

#### **Option C: The Visual Dashboard**
Best for seeing charts, inventory, and fair value overlays.
1. **Start:** `streamlit run "ROUND 1/dashboard.py"`.
2. **Simulate:** Switch to the **Visual Backtester** tab to see exactly *where* you were filled.

#### **Option D: The Rust Backtester (Highest Performance)**
For ultra-fast backtesting with minimal setup. Requires WSL2 on Windows.
- **Setup (one-time):**
  - Install Rust in WSL2: `curl https://sh.rustup.rs -sSf | sh`
  - Install Python dev libraries: `sudo apt update && sudo apt install -y python3-dev`
- **Run command:** From PowerShell: `wsl bash -c "cd /mnt/c/Users/peter/Desktop/IMC/prosperity_rust_backtester && source ~/.cargo/env && cargo run -- --trader /mnt/c/Users/peter/Desktop/IMC/imc-prosperity-4/ROUND\ 1/trader_peter2_2.py --products summary"`
- **Features:**
  - Lightning-fast execution (seconds vs minutes)
  - Accurate simulation of all round data
  - Supports custom traders with full path
  - Outputs detailed PnL breakdown by product and day

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
├── prosperity_rust_backtester/ # High-performance Rust engine
└── README.md                  # Main documentation
```

---

*“In Prosperity, edge is found at the intersection of speed and safety.”*
