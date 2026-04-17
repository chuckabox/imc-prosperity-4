import numpy as np
import pandas as pd

def fit_vcm(df, k_ar_diff=1):
    """
    Manual VECM fit using NumPy Linear Algebra.
    """
    y = df.values
    n, m = y.shape
    
    # Create Differenced Data (Delta Y)
    dy = np.diff(y, axis=0)
    
    # Create Lagged Levels (Y_{t-1}) for the Cointegration Term
    y_lag = y[:-1, :]
    
    # Solve for Beta (the cointegrating vector) using Eigen Decomposition
    # This is a simplified Johansen approach
    cov_y = np.cov(y.T)
    eigenvalues, eigenvectors = np.linalg.eig(cov_y)
    
    # The eigenvector corresponding to the smallest eigenvalue is our 'leash'
    beta = eigenvectors[:, np.argmin(eigenvalues)].reshape(-1, 1)
    
    # Solve for Alpha (Adjustment speed) using OLS: dy = alpha * (y_lag @ beta)
    ect = y_lag @ beta
    alpha = np.linalg.lstsq(ect, dy, rcond=None)[0]
    
    return alpha, beta, ect

def generate_signals(df, beta, threshold=2.0):
    """
    Generates signals by projecting prices onto the Beta vector.
    """
    prices = df.values
    # Spread calculation: S = Price_A - (Hedge_Ratio * Price_B)
    # We normalize Beta so the first coefficient is 1
    hedge_ratio = -beta[1, 0] / beta[0, 0]
    spread = prices[:, 0] - (hedge_ratio * prices[:, 1])
    
    # Calculate rolling Z-Score manually
    mean_s = np.mean(spread)
    std_s = np.std(spread)
    z_scores = (spread - mean_s) / (std_s if std_s > 0 else 1)
    
    signals = np.zeros(len(z_scores))
    signals[z_scores > threshold] = -1  # Short the spread
    signals[z_scores < -threshold] = 1   # Long the spread
    
    return signals, z_scores

def backtest_performance(signals, df):
    """
    Computes cumulative returns based on signal direction.
    """
    # Calculate price changes (returns)
    prices = df.values
    # Simple returns: (P_now / P_prev) - 1
    returns = np.diff(prices, axis=0) / prices[:-1, :]
    
    # Combine asset returns into a single 'Spread Return'
    # PnL = Signal * (Return_A - Return_B)
    spread_return = returns[:, 0] - returns[:, 1]
    
    # Apply signals (shifted by 1 to prevent look-ahead bias)
    strategy_returns = signals[:-1] * spread_return
    
    return np.sum(strategy_returns)

def walk_forward_optimizer(data, train_size=252, test_size=21):
    """
    data: DataFrame with AAPL and MSFT
    train_size: 1 Year (approx)
    test_size: 1 Month (approx)
    """
    best_overall_pnl = -np.inf
    optimal_params = {}
    
    # Define Parameter Grid for Brute Force
    thresholds = [1.5, 2.0, 2.5]
    lags = [1, 5, 9]
    vol_limits = [0.01, 0.02, 0.05]
    
    for t in thresholds:
        for l in lags:
            for v in vol_limits:
                cumulative_pnl = 0
                
                # Walk-forward through the dataset
                for i in range(0, len(data) - train_size - test_size, test_size):
                    # Step 1: Slice data
                    train_set = data.iloc[i : i + train_size]
                    test_set = data.iloc[i + train_size : i + train_size + test_size]
                    
                    try:
                        # Step 2: Fit VECM (Phase 7)
                        res, p, fcst = fit_vcm(train_set, k_ar_diff=l)
                        
                        # Step 3: Run Signal Logic (Phase 9)
                        # We use the 'alpha' and 'beta' from training to trade the test set
                        signals = generate_signals(test_set, res.beta, threshold=t, vol_limit=v)
                        
                        # Step 4: Calculate PnL for this month
                        cumulative_pnl += backtest_performance(signals, test_set)
                    except:
                        continue # Skip windows where math breaks (singular matrices)
                
                # Step 5: Log the champion
                if cumulative_pnl > best_overall_pnl:
                    best_overall_pnl = cumulative_pnl
                    optimal_params = {'threshold': t, 'lags': l, 'vol_limit': v}
                    
    return optimal_params, best_overall_pnl