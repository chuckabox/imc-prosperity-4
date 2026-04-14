import pandas as pd
import numpy as np
import os

data_dir = r"c:\Users\peter\Desktop\imc-prosperity-4\ROUND 1\data_capsule"
files = [f for f in os.listdir(data_dir) if f.startswith("prices")]

dfs = []
for f in files:
    df = pd.read_csv(os.path.join(data_dir, f), sep=';')
    dfs.append(df)

df = pd.concat(dfs)

print("--- Data Summary ---")
for product in df['product'].unique():
    p_df = df[df['product'] == product]
    print(f"{product}: Mean Mid-Price = {p_df['mid_price'].mean():.2f}")

# Osmium Regression
print("\n--- Osmium Regression Analysis ---")
os_df = df[df['product'] == 'ASH_COATED_OSMIUM'].copy()
os_df = os_df.sort_values(['day', 'timestamp'])
# Mid prices
mid_prices = os_df['mid_price'].values

# Create lags
X = []
y = []
for i in range(3, len(mid_prices)):
    lag1 = mid_prices[i-1]
    lag2 = mid_prices[i-2]
    lag3 = mid_prices[i-3]
    X.append([1, lag1, lag2, lag3])
    y.append(mid_prices[i])

X = np.array(X)
y = np.array(y)

# Manual Least Squares: beta = (X^T X)^-1 X^T y
beta, residuals, rank, s = np.linalg.lstsq(X, y, rcond=None)

print(f"Intercept: {beta[0]:.4f}")
print(f"Weights (Lag 1, 2, 3): {beta[1:]}")
# R^2 calculation
y_mean = np.mean(y)
ss_total = np.sum((y - y_mean)**2)
ss_res = np.sum((y - (X @ beta))**2)
r2 = 1 - (ss_res / ss_total)
print(f"R^2 Score: {r2:.4f}")

# Pepper Root Anchor
print("\n--- Pepper Root Anchor Analysis ---")
pr_df = df[df['product'] == 'INTARIAN_PEPPER_ROOT']
print(f"Mean: {pr_df['mid_price'].mean():.2f}")
print(f"Std: {pr_df['mid_price'].std():.2f}")
print(f"Min: {pr_df['mid_price'].min()}, Max: {pr_df['mid_price'].max()}")
