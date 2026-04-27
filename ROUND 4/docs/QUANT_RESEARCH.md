# Round 4: Quantitative Research Findings

## 1. Product Definitions & Roles
Based on multi-day tape analysis, the assets in Round 4 function as a Volatility-Options ecosystem:

| Symbol | Role | Characteristics |
| :--- | :--- | :--- |
| `VELVETFRUIT_EXTRACT` | **Underlying** | Highly liquid, mean-reverting at short horizons, driven by identifiable counterparties. |
| `HYDROGEL_PACK` | **Volatility Oracle** | Correlates **0.62** with 1k-tick rolling volatility of Extract. Predicts option price shifts. |
| `VEV_XXXX` | **Call Options** | Standard calls on Extract with strikes from 4000 to 6500. |

## 2. The Volatility Oracle (`HYDROGEL_PACK`)
The primary breakthrough in this research is identifying the predictive power of `HYDROGEL_PACK`. 

*   **Statistical Evidence**: Rolling standard deviation of `VELVETFRUIT_EXTRACT` (1000ms window) tracks `HYDROGEL_PACK` mid-price with high fidelity.
*   **Trading Utility**: Instead of guessing the "fair" Implied Volatility (IV) for options, use `HYDROGEL_PACK` as a direct input for the $\sigma$ parameter in Black-Scholes.
*   **Lead-Lag**: `HYDROGEL_PACK` often moves 1-5 timestamps *before* option spreads widen/narrow to reflect new volatility regimes.

## 3. Option Strike Analysis

### Deep In-The-Money (ITM) Parity
*   **Strikes**: `VEV_4000`, `VEV_4500`.
*   **Finding**: These options consistently trade at **zero time value** (`Price = S - K`).
*   **Edge**: Any deviation is a high-conviction arbitrage. If `Price < S - K`, it is a risk-free buy (synthetic underlying).

### At-The-Money (ATM) Gamma
*   **Strikes**: `VEV_5200`, `VEV_5300`.
*   **Finding**: These are the most sensitive to `HYDROGEL_PACK` signals. They carry the highest Vega and Gamma.
*   **Strategy**: Best used for **Volatility Arbitrage** (Delta-neutral longing/shorting of volatility).

### Out-Of-The-Money (OTM) Lottery
*   **Strikes**: `VEV_6000`, `VEV_6500`.
*   **Finding**: Prices are often pinned at floor values (0.5 - 1.0). High adverse selection risk; avoid unless volatility spikes are extreme.

## 4. Counterparty Flow (The "Whale" Signals)
Tracking specific participants in `trades_round_4_day_x.csv` reveals persistent biases:
*   **`Mark 67`**: Tends to be a persistent buyer of `VELVETFRUIT_EXTRACT`.
*   **`Mark 49` / `Mark 22`**: Frequently provide sell-side liquidity or execute large sell waves.
*   **Strategy**: Use these as "Flow Skew" inputs for your Market Making logic.

## 5. Backtest vs. Live Discrepancy
*   **Diagnosis**: CSV data is sampled at ~10% of the live exchange density.
*   **Impact**: Algos optimized for CSV "patterns" fail on the portal because the portal has 10x more noise and micro-fills.
*   **Solution**: Shift from "Predictive Directional" models to "Robust Spread Capture" models. Prioritize **Passive Fills** and use wider thresholds for Taker orders.
