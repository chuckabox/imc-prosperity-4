# Round 4 Manual Trading Playbook (Updated)

Date: 2026-04-28

This note captures a discretionary/manual-trader view for Round 4, merging microstructure tape-reading with new quantitative "Oracle" discoveries.

## Core Trading Priorities

1.  **Exploit the Volatility Oracle**: Use `HYDROGEL_PACK` as a lead indicator for `VEV_*` option pricing.
2.  **Harvest Synthetic ITM Arbitrage**: Capture risk-free spreads on `VEV_4000` and `VEV_4500`.
3.  **Counterparty Tracking**: Lean against `Mark 67` (Buyer) and `Mark 49/22` (Sellers) for directional skew.
4.  **Prioritize Passive Fills**: In high-density portal environments, passive fills are the primary PnL driver; limit taker orders to high-conviction signals.

## Manual Execution Framework

### Mode 1: Passive MM (default)
- Quote both sides in `HYDROGEL_PACK` and `VELVETFRUIT_EXTRACT`.
- **New Skew Logic**: Adjust your bid/ask spread based on `HYDROGEL_PACK` price. High price = High Vol = Wider spreads.
- Harvest spread when fill quality remains acceptable.

### Mode 2: Flow-follow (event-driven)
- Trigger when directional prints cluster from repeated participants:
    - **Bullish Bias**: `Mark 67` aggressive buying in VFE.
    - **Bearish Bias**: `Mark 49` / `Mark 22` sell waves in VFE.
- Use these "whales" to skew your quoting levels (e.g., if `Mark 67` is buying, move your bids up to capture more fills).

### Mode 3: Volatility Arbitrage (The "Quant" Mode)
- **Signal**: `HYDROGEL_PACK` price deviates from the rolling volatility of `VELVETFRUIT_EXTRACT`.
- **Action**: 
    - If `HYDROGEL_PACK` is high but `VEV_5200/5300` are cheap -> **Buy Vol** (Buy Calls, Sell Underlying).
    - If `HYDROGEL_PACK` is low but `VEV` prices are high -> **Sell Vol** (Sell Calls, Buy Underlying).
- **Goal**: Capture the "Vega" premium.

### Mode 4: ITM Synthetic Arbitrage (Risk-Free)
- **Target**: `VEV_4000`, `VEV_4500`.
- **Rule**: These should always trade at `Price = VFE_Mid - Strike`.
- **Action**: Execute whenever the spread allows for a 1-2 unit profit. This is effectively trading VFE with no directional risk.

## Key Findings Summary
*   **Volatility Link**: `HYDROGEL_PACK` is a direct proxy for Extract volatility (0.62 correlation).
*   **Deep ITM**: `VEV_4000/4500` have zero time value; they are "Synthetic Extract."
*   **Live Realism**: Backtest portal fills are 10x denser; your strategy must be "fill-hungry" (passive) rather than "price-predicting" (taker).

## Suggested Next Step
Integrate the **Black-Scholes Oracle** into the automated trader to dynamically adjust `VEV` quotes based on `HYDROGEL_PACK` price.
