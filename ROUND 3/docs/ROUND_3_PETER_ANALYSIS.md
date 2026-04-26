# Round 3 – Personal Analysis & Alpha Discovery

This document summarizes the key differences between the Round 3 products and the identified strategies for finding alpha in each.

---

## 1. Product Definitions

| Symbol | Name | Type | Description |
| :--- | :--- | :--- | :--- |
| **TG01** | `HYDROGEL_PACK` | Stationary | Standard mean-reverting commodity. Similar to Amethysts/Osmium. |
| **TG02** | `VELVETFRUIT_EXTRACT` | Underlying | The drifting asset that vouchers are based on. Used for delta-hedging. |
| **TG03** | `VEV_XXXX` (Vouchers) | Options | European Call Options on TG02. The primary source of high-margin profit. |

---

## 2. Alpha Discovery Strategies

### TG01: Hydrogel Packs
*   **The Opportunity:** Predictable mean reversion around 10,000.
*   **Alpha Signal:** **Order Book Imbalance (OBI)**.
    *   Formula: `(Bid Volume - Ask Volume) / (Total Volume)`
    *   Implementation: Use OBI > 0.7 to skew quotes upwards. High imbalance typically precedes a price move to the next tick.
*   **Refinement:** Use the Ornstein-Uhlenbeck half-life (~30k ticks) to determine how aggressively to hold positions as the price deviates from the 10k anchor.

### TG02: Velvetfruit Extract
*   **The Opportunity:** Short-term mean reversion and liquidity provision.
*   **Alpha Signal:** **Negative Lag-1 Autocorrelation (-0.16)**.
    *   Behavior: Price moves are often followed by a reversal on the subsequent tick (bid-ask bounce).
    *   Implementation: Market-make with a tight spread. If a large buy order executes, move the ask price up but keep the bid price steady to capture the expected reversal.
*   **The "Olivia" Factor:** Monitor the trade tape for high-volume consistent traders whose activity may signal broader trend reversals.

### TG03: Velvetfruit Extract Vouchers (Options)
*   **The Opportunity:** **Volatility Arbitrage**.
*   **Alpha Signal:** **IV/RV Gap**.
    *   Market Implied Volatility (IV): **~1.26%/day**
    *   Historical Realized Volatility (RV): **~2.15%/day**
    *   *Result:* Options are systematically underpriced.
*   **Implementation:**
    1.  **Black-Scholes Pricing:** Use a theoretical σ of 1.8%–2.0% to calculate "Fair Value."
    2.  **Gamma Scalping:** Buy the undervalued vouchers and **Delta Hedge** using TG02.
    3.  **Strike Selection:** Focus on ATM (At-The-Money) strikes like **VEV_5200** and **VEV_5300** where Gamma is highest, maximizing profit from price swings in the underlying Extract.

---

## 3. Recommended Tools

*   `ROUND 3/scratch/hp_imbalance_signal.py`: For TG01 imbalance thresholds.
*   `ROUND 3/scratch/vev_iv_scan.py`: To monitor the IV gap on live days.
*   `ROUND 3/scratch/hydrogel_stats.py`: To update the mean-reversion anchor.

---
*Created by Peter's Analysis Assistant — 2026-04-26*
