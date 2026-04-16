# ROUND 1 AI Context

## Quick Facts
- **Project**: IMC Prosperity 4 - Round 1 Trading Strategy
- **Products**: ASH_COATED_OSMIUM, INTARIAN_PEPPER_ROOT
- **Current Status**: Monte Carlo backtester implemented and working
- **Entry Point**: `tools/monte_carlo_cli.py`

## Folder Structure

```
ROUND 1/
├── tools/               # Backtesting & simulation engines
│   ├── monte_carlo_cli.py        (main entry point)
│   ├── monte_carlo_backtester.py (core simulation logic)
│   ├── backtest_cli.py           (CLI backtester)
│   ├── backtest_ultra.py         (Rust integration)
│   └── dashboard.py              (visualization)
│
├── config/              # Configuration & data models
│   ├── config.json
│   └── datamodel.py
│
├── traders/             # Active trader implementations
│   ├── trader.py        (baseline)
│   ├── trader_10k.py    (anchored fair value)
│   └── trader_adin.py   (alternative strategy)
│
├── data/                # Raw data & results
│   ├── data_capsule/    (tick data: prices, trades)
│   └── *_mc_results.csv (simulation results)
│
├── docs/                # Documentation
│   ├── MONTE_CARLO_GUIDE.md
│   ├── TESTING_TOOLKIT.md
│   └── STRATEGY_ANALYSIS.md
│
├── archive/             # Old implementations & cache
│   ├── old_peter/
│   ├── scratch/
│   └── __pycache__/
│
└── ai-context/          # This folder (AI reference)
```

## Current Tools

### Monte Carlo CLI (Main)
```bash
cd "ROUND 1"
python tools/monte_carlo_cli.py traders/trader_10k.py --quick
```

**Presets:**
- `--quick`: 50 sessions × 500 steps (fast)
- `--default`: 100 sessions × 1000 steps (balanced)
- `--heavy`: 1000 sessions × 1000 steps (thorough)
- `--ultra`: 5000 sessions × 1000 steps (expert)

**Output:**
- PnL distribution (mean, median, percentiles)
- Drawdown stats (peak-to-trough)
- Win rate
- CSV results in `data/`

### Real Backtest CLI
```bash
python tools/backtest_cli.py traders/trader_10k.py
```
Runs on historical tick data. Outputs final PnL and position summary.

## Key Imports
- `tools.monte_carlo_backtester` — MarketSimulator, MonteCarloBacktester
- `tools.backtest_cli` — real historical backtester
- `config.datamodel` — Listing, OrderDepth, TradingState, Trade, Order

## Trader Template

All traders in `traders/` follow this interface:
```python
class Trader:
    def __init__(self):
        self.limits = {'ASH_COATED_OSMIUM': 80, 'INTARIAN_PEPPER_ROOT': 80}
        self.history = {}

    def run(self, state: TradingState):
        # Return (orders_dict, conversions, trader_data_str)
        return {}, 0, json.dumps(self.history)
```

## Known Issues & Fixes
- **OrderDepth initialization**: Must call `OrderDepth()` then assign `.buy_orders`, `.sell_orders`
- **TradingState**: Requires `listings`, `observations`, `traderData` arguments
- **Monte Carlo**: Drawdown = peak-to-trough (not min value)
- **Unicode on Windows**: Replace emoji with [!] or [OK]

## Last Run
- Command: `python tools/monte_carlo_cli.py traders/trader_10k.py --quick`
- Result: Mean PnL = -$471, StdDev = $649, Win Rate = 26%
- Output File: `data/trader_10k_mc_results.csv`

## Next Steps (Suggestions)
1. Tune fair value models in trader implementations
2. Test on `--default` (100 sessions) for statistical confidence
3. Run real backtest: `python tools/backtest_cli.py traders/trader_10k.py`
4. Archive successful traders in `archive/winners/`
5. Compare results: Monte Carlo vs. Real Backtest

---
*File maintained by AI. Read this each session for context.*
