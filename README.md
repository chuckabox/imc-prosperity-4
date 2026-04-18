# 📈 IMC Prosperity 4 Trading Suite

A unified repository for strategy development, backtesting, and analysis, currently optimized for **Round 2**.

---

## 🏗️ Project Layout

- **`ROUND 2/`**: Active development workspace containing traders, configurations, and results.
- **`ROUND 1/`**: Legacy data and strategies for reference.
- **`tools/dashboard.py`**: The main entry point for the visual console.
- **`tools/impl/`**: Core implementation of the Unified Dashboard.
- **`requirements-dashboard.txt`**: Python dependencies for the Streamlit dashboard (install once from the repo root).
- **`ROUND 2/tools/robust_backtester.py`**: Round 2 multi-scenario backtester (IMC + real-world + scenarios under `ROUND 2/data_capsule/`).
- **`tools/manual_optimiser/`**: Advanced multi-scenario optimization for Round 2 manual challenges.
- **`archive/`**: Retired rounds, legacy backtesters, and secondary tools.
- **`assets/`**: Visual assets and documentation images.

---

## 🚀 Getting Started

### 1. Launch the Operations Console

Install dashboard dependencies once (Streamlit, Altair, Pandas, NumPy; no Matplotlib required):

```bash
pip install -r requirements-dashboard.txt
```

Run the unified dashboard to visualize prices, execute backtests, and run the manual optimizer:

```bash
streamlit run "tools/dashboard.py"
```

OR

```bash
python -m streamlit run tools/dashboard.py
```

_Note: The dashboard now defaults to **Round 2** but allows switching rounds via the sidebar._

### 2. Run Robust Backtests (CLI)

You can use either the **Round 2 capsule backtester** (single `data_capsule` tree) or the **unified repo-level backtester** (multiple `ROUND N` folders).

#### Round 2 backtester (`ROUND 2/tools/robust_backtester.py`)

Runs CSVs under `ROUND 2/data_capsule/` (IMC days, `real_world/normalized`, `scenarios`). Results are written to `ROUND 2/results/robust/`.

```bash
# Full run (all IMC days in the capsule + real-world + scenarios)
python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/your_trader.py"

# Only Round 2 IMC historical files (three days: day -1, 0, 1)
python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/your_trader.py" --r2 --imc-only

# Only Round 1 IMC files in this capsule (if present), still with real + scenarios unless --imc-only
python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/your_trader.py" --r1

# Both rounds’ IMC filenames, IMC only
python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/your_trader.py" --r1 --r2 --imc-only

# Faster smoke test (subset of real-world + one scenario per regime)
python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/your_trader.py" --quick
```

Flags: `--imc-only`, `--scenarios-only`, `--quick`, `--r1`, `--r2`, `--tag NAME`. With no `--r1`/`--r2`, every `prices_round_*_day_*.csv` in the capsule is included. `--r1` / `--r2` filter **only** those IMC files by round number in the filename.

#### Unified backtester (`tools/robust_backtester.py`)

Aggregates datasets from `ROUND 1`, `ROUND 2`, etc. Results go to `ROUND 2/results/robust/`.

```bash
python tools/robust_backtester.py "ROUND 2/traders/your_trader.py" --quick

# Shorthand for rounds (same as --rounds 1 or --rounds 2)
python tools/robust_backtester.py "ROUND 2/traders/your_trader.py" --r2 --imc

# Explicit rounds
python tools/robust_backtester.py "ROUND 2/traders/your_trader.py" --rounds 1 2 --imc
```

Unified flags: `--rounds`, `--r1`, `--r2`, `--quick`, `--imc`, `--real`, `--scen`, `--tag`.

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
