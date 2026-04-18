import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os

def analyze_assets():
    data_dir = r"ROUND 2\data_capsule"
    files = [f for f in os.listdir(data_dir) if f.startswith("prices_round_2")]
    
    all_data = []
    for file in files:
        df = pd.read_csv(os.path.join(data_dir, file), sep=';')
        all_data.append(df)
    
    df = pd.concat(all_data).sort_values(by=['day', 'timestamp'])
    
    # 1. Pepper Root Analysis
    pepper = df[df['product'] == 'INTARIAN_PEPPER_ROOT'].copy()
    pepper['spread'] = pepper['ask_price_1'] - pepper['bid_price_1']
    
    # Linear Trend for Pepper Root
    # Window of 100 timesteps (note: timestamps are in increments of 100)
    window = 100
    pepper['mid_price_rolling'] = pepper['mid_price'].rolling(window=window).mean()
    
    # Optimized slope calculation for rolling window
    x = np.arange(window)
    x_mean = np.mean(x)
    x_var = np.sum((x - x_mean)**2)
    
    def fast_slope(y):
        return np.sum((x - x_mean) * (y - np.mean(y))) / x_var
    
    pepper['slope'] = pepper['mid_price'].rolling(window=window).apply(fast_slope, raw=True)
    
    # 2. Osmium Analysis
    osmium = df[df['product'] == 'ASH_COATED_OSMIUM'].copy()
    osmium['spread'] = osmium['ask_price_1'] - osmium['bid_price_1']
    
    # Denoised mid price (VWAP mid)
    # Using full book if possible
    def get_vwap_mid(row):
        prices = []
        volumes = []
        for i in range(1, 4):
            if not np.isnan(row[f'bid_price_{i}']) and not np.isnan(row[f'bid_volume_{i}']):
                prices.append(row[f'bid_price_{i}'])
                volumes.append(row[f'bid_volume_{i}'])
            if not np.isnan(row[f'ask_price_{i}']) and not np.isnan(row[f'ask_volume_{i}']):
                prices.append(row[f'ask_price_{i}'])
                volumes.append(row[f'ask_volume_{i}'])
        
        if not prices: return row['mid_price']
        
        # VWAP weighting: closer to the side with less volume usually indicates pressure
        # Actually, standard VWAP mid-price is (p1*v2 + p2*v1)/(v1+v2) to lean towards the "heavier" side
        # Basic:
        b1, bv1 = row['bid_price_1'], row['bid_volume_1']
        a1, av1 = row['ask_price_1'], row['ask_volume_1']
        if np.isnan(b1) or np.isnan(a1): return row['mid_price']
        
        return (b1 * av1 + a1 * bv1) / (bv1 + av1)

    osmium['vwap_mid'] = osmium.apply(get_vwap_mid, axis=1)
    
    # Backfilling gaps
    osmium['vwap_mid_filled'] = osmium['vwap_mid'].ffill()
    
    # Spread behavior
    print("Pepper Root Spread Stats:")
    print(pepper['spread'].describe())
    
    print("\nOsmium Spread Stats:")
    print(osmium['spread'].describe())
    
    # Correlation between spread increase and future price movement?
    pepper['spread_delta'] = pepper['spread'].diff()
    # Let's check if high spread leads to mean reversion
    pepper['next_mid_change'] = pepper['mid_price'].shift(-5) - pepper['mid_price']
    
    # Analyze price change when spread is increasing
    pepper['spread_increasing'] = pepper['spread_delta'] > 0
    inc_spread_move = pepper[pepper['spread_increasing']]['next_mid_change'].mean()
    dec_spread_move = pepper[~pepper['spread_increasing']]['next_mid_change'].mean()
    
    print(f"\nPepper Root Mean 5-step move when Spread is INCREASING: {inc_spread_move:.4f}")
    print(f"Pepper Root Mean 5-step move when Spread is DECREASING: {dec_spread_move:.4f}")

    # 2. Osmium Analysis
    osmium = df[df['product'] == 'ASH_COATED_OSMIUM'].copy()
    osmium['spread'] = osmium['ask_price_1'] - osmium['bid_price_1']
    
    # Denoised mid price (VWAP mid)
    def get_vwap_mid(row):
        b1, bv1 = row['bid_price_1'], row['bid_volume_1']
        a1, av1 = row['ask_price_1'], row['ask_volume_1']
        if np.isnan(b1) or np.isnan(a1): return np.nan
        # VWAP mid: weights price by the volume on the OTHER side to reflect pressure
        # Actually, if ask_volume is high, price should go DOWN, so mid moves closer to bid.
        return (b1 * av1 + a1 * bv1) / (bv1 + av1)

    osmium['vwap_mid'] = osmium.apply(get_vwap_mid, axis=1)
    osmium['vwap_mid_filled'] = osmium['vwap_mid'].ffill()
    
    # Check if vwap_mid leads mid_price
    osmium['mid_change'] = osmium['mid_price'].shift(-1) - osmium['mid_price']
    osmium['vwap_diff'] = osmium['vwap_mid_filled'] - osmium['mid_price']
    
    vwap_corr = osmium[['vwap_diff', 'mid_change']].corr().iloc[0, 1]
    print(f"\nOsmium VWAP Diff vs Next Mid Change Correlation: {vwap_corr:.4f}")

    # Plotting for visual inspection
    avg_spread = pepper['spread'].mean()
    plt.figure(figsize=(15, 10))
    
    plt.subplot(2, 1, 1)
    plt.plot(pepper['timestamp'].iloc[:1000], pepper['mid_price'].iloc[:1000], label='Mid Price')
    plt.plot(pepper['timestamp'].iloc[:1000], pepper['mid_price'].iloc[:1000] + pepper['slope'].iloc[:1000]*10, label='Slope Prediction')
    plt.title('Pepper Root Mid Price & Local Slope')
    plt.legend()
    
    plt.subplot(2, 1, 2)
    plt.plot(pepper['timestamp'].iloc[:1000], pepper['spread'].iloc[:1000], label='Spread', color='orange')
    plt.axhline(avg_spread, color='red', linestyle='--', label='Avg Spread')
    plt.title('Pepper Root Spread')
    plt.legend()
    
    plt.tight_layout()
    plt.savefig(r'ROUND 2\scratch\pepper_analysis.png')
    
    plt.figure(figsize=(15, 12))
    plt.subplot(2, 1, 1)
    plt.plot(osmium['timestamp'].iloc[:500], osmium['mid_price'].iloc[:500], label='Standard Mid')
    plt.plot(osmium['timestamp'].iloc[:500], osmium['vwap_mid_filled'].iloc[:500], label='VWAP Mid (Denoised)', alpha=0.7)
    plt.title('Osmium Denoising')
    plt.legend()
    
    plt.subplot(2, 1, 2)
    plt.plot(osmium['timestamp'].iloc[:500], osmium['vwap_diff'].iloc[:500], label='VWAP - Mid', color='purple')
    plt.axhline(0, color='black', alpha=0.3)
    plt.title('Osmium VWAP Imbalance')
    plt.legend()
    
    plt.savefig(r'ROUND 2\scratch\osmium_analysis.png')

    print("\nAnalysis complete. Visualizations saved to ROUND 2\\scratch\\")

if __name__ == "__main__":
    analyze_assets()
