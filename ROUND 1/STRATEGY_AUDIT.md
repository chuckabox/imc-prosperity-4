# 📊 Round 1 Strategy Audit: Scylla vs Charybdis

# trader_peter.py ![3,177 PNL](image.png)

# trader_peter2.py ![3,340 PNL](image-1.png)

---

## 🏁 Summary Table (Original Audit)

| Strategy         | Total PnL    | Day -2  | Day -1  | Day 0   | Profile                      |
| :--------------- | :----------- | :------ | :------ | :------ | :--------------------------- |
| **Layered MM**   | **+$49,618** | +$18.2k | +$12.9k | +$18.4k | **Aggressive / High Volume** |
| **Simple Penny** | **+$24,418** | +$2.6k  | +$16.3k | +$5.4k  | Conservative / Maker-focused |
| **Fixed Anchor** | **-$86,657** | -$21.7k | -$26.2k | -$38.6k | High Risk / Drift Victim     |

---

## 🔍 Strategy deep-dives

### 🥈 1. `trader_peter.py` ($3,177 Baseline)

- **Strategy**: **Layered Market Making**. Posts multiple layers of liquidity to capture deep volume.
- **Logic**: Uses EMA tracking for Starfruit. It is the original "Layered MM" shown in the table above that achieved the ~$50k total backtest profit.
- **Pros**: Fills more depth than single-level bots.

### 🥇 2. `trader_peter2.py` ($3,340 Optimized)

- **Strategy**: **3-Lag Regression Scalping**. This is the upgraded version of the Layered MM.
- **Logic**: Instead of a lagging EMA, it uses a **statistical linear model** ($0.34P_t + 0.32P_{t-1} + 0.33P_{t-2}$) to predict the very next price move.
- **Performance**: In local backtests, this improved the Round 1 total from **$50.1k** to **$78.1k** by significantly reducing losses during Starfruit drift.

---

## 🧪 Backtesting Methodology

The **Ultra-Backtester** (`backtest_ultra.py`) uses:

1. **Queue Modeling**: Passive fills capped at 40% of market trade volume.
2. **Priority Execution**: Aggressive Market Takes are processed before Makers.
3. **MTM Valuation**: Portfolio valued at the mid-price of the BBO.
