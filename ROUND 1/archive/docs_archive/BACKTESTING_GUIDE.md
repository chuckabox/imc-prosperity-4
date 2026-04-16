# 🧪 Backtesting & Monte Carlo Simulation Guide

A complete walkthrough of testing your trading strategies locally **without uploading to IMC Prosperity**.

---

## Table of Contents
1. [What is Backtesting?](#what-is-backtesting)
2. [Your Backtesting Tools](#your-backtesting-tools)
3. [What is Monte Carlo Simulation?](#what-is-monte-carlo-simulation)
4. [How to Use Each Tool](#how-to-use-each-tool)
5. [Interpreting Results](#interpreting-results)
6. [Complete Workflow](#complete-workflow)

---

## What is Backtesting?

**Backtesting** = Running your trading strategy against historical data to see how it would have performed in the past.

### Why?
- ✅ Test code without risking anything
- ✅ Compare different strategies quickly
- ✅ Find bugs before uploading
- ✅ Understand P&L breakdown (what trades made/lost money?)
- ✅ Estimate position sizing and drawdown

### What You Get:
- **Total P&L**: How much profit/loss you made
- **Daily breakdown**: Performance each day
- **Trade count**: How many times you bought/sold
- **Max drawdown**: Worst losing streak
- **Win rate**: % of profitable trades

---

## Your Backtesting Tools

You have **4 different backtesting engines** with different tradeoffs:

| Tool | Speed | Accuracy | Best For |
|------|-------|----------|----------|
| **backtest_cli.py** | ⚡ Fast | ★★★★★ | Quick PnL checks after code changes |
| **backtest_ultra.py** | 🐢 Slow | ★★★★★ | Deep analysis, strategy audit, comparing versions |
| **dashboard.py** | ⚡ Medium | ★★★★★ | Visual debugging, seeing where you got filled |
| **Rust Backtester** | 🚀 Ultra-fast | ★★★★★ | Large batch runs, parameter sweeps |

---

## What is Monte Carlo Simulation?

**Monte Carlo** = Generate synthetic market scenarios based on your historical trade data to estimate robustness.

### Why?
- Real historical data has only ONE path the market took
- Monte Carlo creates thousands of alternative paths ("what if?")
- Shows: "If these trades happened in a different order, what would my P&L be?"
- Estimates: What's my realistic worst case? Best case? Median?

### What You Get:
- **Confidence intervals**: "95% likely I'll make $X to $Y"
- **Drawdown distribution**: "Worst drawdown could be $Z"
- **Robustness check**: "Does my strategy work only in 1 specific market path?"
- **Risk metrics**: VaR, expected shortfall

### Example:
```
Historical trades: [+100, -50, +200, -30, +150]

Monte Carlo (1000 simulations):
- Sim 1: [+200, +100, -50, +150, -30] → Total: +370
- Sim 2: [-30, +150, +200, -50, +100] → Total: +370
- Sim 3: [+100, -50, -30, +200, +150] → Total: +370
...

Result: Total is same (+370) but ORDER of losses matters!
- If big loss comes early: drawdown is $80
- If big loss comes late: drawdown is $520
```

---

## How to Use Each Tool

### 1. **backtest_cli.py** - Quick Daily PnL Check ⚡

**Best for:** After you make small code changes, quickly verify it still works.

#### Command:
```powershell
python "ROUND 1/backtest_cli.py" "ROUND 1/trader_peter4.py"
```

#### Output:
```
=== Round 1, Day -2 ===
PnL: 1234 (Osmium: +800, Pepper: +434)
Fills: 45 buy, 32 sell

=== Round 1, Day -1 ===
PnL: 567 (Osmium: +340, Pepper: +227)
Fills: 38 buy, 28 sell

=== Round 1, Day 0 ===
PnL: 891 (Osmium: +520, Pepper: +371)
Fills: 41 buy, 35 sell

=== TOTAL ===
Total PnL: 2692
```

#### What to check:
- ✅ Is PnL positive? (If negative, something broke)
- ✅ Is osmium profitable? (If not, your fair price is wrong)
- ✅ Is pepper profitable? (If not, your regression signal is weak)
- ✅ Are you getting fills? (0 fills = too aggressive with pricing)

---

### 2. **backtest_ultra.py** - Deep Strategy Audit 🔍

**Best for:** Comprehensive analysis, comparing multiple strategies, finding why profits changed.

#### Command:
```powershell
python "ROUND 1/backtest_ultra.py"
```

#### What it does:
1. Runs ALL trader files in `ROUND 1/` folder
2. Compares them side-by-side
3. Generates `STRATEGY_AUDIT.md` with detailed breakdown

#### Output File: `STRATEGY_AUDIT.md`
Creates a markdown report with:
- Side-by-side PnL comparison
- Win/loss analysis
- Position histograms
- Daily performance charts (ASCII)
- Taker vs Maker breakdown

#### Example AUDIT output:
```
STRATEGY_AUDIT
===============

| Trader | Total PnL | Osmium | Pepper | Max DD | Win Rate |
|--------|-----------|--------|--------|--------|----------|
| peter3 | 2,450     | 1,800  | 650    | -280   | 62%      |
| peter4 | 2,890     | 2,100  | 790    | -320   | 64%      |
| peter2 | 1,950     | 1,400  | 550    | -450   | 58%      |

```

#### What to check:
- ✅ Which version has highest total PnL?
- ✅ Which has lowest max drawdown?
- ✅ Did osmium or pepper drive the profits?
- ✅ Which version has best risk-adjusted returns?

---

### 3. **dashboard.py** - Visual Backtester 📊

**Best for:** Visual debugging - seeing EXACTLY where you got filled on the order book.

#### Command:
```powershell
streamlit run "ROUND 1/dashboard.py"
```

#### Features:
1. **Visual Backtester Tab**: Live price chart with your orders
2. **Inventory Chart**: See your position over time
3. **Fair Value Overlay**: See where your algorithm thought prices should be
4. **Order Book Snapshot**: See depth at each timestamp

#### How to use:
1. Run command above
2. Browser opens to `http://localhost:8501`
3. Go to **Visual Backtester** tab
4. Select trader and day
5. Play the timeline slider to watch fills happen live
6. Hover over prices to see exact trades

#### What to debug:
- ✅ Are you buying at the right prices?
- ✅ Are you catching up-moves early (good fills)?
- ✅ Are you getting trapped in bad positions?
- ✅ Is your fair value too conservative/aggressive?

---

### 4. **Rust Backtester** - Ultra-Performance 🚀

**Best for:** Running 1000s of parameter combinations, exhaustive testing.

#### Setup (one-time):
```powershell
# Install Rust in WSL2
wsl bash -c "curl https://sh.rustup.rs -sSf | sh"
wsl bash -c "sudo apt update && sudo apt install -y python3-dev"
```

#### Command:
```powershell
wsl bash -c "cd /mnt/c/Users/peter/Desktop/IMC/prosperity_rust_backtester && source ~/.cargo/env && cargo run --release -- --trader /mnt/c/Users/peter/Desktop/IMC/imc-prosperity-4/ROUND\ 1/trader_peter4.py --products summary"
```

#### What it returns:
- TPS (Transactions per second)
- Total PnL
- Per-product breakdown
- JSON output for post-processing

#### Use case:
```powershell
# Test multiple traders in rapid succession
foreach ($trader in @("peter2", "peter3", "peter4", "peter2_2_1")) {
    wsl bash -c "cd /mnt/c/.../prosperity_rust_backtester && ... --trader .../trader_$trader.py"
}
```

---

## 5. **monte_carlo_cli.py** - Synthetic Market Monte Carlo 🎲

**Best for:** Robustness testing - run your strategy on 100s of synthetic market paths.

### What It Does
Generates synthetic order books and trade flows calibrated to Round 1 market structure, then runs your trader multiple times to estimate P&L distribution across different possible market scenarios.

Unlike historical replay (1 fixed path), Monte Carlo asks: **"What if the market unfolded differently?"**

### Commands

#### Quick test (1 minute):
```powershell
cd "ROUND 1"
python monte_carlo_cli.py trader_peter4.py --quick
```

#### Standard analysis (3 minutes, recommended):
```powershell
python monte_carlo_cli.py trader_peter4.py
```
(Default = 100 sessions × 1000 steps each)

#### Deep analysis (several minutes):
```powershell
python monte_carlo_cli.py trader_peter3.py --heavy
```
(Heavy = 1000 sessions × 1000 steps)

#### Custom parameters:
```powershell
python monte_carlo_cli.py trader_peter4.py --sessions 250 --steps 2000
```

### Output Example
```
Monte Carlo Backtester for trader_peter4.py
============================================================
Preset:    DEFAULT
Sessions:  100
Steps:     1000 per session
Total:     100,000 simulation steps
============================================================

PnL Distribution:
  Mean:          $1,234.56
  Median:        $1,210.00
  Std Dev:       $285.43

Percentiles:
  5th:           $512.00
  25th:          $980.00
  75th:          $1,510.00
  95th:          $1,892.00

Range:
  Min:           $-450.00
  Max:           $2,890.00

Drawdown Statistics:
  Mean DD:       $-150.25
  Worst DD:      $-725.00

Win Rate:        67.3%
```

### What It Simulates

**Fair Values (Calibrated from Round 1 data)**
- **Osmium**: Anchored at 10,000 with tape-driven adjustments
- **Pepper Root**: Random walk with mean reversion to 5000

**Order Book Dynamics**
- Symmetric bot walls at varying distances from fair
- Optional one-sided inside quotes
- Realistic spread patterns per product

**Trade Flow**
- Market-taker activity (~30% chance per step)
- Trade sizes from logged distributions
- Both buy and sell flow

### Presets

| Preset | Sessions | Steps | Use Case |
|--------|----------|-------|----------|
| `--quick` | 50 | 500 | ~30s smoke test |
| (default) | 100 | 1000 | ~2-3min analysis |
| `--heavy` | 1000 | 1000 | ~15min deep dive |
| `--ultra` | 5000 | 1000 | ~1min per full test |

### Interpreting Monte Carlo Results

**Good Profile** (Upload candidate):
```
Mean P&L:     $1,200-3000 per session
Std Dev:      < 30% of mean
5th/95th:     Wide confidence interval, still positive
Win Rate:     > 60%
```

**Red Flag - High Risk**:
```
Mean P&L:     < $500
Std Dev:      > 50% of mean (inconsistent)
Worst DD:     > Mean P&L (single bad path wipes gains)
95% confident range includes large losses
```

### Comparing Strategies

```powershell
# Quick comparison across all traders
foreach ($t in @("peter2", "peter3", "peter4")) {
    python monte_carlo_cli.py "trader_$t.py" --quick
}
```

See which has best mean P&L, lowest std dev, and widest right tail (95th percentile).

### For detailed guidance
→ See [MONTE_CARLO_GUIDE.md](MONTE_CARLO_GUIDE.md) for comprehensive documentation

---

## Interpreting Results

### Understanding Backtest Metrics

#### **P&L (Profit & Loss)**
- Total money made or lost
- Example: `+2,450` = Made 2,450 shells
- **Good target for Round 1**: 7,000 - 10,000+ shells total

#### **Max Drawdown**
- Worst losing streak from peak to trough
- Example: `DD = -450` = Lost 450 shells at worst moment
- **Formula**: `(Lowest Point - Peak) / Peak * 100%`
- **Rule of thumb**: Drawdown should be <5-10% of total P&L

#### **Win Rate**
- % of trades that make money
- Example: `64%` = 64 out of 100 trades profitable
- **Not everything**: You can have 40% win rate but still profit (bigger wins than losses)

#### **Taker vs Maker**
- **Taker**: You take existing orders (you pay the spread) - active trading
- **Maker**: You place passive orders (you collect the spread) - patient trading
- **Good ratio**: More makers than takers = you're collecting spreads, not chasing

#### **Osmium vs Pepper Split**
- Where did your profits come from?
- If only osmium profits: Pepper algorithm is weak
- If balanced: Both strategies working well

---

## Complete Workflow

### **Before Each Upload to IMC:**

```
1. Code Change
   ↓
2. Quick Check: python "ROUND 1/backtest_cli.py" "ROUND 1/trader_peter4.py"
   ├─ If negative: Fix code bugs
   ├─ If low PnL: Check your fair price logic
   ├─ If positive: Continue
   ↓
3. Deep Dive: python "ROUND 1/backtest_ultra.py"
   ├─ Compare against other versions
   ├─ Check if this is improvement
   ├─ Read STRATEGY_AUDIT.md
   ↓
4. Visual Debug: streamlit run "ROUND 1/dashboard.py"
   ├─ Watch fills happen
   ├─ Check for edge cases (market opens/closes)
   ├─ Verify fair price is reasonable
   ↓
5. Monte Carlo Robustness: cd "ROUND 1" && python monte_carlo_cli.py trader_peter4.py
   ├─ Estimate confidence interval
   ├─ Check worst-case scenario
   ├─ Verify strategy is robust across different market paths
   ↓
6. Decision:
   ├─ If all metrics good → Upload
   └─ If weak spot found → Back to step 1
```

### **Recommended Testing Sequence**

1. **Make code change**
2. **5 seconds**: `backtest_cli.py` quick check
3. **3 minutes**: `monte_carlo_cli.py --quick` (fast robustness check)
4. **5 minutes**: `backtest_ultra.py` (compare all versions)
5. **10 minutes**: `dashboard.py` (visual validation)
6. **5-15 minutes**: `monte_carlo_cli.py --heavy` (if looking promising)
7. **Decision**: Upload if metrics are solid?

**Total time**: 30 minutes to go from code change to deployment-ready

---

## Red Flags (Don't Upload If You See These)

🚩 **P&L is negative** → Your algorithm loses money
🚩 **Max drawdown > 2000** → Too risky for 10k target
🚩 **Zero fills** → Your prices are too extreme
🚩 **Only makers, zero takers** → Missing fast price moves
🚩 **Pepper only profitable, osmium losing** → Osmium fair price is wrong
🚩 **Huge difference between backtest and Monte Carlo worst case** → Not robust

---

## Example: Running a Complete Test Session

```powershell
# Terminal 1: Quick check
python "ROUND 1/backtest_cli.py" "ROUND 1/trader_peter4.py"

# If good, then:
python "ROUND 1/backtest_ultra.py"

# Compare against audit file
cat STRATEGY_AUDIT.md

# Terminal 2: Visual debugging (parallel)
streamlit run "ROUND 1/dashboard.py"
# Open http://localhost:8501 in browser

# Terminal 3: Monte Carlo (after visual check)
python monte_carlo.py > monte_carlo_results.txt

# Review all results
code monte_carlo_results.txt
code STRATEGY_AUDIT.md
```

---

## Key Takeaways

✅ **Always backtest locally before uploading**
✅ **Use CLI for quick checks after code changes**
✅ **Use Ultra for deep analysis and comparisons**
✅ **Use dashboard for visual debugging edge cases**
✅ **Use Rust for batch parameter testing**
✅ **Use Monte Carlo to estimate robustness**
✅ **Target: 7k-10k total P&L for leaderboard competition**

Good luck! 🚀

