import pandas as pd
import math

def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bs_call(S, K, T, sigma):
    if T <= 0 or sigma <= 0: return max(S - K, 0.0)
    d1 = (math.log(S/K) + 0.5*sigma**2*T)/(sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    return S*norm_cdf(d1) - K*norm_cdf(d2)

def get_iv(C, S, K, T):
    lo, hi = 1e-6, 2.0
    for _ in range(30):
        mid = (lo + hi) / 2
        if bs_call(S, K, T, mid) > C: hi = mid
        else: lo = mid
    return (lo + hi) / 2

df = pd.read_csv('ROUND 4/data_capsule/prices_round_4_day_3.csv', sep=';')
pivot = df.pivot(index='timestamp', columns='product', values='mid_price')
vfe = pivot['VELVETFRUIT_EXTRACT'].iloc[0]

for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500]:
    sym = f'VEV_{k}'
    c = pivot[sym].iloc[0]
    print(f"{sym} (S={vfe}, K={k}, C={c}) -> IV: {get_iv(c, vfe, k, 1.0):.4f}")
