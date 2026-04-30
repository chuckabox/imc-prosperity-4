import pandas as pd
import numpy as np

# Load data
df = pd.read_csv('ROUND 5/data_capsule/prices_round_5_day_2.csv', sep=';')
pivoted = df.pivot(index='timestamp', columns='product', values='mid_price').ffill()

# 1. Market Index (Average Return)
returns = pivoted.pct_change()
market_return = returns.mean(axis=1)

# 2. Momentum (Signs of past 3 returns)
def get_momentum(series):
    s = np.sign(series)
    # 1 if past 3 were all positive, -1 if all negative, 0 otherwise
    mom = ((s.shift(1) == 1) & (s.shift(2) == 1) & (s.shift(3) == 1)).astype(int)
    mom -= ((s.shift(1) == -1) & (s.shift(2) == -1) & (s.shift(3) == -1)).astype(int)
    return mom

print("Analyzing Momentum and Market Correlation...")

for col in pivoted.columns:
    mom = get_momentum(returns[col])
    next_ret = returns[col].shift(-1)
    
    # Correlation with Market
    market_corr = returns[col].corr(market_return)
    
    # Accuracy of Momentum prediction
    valid = mom != 0
    if valid.sum() > 100:
        mom_accuracy = (np.sign(next_ret[valid]) == mom[valid]).mean()
        if mom_accuracy > 0.52:
            print(f"Product: {col}")
            print(f"  Market Correlation: {market_corr:.4f}")
            print(f"  3-Step Momentum Accuracy: {mom_accuracy:.2%} (N={valid.sum()})")

