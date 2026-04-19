# Round 2: The Interian Expansion - Trading Specification

This document provides a comprehensive overview of the second trading round on Intara, including new mechanics, asset behaviors, and algorithmic strategies for use as context in development.

## 1. Overview & Qualifiers
*   **Mission:** Final opportunity to reach the threshold of **200,000 XIRECs** before the leaderboard resets for Phase 2.
*   **Status:** Qualifications for the final mission are primary objectives for these first two rounds.
*   **Market State:** Acceleration in trading activity with increased competition for Ash-Coated Osmium and Intarian Pepper Root.

---

## 2. New Strategic Mechanics

### Market Access Fee (MAF)
A "blind auction" mechanism to secure additional market data and liquidity.
*   **Benefit:** Gain access to **25% more order book volume**.
*   **Mechanism:** Top 50% of bidders secure the extra flow.
*   **Outcome - Success:** Pay the bid price, receive 125% total quotes (80% base + 25% extra).
*   **Outcome - Failure:** Pay 0, continue with standard 80% volume allocation.
*   **Implementation:** Incorporate a `bid()` function into the `Trader` class.
*   **Game Theory:** Aim for the "median" bid; overpaying guarantees access but reduces final PnL.

### Growth Pillars
*   **Budget:** 50,000 XIRECs provided by XIREN.
*   **Task:** Distribute budget across three growth pillars to optimize outpost performance.

---

## 3. Asset Analysis & Strategy

### Intarian Pepper Root
*   **Behavior:** Non-stationary "straight-line" logic, adjusted for a **linear trend**.
*   **Observation:** Linear regression on `mid_price` (window ≈ 100 timesteps) yields decent predictive results.
*   **Strategy Insights:** 
    *   Avoid naive "buy as fast as possible" due to high transaction costs.
    *   **Pro Tip (@oats/April):** Significant value capture possible by reacting to the **increasing spread**.
    *   Ideal strategy: Sophisticated Buy and Hold or Trend-Following.

### Ash-Coated Osmium
*   **Behavior:** "Drifting" asset (similar to TOMATOES in tutorials).
*   **Primary Challenge:** Adapt a drift-adjusted mean reversion strategy.
*   **Optimal Approach:** A blend of Market Making (MM), Market Taking (MT) on mispricings, Mean Reversion (MR), and Drift Adjustment.
*   **Community Note:** Finding the perfect "quoting mix" was the main challenge discussed on Discord.

---

## 4. Research & Denoising Techniques
The following techniques showed significant benefit in signal quality:
*   **Mid-Price Backfilling:** Essential during moments with empty order books.
*   **Volume-Weighted Mid-Prices (VWAP):** Utilizing depth across the full order book rather than just the first level.
*   **Order Flow Imbalance:** Adjusting price signals based on significant imbalance periods.

---

## 5. Post-Mortem: Lessons from Previous Failures
> [!WARNING]
> Critical errors identified in previous implementations:

*   **Directional Errors:** Reversing Z-score entry/exit signals (buying on high price instead of selling).
*   **Negative Order Volumes:** Logic errors leading to "crossing the spread" against own orders.
*   **Inventory Management:** Subtracting flat volumes without checks (`max(0, quote)`), causing aggressive shorting on empty timestamps.
*   **Timing:** Shipping flawed code due to hard deadlines.

---

## 6. Development Roadmap
Future iterations focus on four primary pillars:

1.  **Gap Handling:** Robust logic for missing bids, asks, or mid-prices.
2.  **Time-Series Memory:** Maintaining a history of denoised mid-prices to filter temporary noise.
3.  **Trend Integration:** Micro-trend following to better time mean reversion entries.
4.  **Passive Liquidity:** Capturing spread with refined passive quote placement to avoid being "run over" by market moves.
