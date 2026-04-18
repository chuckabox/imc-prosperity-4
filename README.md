# 📈 IMC Prosperity 4 Trading Suite

A unified repository for strategy development, backtesting, and analysis, currently optimized for **Round 2**.

---

## 🏗️ Project Layout

- **`ROUND 2/`**: Active development workspace containing traders, configurations, and results.
- **`ROUND 1/`**: Legacy data and strategies for reference.
- **`tools/dashboard.py`**: The main entry point for the visual console.
- **`tools/impl/`**: Core implementation of the Unified Dashboard.
- **`tools/manual_optimiser/`**: Advanced multi-scenario optimization for Round 2 manual challenges.
- **`archive/`**: Retired rounds, legacy backtesters, and secondary tools.
- **`assets/`**: Visual assets and documentation images.

---

## 🚀 Getting Started

### 1. Launch the Operations Console

Run the unified dashboard to visualize prices, execute backtests, and run the manual optimizer:

```bash
streamlit run "tools/dashboard.py"
```

_Note: The dashboard now defaults to **Round 2** but allows switching rounds via the sidebar._

### 2. Run Robust Backtests (CLI)

Test your traders against all available historical days, real-world data, and synthetic scenarios:

```bash
# Using the unified backtester (Consolidated results go to ROUND 2/results/robust)
python tools/robust_backtester.py ROUND 2/traders/your_trader.py --quick
```

---

## 🛡️ Manual Challenge Strategy (Round 2)

The **Manual Optimizer** (integrated into the dashboard) helps compute the optimal allocation of your 50,000 XIRECs budget across Research, Scale, and Speed.

### Visual Reference

![Manual Strategy Recommendations](assets/image.png)
![Scenario Analysis Overlay](assets/image-1.png)

### Current Recommendation

- **Target Allocation**: `x=15` (Research), `y=43` (Scale), `z=42` (Speed)
- **Expected Net PnL**: ~170k - 220k XIRECs.
- **Strategic Insight**:
  - Research & Scale converge predictably near `x=15`, `y=45`.
  - **Speed (z)** is the deciding factor. Values between 37–50 are optimal. Bidding too low introduces tail risk; bidding too high (e.g., `z=71`) burns budget without significant rank gain if competitors are aggressive.
  - This allocation clears the **200k target** in every plausible competitor model (Beta-lazy, Bimodal, Exponential).

---

## 🛠️ Contributing / New Rounds

1. Use the templates in `archive/ROUND_TEMPLATE` if starting fresh.
2. Add data under `ROUND X/data_capsule/` and strategies under `ROUND X/traders/`.
3. The Unified Dashboard will automatically detect the new `ROUND X` folder.
