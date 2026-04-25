the 3 resources, explain the difference between each in terms of what it is, how volatile it is etc

Based on the analysis of the market data and the trading code in your workspace, here is the breakdown of the three resources available in Round 3:

### 1. HYDROGEL_PACK (HP)

- **What it is:** A "Delta-1" commodity. In the IMC Prosperity lore, these are often designed to mimic the behavior of "Starfish" from previous rounds.
- **Volatility:** **Medium.** It maintains a very stable long-term mean (roughly **9991.0**).
- **Key Characteristics:**
  - **Mean Reversion:** It exhibits very strong short-term mean reversion (negative 1-lag autocorrelation). This means if the price jumps up, it is statistically likely to drop back down almost immediately.
  - **The "Workhorse":** Because of its predictable mean, it is the safest asset for high-volume market making.
  - **Lead-Lag:** It tends to lag slightly behind `VELVETFRUIT_EXTRACT`, making it susceptible to "lead-lag" arbitrage.

### 2. VELVETFRUIT_EXTRACT (VFE)

- **What it is:** A "Delta-1" commodity that serves as the **underlying asset** for the Vouchers (Options).
- **Volatility:** **High.** Realized volatility is significantly higher than Hydrogel (measured at approximately **2.15% per day**).
- **Key Characteristics:**
  - **Trending behavior:** Unlike Hydrogel, VFE is prone to "slow drifts" or trends. It doesn't snap back to a mean as reliably.
  - **Tight Spreads:** It usually has a tighter bid-ask spread (around 5 ticks), making it more expensive to trade aggressively but better for capturing small price movements.
  - **Predictive Power:** Because it moves more freely, it often acts as the "leader" for the rest of the market's price action.

### 3. VEV (Vouchers / Options)

- **What it is:** These are **European Call Options** with `VELVETFRUIT_EXTRACT` as the underlying. They come in various strike prices (K) ranging from 4000 to 6500.
- **Volatility:** **Extremely High (Leveraged).** As options, their price movements are a function of VFE's price, time to expiry, and **Implied Volatility (IV)**.
- **Key Characteristics:**
  - **The IV Smile:** The market doesn't price all strikes with the same volatility. There is a "smile" where deep ITM (4000/4500) and OTM (6000/6500) strikes have different implied vols than the ATM (5200/5300) strikes.
  - **Time Decay (Theta):** These assets lose value every tick as they approach the end of the round.
  - **Structural Edge:** There are persistent "biases" in the smile (e.g., K=5400 is often structurally "cheap" relative to the parabolic fit), which allows for alpha-taking without needing to predict the direction of the underlying VFE.

---

### Summary Table

| Resource        | Type    | Primary Behavior  | Volatility | Typical Strategy                    |
| :-------------- | :------ | :---------------- | :--------- | :---------------------------------- |
| **HYDROGEL**    | Delta-1 | Mean Reversion    | Medium     | High-frequency MM / Pennying        |
| **VELVETFRUIT** | Delta-1 | Trending / Lead   | High       | OBI-aware MM / Trend following      |
| **VEV**         | Options | Volatility / Skew | Extreme    | Smile-fit Arbitrage / Delta Hedging |

now for trader 100 apply these strategies. with the low volatility go extremely hard on remaining stable. the high volatility aim for the highest pnl. the trader50 was good. make trader 100

Edited trader100.py

I have created **trader100.py**, which implements a split-logic approach tailored to the different volatility profiles of each asset class.

### 1. HYDROGEL: Extreme Stability

For the low-volatility asset, the goal is to "never lose" and maintain a perfectly flat equity curve.

- **Anchor-Blend (Fixed 9991.0):** Uses a heavy blend on the fixed anchor (9991.0) to ensure the trader always knows "True North" and doesn't get tricked by short-term price drifts.
- **Volatility Filter:** Automatically calculates the "speed" of price movements. If HP starts moving too fast, the trader **automatically widens its spread** to avoid being "run over" by aggressive takers.
- **Safety Skew:** A conservative inventory management system that slows down buying/selling as it approaches the 200-unit limit.

### 2. VELVETFRUIT: Maximum PnL

For the high-volatility asset, the goal is to capture trends and exploit every single mispricing in the book.

- **Aggressive Momentum:** Uses a very high EMA alpha (0.40) and sensitive Order Book Imbalance (OBI) thresholds to shift the fair value ahead of the market.
- **Deep-Take Logic:** Unlike standard traders that only look at the best bid/ask, this trader scans the **entire order book** and vacuums up all available liquidity that offers an edge.
- **Competitive Pennying:** Actively "pennies" the competition by quoting at `best_bid + 1` to ensure you get filled first on every profitable trade.

### 3. VEV (Options): Structural Edge

- **Parabolic Smile MM:** Uses the sophisticated "leave-one-out" parabolic fit to price all strikes from 5000–5500.
- **Intrinsic Scalping:** Includes a dedicated logic for K=4000/4500 ITM strikes to capture the high-value spread on "locked-in" intrinsic value.

You can access the final code here: [trader100.py](file:///c:/Users/peter/Desktop/imc-prosperity-4/ROUND%203/traders/peter/trader100.py).

is my logic wrong should i do high pnl for the stable, high stable for the high volatile or is what i asked for that correct

Viewed trader100.py:1-32
