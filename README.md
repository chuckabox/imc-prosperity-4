# IMC Prosperity 4

## Setup
```bash
pip install -r requirements-dashboard.txt
```

## Dashboard
```bash
python -m streamlit run tools/dashboard.py
```
Open the **Rust Backtester** tab to see leaderboards and best/safest trader analysis.

## Docs

- Visualizer: `docs/VISUALIZER_GUIDE.md`
- Backtesting: `docs/BACKTEST_GUIDE.md`

## Common Commands

```bash
python tools/runbacktest.py "ROUND 4/traders/ken/table.py" --products summary
python tools/parse_runs.py
python tools/backtest_results_manager.py
```

---

## Backtest a Trader (Round 3)

The project now uses the **GeyzsoN/prosperity_rust_backtester** engine for high-fidelity Round 3 simulation (Options, Greek-aware hedging, etc.).

**Single trader run**:
```bash
python tools/run_rust_backtester.py --use-wsl
```
*Defaults to `ROUND 3/traders/ken/we_found_vfe_gold2.py` and `ROUND 3/data_capsule`.*

**Custom run**:
```bash
python tools/run_rust_backtester.py --trader "ROUND 3/traders/ken/we_found_vfe_gold2.py" --use-wsl
```

**Compare multiple traders**:
```bash
python tools/compare_rust.py "ROUND 3/traders/ken/we_found_vfe_gold.py" "ROUND 3/traders/ken/we_found_vfe_gold2.py"
```

**Flags:**
- `--use-wsl` — Recommended for Windows (runs Rust + cargo inside WSL Ubuntu).
- `--no-build` — Skip recompiling Rust (much faster for iterating on trader logic).
- `--dataset "ROUND 3/data_capsule"` — Change the data source.
- `--day 1` — Run a single day (0, 1, or 2) instead of the full 3-day capsule.

Results are saved to `external/prosperity_rust_backtester/runs/` and are automatically picked up by the **Dashboard**.

---

## Structure
```
ROUND 3/        Round 3 traders, analysis docs, and data capsule
tools/          Backtester launchers, dashboard, and analysis scripts
external/       Rust engine source (GeyzsoN fork)
```
