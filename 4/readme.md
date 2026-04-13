# IMC Prosperity 4: Tutorial Round Workspace

Welcome to your algorithmic trading command center! This workspace is designed for a complete beginner to analyze, backtest, and deploy a trading bot for the IMC Prosperity 4 competition.

## 🚀 Quick Start Checklist

Follow these steps to get your first bot ready for upload:

### 📥 1. Setup Data
- **Drop your Excel/CSV files**: Take the historical price and trade data you downloaded from the IMC website and place them into the `data_capsule/` folder.
- The dashboard will automatically detect these files if they are named correctly (e.g., `prices_round_0_day_-1.csv`).

### 🔍 2. Analysis
- **Open the Dashboard**: Run `streamlit run dashboard.py` in your terminal.
- **Click 'Analyze'**: Navigate to the **One-Click Forge** tab and click the **Run Auto-Analysis** button.
- **Don't worry about the math**: The bot will automatically calculate things like the 10,000 "Fair Value" mark for Emeralds so you don't have to!

### 🛠️ 3. The 'Forge'
- **Configure in Sidebar**: Use the sliders in the sidebar to set your "Backpack size" (Position Limits) and "Aggressiveness" (Target Spread). 
- **⚠️ Safety First**: Keep your limits between 15-18 to avoid disqualification!
- **Click 'Forge Final'**: Back in the **One-Click Forge** tab, click the **Forge Final Trader.py** button. This creates a clean, standalone file with all your settings baked in.

### 📤 4. Upload
- **Download**: Click the download button that appears after forging.
- **Upload**: Take the `trader.py` file and drag it into the **A.R.I.A. Uplink** on the IMC competition site.

---

## 🧠 Trading Strategies Explained

- **Mean Reversion (The 'Rubber Band')**: This strategy assumes prices always snap back to the middle. It buys when the price is low and sells when it's high. Perfect for stable assets like Emeralds.
- **Market Making**: This strategy places both a Buy and a Sell order at the same time. You profit from the "Spread" (the tiny gap between what people are paying and what they are asking for).

## 📁 Folder Structure

- `trader.py`: Your actual trading bot (the "brain").
- `dashboard.py`: Your control center and backtester.
- `data_capsule/`: Where you stash your market data.
- `config.json`: Where the dashboard saves your slider settings.
