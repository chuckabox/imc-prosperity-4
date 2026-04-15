# 🎲 Monte Carlo Backtester for Round 1

Extended version of the [chrispyroberts/imc-prosperity-4](https://github.com/chrispyroberts/imc-prosperity-4) repo to support **Round 1 products** (Osmium & Pepper Root).

> Unlike historical replay (which tests one fixed path), Monte Carlo generates **1000s of alternative market scenarios** to estimate what happens to your strategy across all possible futures.

---

## Quick Start

### 1. Quick Test (30 seconds)
```powershell
# Set PYTHONPATH first
$env:PYTHONPATH = "ROUND 1\config;ROUND 1\traders;ROUND 1\traders\peter;ROUND 1\tools"
python "ROUND 1/tools/monte_carlo_cli.py" "ROUND 1/traders/peter/trader_peter_aggressive.py" --quick
```

Output:
```
PnL Distribution:
  Mean:          $1,234.56
  Median:        $1,210.00
  Std Dev:       $285.43
Percentiles:
  5th:           $  512.00
  95th:          $1,892.00
Win Rate:        67.3%
```

### 2. Standard Analysis (2-3 minutes)
```powershell
python "ROUND 1/tools/monte_carlo_cli.py" "ROUND 1/traders/peter/trader_peter_aggressive.py"
```
(Default = 100 sessions × 1000 steps each)

### 3. Deep Analysis (15-20 minutes)
```powershell
python "ROUND 1/tools/monte_carlo_cli.py" "ROUND 1/traders/ken/trader_ken_v6_1.py" --heavy
```
(Heavy = 1000 sessions × 1000 steps = 1M simulation steps)

---

## What's Being Simulated

### Fair Value Models (Calibrated from Round 1)

**ASH_COATED_OSMIUM:**
- Anchored at ~10,000
- Random tape adjustments modeled as AR(1) process
- Bots quote ±8-10 ticks around fair

**INTARIAN_PEPPER_ROOT:**
- Zero-drift random walk (like a price process)
- Mean reversion to ~5000 (Note: Historical Pepper Root trades 10k-12k; simulator uses 5k baseline)
- Bots quote ±6.5-8 ticks around fair

---

## Interpreting Results With Red Flags

### 🚩 Mean P&L is 0.00 or Negative
```
Mean:          $0.00
```
- **Cause**: Most likely your strategy is a **Market Maker** with tight price guards. If your `take_margin` is smaller than the simulated bot spread (8-10 ticks), you will never fill in the synthetic market.
- **Action**: For MC validation, temporarily relax price guards or use a taker strategy like `trader_peter_aggressive.py`.

### 🚩 Std Dev > 50% of Mean
- Your strategy is *inconsistent*. Some scenarios you win big, others you lose big.
- **Action**: Reduce aggressiveness, tighten stops.

### 🚩 Worst Drawdown > Mean P&L
- One bad session wipes out 2+ good sessions.
- **Action**: Reduce position limits (80 -> 20) or add risk controls.

---

## CLI Presets

| Preset | Sessions | Steps | Use Case |
|--------|----------|-------|----------|
| `--quick` | 50 | 500 | Quick smoke test |
| (default) | 100 | 1000 | Recommended |
| `--heavy` | 1000 | 1000 | Comprehensive analysis |
| `--ultra` | 5000 | 1000 | Expert validation |

---

## Key Files

- **`tools/monte_carlo_cli.py`**: The main entry point.
- **`tools/monte_carlo_backtester.py`**: The simulation engine.
- **`data/trader_name_mc_results.csv`**: Detailed per-session results for post-analysis.

---

**Goal**: Get to 1000+ mean P&L on Monte Carlo before uploading! 🎯
