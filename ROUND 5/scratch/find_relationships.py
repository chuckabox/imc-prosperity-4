import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression

# Load day 2 prices
df = pd.read_csv('ROUND 5/data_capsule/prices_round_5_day_2.csv', sep=';')

# Pivot to get mid_price for each product at each timestamp
pivoted = df.pivot(index='timestamp', columns='product', values='mid_price').fillna(method='ffill')

print("Products loaded:", list(pivoted.columns))

# Let's try to find if any product is a linear combination of others
# Or let's calculate correlation matrix
corr = pivoted.corr()

# Find highest correlations (absolute value > 0.95, excluding self)
high_corr = []
for i in range(len(corr.columns)):
    for j in range(i+1, len(corr.columns)):
        if abs(corr.iloc[i, j]) > 0.95:
            high_corr.append((corr.columns[i], corr.columns[j], corr.iloc[i, j]))

print("\nHigh Correlations:")
for c in sorted(high_corr, key=lambda x: -abs(x[2])):
    print(f"{c[0]} - {c[1]}: {c[2]:.4f}")

# Let's do a multiple regression to see if some products are baskets of others
# We will just run an L1 penalized regression (Lasso) or check OLS for each product against all others
from sklearn.linear_model import LassoCV
from sklearn.preprocessing import StandardScaler

scaler = StandardScaler()
X_scaled = scaler.fit_transform(pivoted)
X_scaled_df = pd.DataFrame(X_scaled, columns=pivoted.columns, index=pivoted.index)

print("\nRunning Lasso to find basket dependencies...")
for prod in pivoted.columns:
    y = X_scaled_df[prod]
    X = X_scaled_df.drop(columns=[prod])
    
    lasso = LassoCV(cv=5, random_state=42).fit(X, y)
    score = lasso.score(X, y)
    
    if score > 0.98: # Almost perfect fit implies a deterministic basket relationship
        print(f"\nProduct: {prod} (R^2 = {score:.4f})")
        coefs = pd.Series(lasso.coef_, index=X.columns)
        important = coefs[abs(coefs) > 0.01]
        
        # Now run OLS on the original non-scaled data for these important features to get exact coefficients
        if len(important) > 0:
            X_unscaled = pivoted[important.index]
            y_unscaled = pivoted[prod]
            ols = LinearRegression().fit(X_unscaled, y_unscaled)
            print("  Exact coefficients:")
            for c_name, c_val in zip(important.index, ols.coef_):
                print(f"    {c_name}: {c_val:.4f}")
            print(f"    Intercept: {ols.intercept_:.4f}")

