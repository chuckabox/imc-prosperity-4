# Round 4 Manual Trading & Alpha Findings

## 1. Market Overview
Round 4 features the following products:
- **VELVETFRUIT_EXTRACT**: The underlying asset (Price range: 5100 - 5400).
- **HYDROGEL_PACK**: A correlated product (Price range: 9800 - 10200).
- **VEV_XXXX**: Call options on `VELVETFRUIT_EXTRACT` with strikes ranging from 4000 to 6500.

## 2. Manual Trade Log (Day 3 - First 1/10th)
I identified specific opportunities in the first 100,000 ticks of Day 3.

| Timestamp | Action | Product | Price | Rationale |
| :--- | :--- | :--- | :--- | :--- |
| 5,400 | BUY | HYDROGEL_PACK | 9920 | Spread (HYDROGEL - VELVETFRUIT) dropped to 4700, well below mean (4768). |
| 15,200 | SELL | HYDROGEL_PACK | 10050 | Spread jumped to 4810, above +1.5 STD. |
| 42,000 | BUY | VEV_5200 | 90 | Underlying at 5260. Fair value (BS) suggests 95. Mispriced low. |
| 78,000 | SELL | VEV_5200 | 110 | Underlying at 5270. IV spiked temporarily. |

## 3. Alpha Identification

### Alpha A: Spread Mean Reversion
**Products:** `HYDROGEL_PACK` and `VELVETFRUIT_EXTRACT`
**Finding:** The spread `S = HYDROGEL_PACK - VELVETFRUIT_EXTRACT` is highly stationary with a mean around 4750.
**Strategy:** 
- Long Spread when `S < Mean - 1.5 * STD` (Buy HYDROGEL, Sell VELVETFRUIT)
- Short Spread when `S > Mean + 1.5 * STD` (Sell HYDROGEL, Buy VELVETFRUIT)
- Target Profit: 20-40 ticks per pair.

### Alpha B: Option Fair Value Arbitrage
**Products:** `VEV_XXXX` calls and `VELVETFRUIT_EXTRACT`
**Finding:** Market prices for `VEV_XXXX` often lag the underlying price moves, or exhibit temporary IV spikes.
**Strategy:**
- Calculate Black-Scholes price for all strikes.
- Trade when `|Market - FairValue| > Threshold`.
- Maintain delta-neutrality if possible, or just take the direction if the mispricing is large enough.

### Alpha C: Market Making the Spread
**Finding:** `HYDROGEL_PACK` has a consistent bid-ask spread of 4-6 ticks.
**Strategy:**
- Place resting orders on both sides of the book for `HYDROGEL_PACK` and `VELVETFRUIT_EXTRACT`.
- Focus on high-volume strikes like `VEV_5200`.

## 4. Proposed Algorithm: `malware.py`
The algorithm will combine these alphas, prioritizing the Spread Mean Reversion for the 20k PnL target in the first 1/10th of Day 3, while using the Option Arbitrage for long-term 6-digit PnL.
