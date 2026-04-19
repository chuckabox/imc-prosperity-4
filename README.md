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

---

## Backtest a Trader

**Single trader** (Rust + prosperity4bt):
```bash
python tools/run_rust_backtester.py --trader "ROUND 2/traders/ken/trader_ken_v6.py"
```

**Compare multiple traders**:
```bash
python tools/compare_rust.py "ROUND 2/traders/ken/trader_ken_v6.py" "ROUND 2/traders/suvin/trader_v2.py"
```

**Flags:**
- `--use-wsl` — Windows without Visual Studio Build Tools
- `--no-build` — skip recompiling Rust (faster if already built)
- `--rust-only` / `--p4bt-only` — run only one engine
- `--day 1` — single day instead of all days

Results land in `external/prosperity_rust_backtester/runs/` and appear automatically in the dashboard.

---

## Structure
```
ROUND 2/        active traders + data
tools/          backtester launchers, dashboard
external/       Rust engine source
```
