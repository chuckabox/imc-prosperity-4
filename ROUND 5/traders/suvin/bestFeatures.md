Features of This Trading Algorithm
Architecture
This is a passive market maker with leader-lag alpha skewing, built for a simulated trading competition (likely Prosperity/IMC). It trades multiple instruments simultaneously using a single Trader class with persistent state.

1. Persistent State Management

Serializes/deserializes state via traderData (JSON string) between rounds
Tracks price history for two instruments (bh_hist, poly_hist) with a rolling 100-bar lookback
Detects timestamp resets and clears stale memory automatically

2. Leader-Lag Alpha Signal

Treats GALAXY_SOUNDS_BLACK_HOLES as a leader and SLEEP_POD_POLYESTER as a lag instrument
Computes how much the leader has moved over the last 100 ticks
Calculates a correlation sign between leader and lag (positive vs. negative co-movement) using covariance
Applies a 10% scaled skew to the lag instrument's fair price based on leader movement

3. Inventory Skewing

Adjusts fair price by 0.25 × position to lean against inventory buildup — e.g. if long 4 units, fair price is pulled down by 1.0, making the algo more eager to sell

4. Passive Market Making (Universal)

Runs on every instrument in order_depths automatically
Always quotes inside the spread (bid+1 / ask−1) relative to fair value, acting as a maker
Clips order sizes to MM_CLIP = 5 and respects position limits (LIMIT = 10) on both sides

5. Quote Clamping

Prevents quoting outside the existing book:

mm_bid = min(round(fair - 1), ask - 1) — never lifts the offer accidentally
mm_ask = max(round(fair + 1), bid + 1) — never hits the bid accidentally




Key Parameters
ParameterValueRoleLIMIT10Max position per instrumentMM_CLIP5Max order size per quoteINV_SKEW0.25Fair price shift per unit of inventoryLL_LOOKBACK100Bars of history for leader-lag signal