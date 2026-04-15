# Round 1 Strategy Analysis

Generated: 2026-04-15  
Backtester: `backtest_cli.py` (aggressive take + 50% passive fill simulation)  
Products: `ASH_COATED_OSMIUM` | `INTARIAN_PEPPER_ROOT` | Position limit: 80 each

---

## 🏛️ Portfolio Organization (Current)

Following the categorical audit, strategies have been organized by series:

### 1. The Peter Series (`traders/peter/`)
Optimized for the Round 1 historical stationarity.
- **`trader_peter_aggressive.py`** ($272k): Highest PnL; greedy taker logic.
- **`trader_peter_safe.py`** ($246k): Robust mm; anchored fair values.
- **`trader_peter_trend.py`** ($209k): EMA-driven; adaptive fair pricing.

### 2. The Ken Series (`traders/ken/`)
High-fidelity institutional-grade market making.
- **`trader_ken_v6_1.py`** ($301k): current absolute PnL champion.
- **`ken_pepper_original.py`**: aggressive trend accumulation.

### 3. The Adin Series (`traders/adin/`)
- **`trader_adin.py`** ($243k): Bias-long trend opportunist.

---

## 📊 Historical Backtest Baseline

| Trader | Day -2 | Day -1 | Day 0 | **Total** |
|---|---|---|---|---|
| **`traders/ken/trader_ken_v6_1.py`** | 100,480 | 101,713 | 99,288 | **301,481** 🏆 |
| **`traders/peter/trader_peter_aggressive.py`** | 90,885 | 92,362 | 89,595 | **272,842** 🥈 |
| **`traders/adin/trader_adin.py`** | 81,480 | 80,938 | 81,086 | **243,504** |
| `trader.py` (production baseline) | 97,348 | 18,764 | -63,903 | 52,210 ⚠️ |

---

## 🔬 Critical Findings

### 1. Osmium Anchor + Capped Tape Is the Most Reliable Base
Across tested families, strategies anchored around `10000` with capped tape adjustment are consistently robust. The Ken series improves on this with a `mid_pull` drift factor.

### 2. The Production Bot (`trader.py`) Is Broken for Day 0
The production bot loses **-63,903** on Day 0. The root cause is **miscalibrated regression weights** (inherited from Starfruit) and a fixed Pepper anchor that failed when the market moved to 12k.

### 3. Aggression vs. Safety
- **Peter Aggressive** wins on volume by taking all asks in trends.
- **Ken v6.1** wins on precision by splitting passive orders across two levels, capturing more of the queue without concentration risk.

---

## 🏛️ Individual Category Analysis

### Peter Series: `trader_peter_aggressive.py`
- **PnL: $272,842**
- Correct `10000` Osmium anchor. Correct Pepper regression weights. 
- **The differentiator**: It pennys the queue at `best_bid + 1`, ensuring it is at the front for every passive fill.

### Ken Series: `trader_ken_v6_1.py`
- **PnL: $301,481**
- **The differentiator**: Uses a "split-passive" size strategy (62% at top of book, 38% deeper). This maximizes queue priority while protecting against full-order toxicity.

---

## 🏺 Legacy Archive
Detailed notes on failed experiments (`peter11`, `regime detection`, `uncapped tape`) are preserved in `archive/old_peter/`.
- **Key lesson**: Never hardcode an exit anchor for a trending asset (Pepper).
- **Key lesson**: Regression without periodic refitting is more dangerous than a simple moving average.
