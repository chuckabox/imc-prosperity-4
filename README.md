# 📈 IMC Prosperity 4 Trading Suite

A unified repository for strategy development, backtesting, and analysis, currently optimized for **Round 2**.

---

## 🏗️ Project Layout

- **`ROUND 2/`**: Active development workspace containing traders, configurations, and results.
- **`ROUND 1/`**: Legacy data and strategies for reference.
- **`tools/dashboard.py`**: The main entry point for the visual console.
- **`tools/run_rust_backtester.py`**: One command to build and run the vendored Rust backtester against Round 2 capsule data (supports `--use-wsl` on Windows).
- **`tools/impl/`**: Core implementation of the Unified Dashboard.
- **`requirements-dashboard.txt`**: Python dependencies for the Streamlit dashboard (install once from the repo root).
- **`external/prosperity_rust_backtester/`**: Vendored [Rust backtester](https://github.com/GeyzsoN/prosperity_rust_backtester) (primary high-performance engine).
- **`run_backtest.ps1`**: Optional PowerShell helper that shells into WSL (edit the hard-coded binary path inside the script for your machine).
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

With dependencies installed, `tools/impl/unified_dashboard.py` is the implementation behind `tools/dashboard.py`.

The UI defaults to **Round 2**; use the sidebar to switch rounds. The Robust Analysis tab reads CSVs from `ROUND N/results/robust/` (IMC-focused metrics by default).

### 3. Rust backtester (primary engine)

**Do I need to install something?** Only for compiling and running **Rust** on Windows without WSL. The **Python dashboard** does **not** need Visual Studio. On Windows you either install **[Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)** once (MSVC linker), or use **`python tools/run_rust_backtester.py --use-wsl`** after installing Rust + `build-essential` inside WSL/Ubuntu.

The crate lives in **`external/prosperity_rust_backtester/`**. More paths and WSL notes: **`external/README_IMC_PROSPERITY.md`**.

#### Windows / WSL

You need **`cargo`** on the machine that actually compiles (Windows host or Linux in WSL).

- **WSL2:** Often the least painful path on Windows.
- **Native Windows:** Default Rust target is MSVC; if you see `linker link.exe not found`, use **`--use-wsl`** with the Python launcher (Rust must be installed inside Ubuntu).

#### Launchers

**A. One-command Python launcher (recommended):**

```powershell
python "tools/run_rust_backtester.py"
```

Builds the release binary if needed, then runs against **Round 2** capsule data by default.

```powershell
python "tools/run_rust_backtester.py" --use-wsl
python "tools/run_rust_backtester.py" --trader "ROUND 2/traders/peter/trader_peter_v2001.py" --dataset "ROUND 2/data_capsule"
python "tools/run_rust_backtester.py" -- --day -1
python "tools/run_rust_backtester.py" --no-build
```

**B. PowerShell wrapper (`run_backtest.ps1`):**

```powershell
.\run_backtest.ps1 -dataset tutorial
```

Opens WSL and runs `rust_backtester`; **edit the script** so the path to `rust_backtester` matches your clone (it ships with an example path).

Upstream engine: [GeyzsoN/prosperity_rust_backtester](https://github.com/GeyzsoN/prosperity_rust_backtester).

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

### 5. Python multi-session harness

This branch focuses on the **Rust** engine above. Legacy **Python** `robust_backtester.py` scripts may still appear in **`archive/`** or older docs; the dashboard **Robust Analysis** tab plots whatever result CSVs you have under `ROUND N/results/robust/`.

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
