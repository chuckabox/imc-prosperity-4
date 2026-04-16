import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

# 1. Load IMC Data
imc_files = [
    'prices_round_1_day_-2.csv',
    'prices_round_1_day_-1.csv',
    'prices_round_1_day_0.csv'
]
dfs = []
for f in imc_files:
    df = pd.read_csv(f'ROUND 1/data_capsule/{f}', sep=';')
    dfs.append(df)
imc_df = pd.concat(dfs, ignore_index=True)
# Target Product
product = 'INTARIAN_PEPPER_ROOT'
df_p = imc_df[imc_df['product'] == product].copy()
df_p = df_p.sort_values(['day', 'timestamp']).reset_index(drop=True)

# 2. Split into train, val, test
n = len(df_p)
train_end = int(n * 0.6)
val_end = int(n * 0.8)

train_df = df_p.iloc[:train_end]
val_df = df_p.iloc[train_end:val_end]
test_df = df_p.iloc[val_end:]

# Strategy Logic: Mean Reversion / Z-Score
def backtest(prices, window, z_thresh, pos_limit):
    prices = prices.copy()
    prices['mid'] = prices['mid_price']
    prices['ma'] = prices['mid'].rolling(window).mean()
    prices['std'] = prices['mid'].rolling(window).std()
    prices['z'] = (prices['mid'] - prices['ma']) / prices['std']
    
    pos = 0
    cash = 0
    limit = pos_limit
    
    pnls = []
    
    for i in range(len(prices)):
        row = prices.iloc[i]
        if np.isnan(row['z']):
            pnls.append(0)
            continue
            
        z = row['z']
        price = row['mid']
        
        # Simple execution
        target_pos = 0
        if z < -z_thresh:
            target_pos = limit
        elif z > z_thresh:
            target_pos = -limit
            
        trade = target_pos - pos
        cash -= trade * price
        pos = target_pos
        
        mtm = cash + pos * price
        pnls.append(mtm)
        
    prices['pnl'] = pnls
    prices['pnl_diff'] = prices['pnl'].diff().fillna(0)
    
    pnl = pnls[-1]
    variance = prices['pnl_diff'].var()
    dd = (prices['pnl'].cummax() - prices['pnl']).max()
    return pnl, variance, dd

# 3. Train & Tune (Grid Search)
best_pnl = -np.inf
best_params = None

for w in [50, 100, 200]:
    for z in [1.0, 1.5, 2.0]:
        pnl, _, _ = backtest(train_df, w, z, 80)
        if pnl > best_pnl:
            best_pnl = pnl
            best_params = (w, z)

print(f"Best Params (Train): window={best_params[0]}, z={best_params[1]}")

# 4. Stress Test (Val set with noise)
val_noise = val_df.copy()
val_noise['mid_price'] *= np.random.normal(1, 0.002, len(val_noise))
val_pnl, val_var, val_dd = backtest(val_noise, best_params[0], best_params[1], 80)

# 5. External Valid (SPY)
ext_df = pd.read_csv('ROUND 1/data/external/processed/SPY.csv')
ext_df['mid_price'] = ext_df['close']
ext_pnl, ext_var, ext_dd = backtest(ext_df, best_params[0], best_params[1], 80)

# 6. Test Evaluation
test_pnl, test_var, test_dd = backtest(test_df, best_params[0], best_params[1], 80)

print(f"Val (Noise) -> PnL: {val_pnl:.0f}, Var: {val_var:.2f}, DD: {val_dd:.0f}")
print(f"External -> PnL: {ext_pnl:.0f}, Var: {ext_var:.2f}, DD: {ext_dd:.0f}")
print(f"Test -> PnL: {test_pnl:.0f}, Var: {test_var:.2f}, DD: {test_dd:.0f}")
