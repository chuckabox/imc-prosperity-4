# 📈 IMC Prosperity 4 Trading Suite

A unified repository for strategy development, backtesting, and analysis, currently optimized for **Round 2**.

---

## 🏗️ Project Layout

- **`ROUND 2/`**: Active development workspace containing traders, configurations, and results.
- **`ROUND 1/`**: Legacy data and strategies for reference.
- **`tools/dashboard.py`**: The main entry point for the visual console.
- **`tools/run_rust_backtester.py`**: One command to build and run the vendored Rust backtester against Round 2 capsule data.
- **`tools/impl/`**: Core implementation of the Unified Dashboard.
- **`requirements-dashboard.txt`**: Python dependencies for the Streamlit dashboard (install once from the repo root).
- **`ROUND 2/tools/robust_backtester.py`**: Round 2 multi-session backtester (defaults to **IMC capsule days only** under `ROUND 2/data_capsule/`; scenarios and cached real-world CSVs are opt-in).
- **`external/prosperity_rust_backtester/`**: Vendored [Rust backtester](https://github.com/GeyzsoN/prosperity_rust_backtester) (see `external/README_IMC_PROSPERITY.md`).
- **`tools/manual_optimiser/`**: Advanced multi-scenario optimization for Round 2 manual challenges.
- **`archive/`**: Retired rounds, legacy backtesters, and secondary tools.
- **`assets/`**: Visual assets and documentation images.

---

## 🚀 Getting Started

### 1. Python environment

From the repo root (use a venv if you like):

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dashboard.txt
```

That file includes **matplotlib** (used by pandas `Styler.background_gradient` on the Robust Analysis comparison tables). If you skip reinstall after a pull, run `pip install -r requirements-dashboard.txt` again.

On PowerShell, paths that contain spaces must be quoted.

### 2. Launch the Operations Console (Streamlit)

```bash
streamlit run "tools/dashboard.py"
```

Or:

```bash
python -m streamlit run "tools/dashboard.py"
```

**Verified:** With dependencies installed, `tools/impl/unified_dashboard.py` imports cleanly and the app entrypoint is `tools/dashboard.py`.

The UI defaults to **Round 2**; use the sidebar to switch rounds. The Robust Analysis tab reads CSVs from `ROUND N/results/robust/` (IMC-focused metrics by default).

### 3. Optional: Rust CLI backtester (one command)

From the repo root this builds the vendored crate (release) if needed, then runs it against **Round 2** capsule data and the default Ken v6 trader:

```powershell
python "tools/run_rust_backtester.py"
```

Override trader or dataset, or pass extra flags to the Rust binary:

```powershell
python "tools/run_rust_backtester.py" --trader "ROUND 2/traders/trader.py" --dataset "ROUND 2/data_capsule"
python "tools/run_rust_backtester.py" -- --day -1
python "tools/run_rust_backtester.py" --no-build
```

Sources live in `external/prosperity_rust_backtester/`. You need **`cargo`** on PATH. On **Windows**, the first build needs the **MSVC linker** (Visual Studio Build Tools with “Desktop development with C++”) unless you use **WSL2**. More detail: **`external/README_IMC_PROSPERITY.md`**.

### 4. Real-world market fetcher (off by default)

`ROUND 1/tools/real_data_fetcher.py` and `ROUND 2/tools/real_data_fetcher.py` **do not** call yfinance / Alpha Vantage unless you set:

PowerShell:

```powershell
$env:IMC_PROSPERITY_ALLOW_REAL_FETCH = "1"
python "ROUND 2/tools/real_data_fetcher.py"
```

bash:

```bash
export IMC_PROSPERITY_ALLOW_REAL_FETCH=1
python "ROUND 2/tools/real_data_fetcher.py"
```

Use `python "ROUND 2/tools/real_data_fetcher.py" --list` to inspect local cache without network access.

### 5. Run robust backtests (CLI)

Use either the **Round 2 capsule backtester** (one `data_capsule`) or the **unified repo-level backtester** (several `ROUND N` folders).

#### Round 2 backtester (`ROUND 2/tools/robust_backtester.py`)

**Default:** all `prices_round_*_day_*.csv` under `ROUND 2/data_capsule/` that match the capsule — **IMC historical sessions only** (no scenarios, no `real_world/normalized` unless you opt in). Results go to `ROUND 2/results/robust/`.

```bash
# Default: all IMC days in the capsule (recommended baseline)
python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/your_trader.py"

# Only Round 2 IMC files (e.g. three days when those CSVs exist)
python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/your_trader.py" --r2

# Round 1 filenames only (if those CSVs exist in the same capsule)
python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/your_trader.py" --r1

# Both rounds’ IMC filenames in the capsule
python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/your_trader.py" --r1 --r2

# Add synthetic scenarios (still no network)
python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/your_trader.py" --with-scenarios

# Previous “everything” mix: IMC + scenarios + local real_world cache (if present)
python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/your_trader.py" --full-legacy

# Faster run when scenarios/real are enabled: subsample real + one scenario per regime
python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/your_trader.py" --full-legacy --quick
```

Flags: `--imc-only` (same as default for scripts), `--scenarios-only`, `--with-scenarios`, `--with-real-world`, `--full-legacy`, `--quick`, `--r1`, `--r2`, `--tag NAME`. With no `--r1`/`--r2`, every matching IMC price file in the capsule is included.

#### Unified backtester (`tools/robust_backtester.py`)

Aggregates IMC days from `ROUND 1`, `ROUND 2`, … (default **IMC only**). Optional `--with-scenarios`, `--with-real-world`, or `--full-legacy` match the Round 2 tool. Results go to `ROUND 2/results/robust/`.

```bash
python tools/robust_backtester.py "ROUND 2/traders/your_trader.py" --quick

python tools/robust_backtester.py "ROUND 2/traders/your_trader.py" --r2 --imc

python tools/robust_backtester.py "ROUND 2/traders/your_trader.py" --rounds 1 2 --imc

# Include scenarios across rounds (no network)
python tools/robust_backtester.py "ROUND 2/traders/your_trader.py" --rounds 2 --with-scenarios
```

Unified flags: `--rounds`, `--r1`, `--r2`, `--quick`, `--imc`, `--real`, `--scen`, `--with-scenarios`, `--with-real-world`, `--full-legacy`, `--tag`.

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
