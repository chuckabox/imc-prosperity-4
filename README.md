# 📈 IMC Prosperity 4 Trading Suite

Unified workspace for strategy development, high-performance backtesting, and analysis.

---

## ⚡ Quick Start

### 1. Setup Environment
```powershell
pip install -r requirements-dashboard.txt
```

### 2. Launch Console
```powershell
python -m streamlit run "tools/dashboard.py"
```

---

## 🦀 Rust Backtesting

The **Rust Backtester** is our primary high-performance engine for Round 2. It automatically aggregates 3-day results for easy comparison.

### 🔥 Run a Backtest
To run a specific trader (e.g., Suvin v2) against the Round 2 data:
```powershell
python "tools/run_rust_backtester.py" --use-wsl --trader "ROUND 2/traders/suvin/trader_stable_suvin_v2.py" --dataset "ROUND 2/data_capsule"
```
*Note: Use `--use-wsl` if you are on Windows and don't have Visual Studio Build Tools installed.*

### ⚔️ Compare Multiple Traders
Run multiple versions side-by-side:
```powershell
python "tools/compare_rust.py" --use-wsl "ROUND 2/traders/trader1.py" "ROUND 2/traders/trader2.py"
```

---

## 📊 Analysis Dashboard

Open the **"🦀 Rust Backtester"** tab in the dashboard to:
1. **Compare Traders**: Select multiple runs to see a side-by-side leaderboard.
2. **View Winners**: Automatically identifies the best-performing script across all days.
3. **Deep Dive**: Inspect PnL by product and trade execution details.

---

## 📂 Project Structure

- **`ROUND 2/`**: Active traders and training data.
- **`tools/`**: Entry points for Dashboard and Backtester wrappers.
- **`external/prosperity_rust_backtester/`**: The core backtesting engine.
- **`runs/`**: (Generated) Output logs and metrics from your tests.

---
