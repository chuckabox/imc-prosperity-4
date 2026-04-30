# Drawdown Reduction Changes (SafeKiller vs Answer)

After analyzing `answer.py` from the `peter` folder, the following structural weaknesses were identified which contribute to "the dip" (drawdowns) during volatile market regimes:

1. **Static Limits**: A hardcoded `LIMIT = 10` restricts trading on high-volume products (like `CHOCOLATE` or `COCONUT`), reducing potential PnL and artificially inflating risk ratios on low-limit products.
2. **Linear Inventory Skew**: The base formula `fair = mid - (INV_SKEW * pos)` uses a static 0.25 tick skew. Near maximum inventory, this provides insufficient protection against toxic flow, leading to accumulating max inventory on the wrong side of a strong market trend.
3. **Passive-Only Execution**: The logic strictly forces `mm_bid <= ask - 1` and `mm_ask >= bid + 1`. If inventory is maxed out and the market trend reverses strongly against the position, the trader simply holds the bag without stopping out, resulting in deep drawdowns.
4. **No Trend/Shock Awareness**: The system does not adjust to short-term momentum or volatility, quoting the same tight 1-tick edge regardless of market speed.

### Implemented Improvements in `SafeKiller.py`

1. **Dynamic Limits via Product Mapping**
   - Implemented a `LIMITS` dictionary to support distinct maximum position sizing per product, allowing optimal scaling per asset.

2. **Quadratic Inventory Skew (Risk-Adjusted Fair Price)**
   - Modified skew to increase dynamically as the position approaches the limit: `inv_skew_factor = BASE_INV_SKEW * (1.0 + abs(pos_ratio) * 2.0)`.
   - This severely penalizes taking on more inventory when already heavily exposed, avoiding toxic liquidity.

3. **Trend Detection and Momentum Filters**
   - Added `price_hist` to memory to track mid-prices over time.
   - Computes a short-term MA (10 periods) vs long-term MA (50 periods). If `ma_short` significantly diverges from `ma_long`, the algorithm automatically adjusts the `fair` price toward the trend (`trend_adj`), preventing adverse selection.

4. **Dynamic Edge Quoting**
   - Replaced fixed `1` tick edge with `edge = 1 + abs(trend_adj) * 0.5`. Spreads automatically widen during high momentum or volatility periods to protect capital.

5. **Active De-Risking (Cut-Loss Mechanism)**
   - Integrated a critical drawdown safeguard. If inventory exceeds 80% of the maximum limit **AND** the trend opposes the position, the algorithm will cross the spread as a taker (`mm_ask = bid` or `mm_bid = ask`) to aggressively unwind and stop the bleeding.

6. **Inventory Clip Scaling**
   - Adjusted order volumes based on available inventory space instead of fixed `MM_CLIP` blocks. It scales down clip size as inventory maxes out, smoothing out entry sizes and reducing the impact of large simultaneous fills at bad prices.
