# 🚀 Round 1 Testing Toolkit

Quick reference for all available testing and simulation tools.

---

## One-Command Quick Start

```powershell
# Run from the repository root
$env:PYTHONPATH = "ROUND 1\config;ROUND 1\traders;ROUND 1\traders\peter;ROUND 1\tools"
python "ROUND 1/tools/backtest_cli.py" "ROUND 1/traders/peter/trader_peter_aggressive.py"
```

→ Get instant P&L estimate in 1-2 seconds

---

## All Available Tools

### 📊 Historical Backtesting

| Tool | Command | Time | Purpose |
|------|---------|------|---------|
| **CLI** | `python tools/backtest_cli.py trader_path.py` | 1-2s | Quick PnL check |
| **Ultra** | `python tools/backtest_ultra.py` | 1-2m | Deep audit, compare all traders |
| **Visual** | `streamlit run tools/dashboard.py` | 5m | Interactive chart debugging |

### 🎲 Monte Carlo Simulation

| Preset | Command | Time | Use Case |
|--------|---------|------|----------|
| **Quick** | `python tools/monte_carlo_cli.py trader_path.py --quick` | 30s | Smoke test |
| **Default** | `python tools/monte_carlo_cli.py trader_path.py` | 2-3m | Standard validation |
| **Heavy** | `python tools/monte_carlo_cli.py trader_path.py --heavy` | 15-20m | Deep robustness |

---

## When to Use Each

### 🔴 Just Made a Code Change?
```powershell
python "ROUND 1/tools/backtest_cli.py" "ROUND 1/traders/peter/trader_peter_aggressive.py"
```
- Instant feedback
- **Tip**: If PnL went down, you know which change broke it.

### 🟡 Deciding Between categorical champions?
```powershell
python "ROUND 1/tools/backtest_cli.py" "ROUND 1/traders/ken/trader_ken_v6_1.py"
```
- Check `overall_comparisons.md` for current benchmarks.

### 🟢 Ready to Upload?
```powershell
# 1. Sanity check
python tools/backtest_cli.py traders/peter/trader_peter_aggressive.py

# 2. Quick Monte Carlo (robustness)
python tools/monte_carlo_cli.py traders/peter/trader_peter_aggressive.py --quick

# 3. Visual validation
streamlit run tools/dashboard.py
```

---

## Organization Guide

Active traders are organized by series:
- `ROUND 1/traders/peter/` (Aggressive, Safe, Trend categories)
- `ROUND 1/traders/ken/` (Market Making excellence)
- `ROUND 1/traders/adin/` (Trend-biased accumulation)

---

## Troubleshooting

### "ImportError: No module named 'datamodel'"
→ Make sure you set `$env:PYTHONPATH = "ROUND 1\config;ROUND 1\traders;ROUND 1\traders\peter;ROUND 1\tools"`

### Monte Carlo results look wrong
→ Ensure the simulated spread in `monte_carlo_backtester.py` matches your trader's tolerance. MM strategies with tight guards may report 0.00 PnL in synthetic markets.

---

**Goal**: Get to 1000+ mean P&L on Monte Carlo before uploading! 🎯
