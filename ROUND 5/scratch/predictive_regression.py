import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression, LassoCV
from sklearn.preprocessing import StandardScaler

# Load data
prices_df = pd.read_csv('ROUND 5/data_capsule/prices_round_5_day_2.csv', sep=';')
pivoted = prices_df.pivot(index='timestamp', columns='product', values='mid_price').fillna(method='ffill')

# Calculate returns
returns = pivoted.pct_change().dropna()

# Features for each product i:
# 1. Own past returns (Lag 1)
# 2. Other products past returns (Lag 1)
# 3. Spread (relative to mid)
# 4. Volume (implied from trades? or just use order book depth)
# Since we don't have volume easily pivoted, let's start with Returns and Spread.

spreads = prices_df.copy()
spreads['spread'] = spreads['ask_price_1'] - spreads['bid_price_1']
spread_pivoted = spreads.pivot(index='timestamp', columns='product', values='spread').fillna(method='ffill')

# Target: Next period return for a specific product
# Features: Current returns of all products + Current spreads of all products

X = pd.concat([returns, spread_pivoted.shift(1).dropna()], axis=1).dropna()
y = returns.shift(-1).dropna()

# Align indices
common_idx = X.index.intersection(y.index)
X = X.loc[common_idx]
y = y.loc[common_idx]

print(f"Analyzing {len(common_idx)} periods...")

# Focus on a few interesting products (e.g. SNACKPACK_VANILLA, PEBBLES_XL)
targets = ["PEBBLES_XL", "SNACKPACK_VANILLA", "GALAXY_SOUNDS_BLACK_HOLES"]

for target in targets:
    print(f"\n--- Predicting next return for {target} ---")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    lasso = LassoCV(cv=5, random_state=42).fit(X_scaled, y[target])
    score = lasso.score(X_scaled, y[target])
    print(f"Lasso R^2 Score: {score:.6f}")
    
    if score > 0.01: # Even a tiny edge is valuable for direction
        coefs = pd.Series(lasso.coef_, index=X.columns)
        important = coefs[abs(coefs) > 1e-5].sort_values(ascending=False)
        print("Top features:")
        print(important.head(10))
        
        # Check directional accuracy
        pred = lasso.predict(X_scaled)
        correct_direction = np.sign(pred) == np.sign(y[target])
        accuracy = correct_direction.mean()
        print(f"Directional Accuracy: {accuracy:.2%} (Chance is 50%)")
