# 🚀 Round 1 Testing Toolkit

Quick reference for all available testing and simulation tools.

---

## One-Command Quick Start

```powershell
cd "ROUND 1"
python backtest_cli.py trader_peter4.py
```

→ Get instant P&L estimate in 1-2 seconds

---

## All Available Tools

### 📊 Historical Backtesting

| Tool | Command | Time | Purpose |
|------|---------|------|---------|
| **CLI** | `python backtest_cli.py trader_peter4.py` | 1-2s | Quick PnL check |
| **Ultra** | `python backtest_ultra.py` | 1-2m | Deep audit, compare all traders |
| **Visual** | `streamlit run dashboard.py` | 5m | Interactive chart debugging |
| **Rust** | `wsl bash -c "..."` | 30s | Ultra-fast performance testing |

### 🎲 Monte Carlo Simulation (NEW!)

| Preset | Command | Time | Use Case |
|--------|---------|------|----------|
| **Quick** | `python monte_carlo_cli.py trader_peter4.py --quick` | 30s | Smoke test |
| **Default** | `python monte_carlo_cli.py trader_peter4.py` | 2-3m | Standard validation |
| **Heavy** | `python monte_carlo_cli.py trader_peter4.py --heavy` | 15-20m | Deep robustness |

---

## When to Use Each

### 🔴 Just Made a Code Change?
```powershell
python backtest_cli.py trader_peter4.py
```
- Instant feedback
- Catches obvious bugs
- **Tip**: If PnL went down, you know which change broke it

### 🟡 Deciding Between Versions?
```powershell
python backtest_ultra.py
```
- Compares ALL traders side-by-side
- Reads `STRATEGY_AUDIT.md` after
- **Tip**: Look for best mean, lowest drawdown, highest win rate

### 🟢 Ready to Upload?
```powershell
cd ROUND 1

# 1. Sanity check
python backtest_cli.py trader_peter4.py

# 2. Quick Monte Carlo (robustness)
python monte_carlo_cli.py trader_peter4.py --quick

# 3. Visual validation
streamlit run dashboard.py

# 4. Final confidence check
python monte_carlo_cli.py trader_peter4.py --heavy
```

---

## Monte Carlo Output Files

After running Monte Carlo, you'll get:
- **Terminal output**: Summary statistics and interpretation
- **`trader_peter4_mc_results.csv`**: Detailed per-session results

Outputs are automatically saved in the `ROUND 1/` folder.

---

## Understanding Results

### ✅ Good Signals
```
Mean P&L:      $1,200+  (aim for 1-3k per session)
Std Dev:       < 30% of mean
Win Rate:      > 60%
95% CI:        Mostly positive
```

### 🚩 Red Flags
```
Mean P&L:      < $500
Std Dev:       > 50% of mean
Win Rate:      < 40%
Worst DD:      > Total PnL
```

---

## File Guide

| File | Purpose |
|------|---------|
| `backtest_cli.py` | Fast P&L check |
| `backtest_ultra.py` | Deep audit |
| `dashboard.py` | Visual debugging |
| `monte_carlo_backtester.py` | MC simulation engine |
| `monte_carlo_cli.py` | MC command-line interface |
| `STRATEGY_AUDIT.md` | Generated comparison report |

---

## Documentation

- **Full backtesting guide**: See `../BACKTESTING_GUIDE.md`
- **Monte Carlo details**: See `MONTE_CARLO_GUIDE.md`
- **Patterns reference**: See `.agents/skills/technical-analysis/references/patterns.md`

---

## Troubleshooting

### "ImportError: No module named 'datamodel'"
→ Make sure you're in the `ROUND 1/` directorywhen running

### Monte Carlo results look wrong
→ Check your trader for bugs (run `backtest_cli.py` first)

### Too slow on my machine
→ Start with `--quick` preset instead of `--heavy`

### Want reproducible results?
→ Use `--seed 12345` flag with `monte_carlo_cli.py`

---

**Goal**: Get to 1000+ mean P&L on Monte Carlo before uploading! 🎯
