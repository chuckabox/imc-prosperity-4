# Round 1 Market Analysis: Hidden Patterns

Analysis of the historical data for Round 1 reveals distinct behaviors for the two active products. 

## 1. INTARIAN_PEPPER_ROOT (The "Safe" Trend)
As rumored, this asset is extremely steady but follows a predictable linear drift.

- **Observed Pattern**: Linear Upward Trend.
- **Quantified Drift**: Approximately **+0.1 per timestamp** (+1000 per full day cycle).
- **Behavior**: It behaves like a "hardy, slow-growing root," moving from ~10,000 to ~13,000 over the course of three days (-2, -1, 0).
- **Strategy Recommendation**: Trend-following or Mean Reversion around a moving average/linear regression line.

## 2. ASH_COATED_OSMIUM (The "Volatile" Mean Reverter)
The "unpredictability" of Osmium is actually a **high-variance mean reversion** pattern anchored around 10,000.

- **Observed Pattern**: Fast Mean Reversion with High Spread.
- **Fair Value**: Stably anchored around **10,000** (drifting slightly upwards by ~3-4 points per day).
- **Mid-Price Volatility**: Standard Deviation is approximately **5.7**, significantly higher than Tutorial AMETHYSTS, justifying the "volatile" rumor.
- **Order Book Pattern**: The bid-ask spread is remarkably wide, often ranging between **16 and 22 points**.
- **The Hidden Pattern**: Despite its wide swings, the price reverts to its mean extremely quickly. The "unpredictability" is the noise within the wide spread.
- **Strategy Recommendation**: Aggressive Market Making. The wide spread provides a significant "safety margin" for limit orders. Use a tight mean-reversion filter (Z-score > 2.0) to capture the swings while avoiding the noise.

## Position Limits
Both assets have a limit of **80 units**.
- For **PEPPER_ROOT**, use the trend to skew inventory (stay long).
- For **OSMIUM**, use the wide spread to harvest PnL via passive fills, keeping inventory close to zero.

---
*Analysis performed by Technical Analysis Grandmaster @ antigravity*
