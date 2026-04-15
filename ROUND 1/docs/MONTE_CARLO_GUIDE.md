# 🎲 Monte Carlo Backtester for Round 1

Extended version of the [chrispyroberts/imc-prosperity-4](https://github.com/chrispyroberts/imc-prosperity-4) repo to support **Round 1 products** (Osmium & Pepper Root).

> Unlike historical replay (which tests one fixed path), Monte Carlo generates **1000s of alternative market scenarios** to estimate what happens to your strategy across all possible futures.

---

## Quick Start

### 1. Quick Test (1 minute)
```powershell
cd "ROUND 1"
python monte_carlo_cli.py trader_peter4.py --quick
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

### 2. Standard Analysis (3 minutes)
```powershell
python monte_carlo_cli.py trader_peter4.py
```
(Default = 100 sessions × 1000 steps each)

### 3. Deep Analysis (several minutes)
```powershell
python monte_carlo_cli.py trader_peter3.py --heavy
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
- Mean reversion to ~5000
- Bots quote ±6.5-8 ticks around fair
- Higher volatility than Osmium

### Order Book Generation
Each timestamp:
1. Bot 1 places outer symmetric wall (±10 ticks for Osmium, ±8 for Pepper)
2. Bot 2 places inner symmetric wall (±8 ticks for Osmium, ±6.5 for Pepper)
3. Bot 3 sometimes posts one-sided inside quote
4. Your trader's orders are inserted and matched
5. Simulated market-taker flow

### Trade Flow
- Trades happen after your orders with ~30% probability per step
- Trade sizes sampled from logged distributions
- Sides are random (50/50)

---

## CLI Presets

| Preset | Sessions | Steps | Use Case |
|--------|----------|-------|----------|
| `--quick` | 50 | 500 | Quick smoke test |
| (default) | 100 | 1000 | Recommended |
| `--heavy` | 1000 | 1000 | Comprehensive analysis |
| `--ultra` | 5000 | 1000 | Expert validation |

### Custom Parameters
```powershell
# Override specific values
python monte_carlo_cli.py trader_peter4.py --sessions 250 --steps 2000

# Combine with presets (overrides take priority)
python monte_carlo_cli.py trader_peter4.py --heavy --steps 1500
```

---

## Understanding the Output

### Main Statistics

**Mean P&L**: Average outcome across all sessions
```
Mean:          $1,234.56
```
- This is your expected return per session
- Target for Round 1: **$1,000 - $3,000 mean**

**Std Dev**: Volatility of outcomes
```
Std Dev:       $285.43
```
- Measures consistency
- Lower is better (more predictable)
- Good ratio: Std Dev < 30% of Mean

**Percentiles**: Distribution of outcomes
```
5th:           $512.00    (5% of sessions worse than this)
50th:          $1,210.00  (median/middle)
95th:          $1,892.00  (95% of sessions better than this)
```
- 90% confidence interval = [5th, 95th]
- Range shows best-case and worst-case scenarios

### Risk Metrics

**Drawdown**: Maximum loss during a session
```
Mean DD:       $-150.25
Worst DD:      $-725.00
```
- Drawdown < 3% of Mean P&L is healthy
- If worst DD > Mean P&L: Strategy is risky

**Win Rate**: % of sessions with positive P&L
```
Win Rate:      67.3%
```
- For high-frequency trading: 50%+ is reasonable
- For longer-term: 40%+ is acceptable
- Below 30%: Revisit your logic

---

## Example: Comparing Strategies

### Test multiple traders
```powershell
# Quick comparison
foreach ($trader in @("trader_peter2", "trader_peter3", "trader_peter4")) {
    python monte_carlo_cli.py "ROUND 1/$trader.py" --quick
}
```

### Results table
```
Trader          Mean PnL    Std Dev    P5        P95       Win Rate
peter2          $892.34     $234.23    $350      $1,450    62%
peter3          $1,123.45   $289.34    $450      $1,700    65%
peter4          $1,456.78   $312.45    $500      $2,100    68%  ← Best
```

**Analysis**: peter4 has highest mean, slightly higher std dev, but better range.

---

## Interpreting Results With Red Flags

### 🚩 Mean P&L is negative or < $500
```
Mean:          $-234.56
```
- Your algorithm loses money on average
- **Action**: Fix your fair price logic or market making spreads

### 🚩 Std Dev > 50% of Mean
```
Mean:          $1,234.56
Std Dev:       $687.23    ← Too high!
```
- Your strategy is *inconsistent*
- Some scenarios you win big, others you lose big
- **Action**: Reduce aggressiveness, tighten stops

### 🚩 Worst Drawdown > Mean P&L
```
Mean:          $1,234.56
Worst DD:      $-2,100.00  ← Worse than average profit!
```
- One bad session wipes out 2+ good sessions
- **Action**: Reduce position limits or add risk controls

### 🚩 Win Rate < 40%
```
Win Rate:      32.1%
```
- Most sessions lose money
- You might be on wrong side of the market
- **Action**: Check tape reading logic

### ✅ Healthy Profile
```
Mean:          $1,500.00
Std Dev:       $250.00    (16% of mean - great!)
P5:            $850
P95:           $2,100
Win Rate:      68%
```
- Consistent profits
- Reasonable range
- Safe to upload

---

## File Outputs

### `trader_peter4_mc_results.csv`
Detailed per-session results:
```
session_id,final_pnl,max_drawdown,max_position_osmium,max_position_pepper,trades_osmium,trades_pepper
0,"1523.45","-287.10","45","38","87","92"
1,"1289.67","-156.23","42","41","85","89"
...
```

Use this to:
- Identify outlier sessions (best/worst)
- Spot patterns (do bad sessions cluster?)
- Analyze position sizing

---

## Advanced Usage

### Run with Specific Seed (Reproducibility)
```powershell
python monte_carlo_cli.py trader_peter4.py --seed 12345
```

Same seed = Same random path = Same results (useful for debugging)

### Save to Custom Output
```powershell
python monte_carlo_cli.py trader_peter4.py --output results/peter4_analysis.csv
```

### Batch Testing
```powershell
# Test all trader versions
$traders = Get-ChildItem "ROUND 1/trader_*.py" | Select-Object -ExpandProperty Name
foreach ($t in $traders) {
    python monte_carlo_cli.py "ROUND 1/$t" --heavy --output "results/$($t -replace '.py', '_mc.csv')"
}
```

---

## Comparison: Historical Replay vs Monte Carlo

### Historical Replay (Standard Backtest)
```
What: Run strategy on 1 actual path (the historical data)
Pros: Exact, uses real data
Cons: Only shows 1 possible outcome
Result: "I made $2,450 on this data"
```

### Monte Carlo Simulation
```
What: Run strategy on 1000 synthetic paths (calibrated to market)
Pros: Shows distribution of outcomes, robustness testing
Cons: Synthetic (not exactly real), calibration assumptions
Result: "I expect to make $1,200 ± $300 (90% confidence)"
```

### Best Practice
```
1. Historical replay → Get initial P&L estimate
2. Monte Carlo → Validate robustness
3. Paper trade → Test real execution
4. Live → Deploy
```

---

## Troubleshooting

### "No module named 'datamodel'"
Make sure you're running from within the `ROUND 1/` directory or adjust the import.

### Simulation is very slow
Use `--quick` preset first, then scale up to `--heavy` after validation.

### Results are nonsensical (all losses)
Your trader might have bugs. Check:
- Fair price calculation
- Order submission logic
- Position tracking

### Results vary wildly between runs
This is expected (Monte Carlo introduces randomness). Use same `--seed` to reproduce.

---

## Next Steps

1. **Get baseline**: Run `--quick` on your best trader
2. **Compare versions**: Test all variations with `--quick`
3. **Deep dive**: Run `--heavy` on top candidate
4. **Validate**: Compare MC results against historical backtest
5. **Upload**: When Monte Carlo shows consistent profits

---

## References

- Original repo: https://github.com/chrispyroberts/imc-prosperity-4
- IMC Prosperity docs: https://imc-prosperity.com
- Monte Carlo methods: [Wikipedia](https://en.wikipedia.org/wiki/Monte_Carlo_method)
