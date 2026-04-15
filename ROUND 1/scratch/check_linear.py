import pandas as pd
import numpy as np

def analyze_linear(day):
    file_path = f"ROUND 1/data/data_capsule/prices_round_1_day_{day}.csv"
    try:
        df = pd.read_csv(file_path, sep=';')
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return

    df_pivot = df.pivot(index='timestamp', columns='product', values='mid_price').dropna()
    
    x = df_pivot['INTARIAN_PEPPER_ROOT'].values
    y = df_pivot['ASH_COATED_OSMIUM'].values
    
    # Simple linear regression using numpy
    A = np.vstack([x, np.ones(len(x))]).T
    m, c = np.linalg.lstsq(A, y, rcond=None)[0]
    
    # Calculate R^2
    y_pred = m * x + c
    ss_res = np.sum((y - y_pred)**2)
    ss_tot = np.sum((y - np.mean(y))**2)
    r2 = 1 - (ss_res / ss_tot)

    print(f"--- Day {day} Linear Regression ---")
    print(f"Osmium = {m:.6f} * Pepper + {c:.2f}")
    print(f"R^2: {r2:.6f}")

if __name__ == "__main__":
    for d in [-2, -1, 0]:
        analyze_linear(d)
        print("\n")
