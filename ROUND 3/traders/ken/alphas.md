# Prosperity Round 3: Alpha Discoveries

This document tracks the key quantitative edges (alphas) and architectural breakthroughs found during the optimization of the Ken/Generation trader series.

Alpha count: 8

## 1. Inventory & Market Making Alphas

### HP Anchor (`HYDROGEL_PACK`)
- **Discovery**: The `HYDROGEL_PACK` price mean-reverts heavily around a hard baseline of **9991.0**.
- **Implementation**: Used as a blend target for EWMA fair pricing.
- **Benefit**: Prevents the MM from following trends that are likely to mean-revert, keeping position skew profitable.

### VFE Micro-Price Tilt (`VELVETFRUIT_EXTRACT`)
- **Discovery**: The mid-price is often a lagging indicator of the next move compared to the book imbalance.
- **Implementation**: Calculated fair as `(1 - tilt) * ewma + tilt * micro`, where micro-price is `(bb * av + ba * bv) / (bv + av)`.
- **Benefit**: Faster reaction to order flow, reducing adverse selection.

### VFE Speed Limiters
- **Discovery**: Taking large positions too quickly leads to getting "run over" by momentum and hitting position limits in sub-optimal spots.
- **Implementation**: `VFE_SPEED_TRIGGER` and `SPEED_COOLDOWN_TS`. If more than 54 contracts are traded in a short window, the bot scales back for 40 seconds.
- **Benefit**: Improves retention and exit quality.

---

## 2. Options RV & Greek Alphas (`VEV` Options)

### Quadratic Smile Fitting
- **Discovery**: Strike-by-strike IV solving is noisy. A global quadratic fit ($IV = ax^2 + bx + c$) on log-moneyness provides a stable "fair" surface.
- **Implementation**: `_solve_3x3` matrix solver to fit the smile every tick across available strikes.
- **Benefit**: Provides robust fair prices for strikes even with wide spreads, allowing for tighter RV pairing.

### Gamma-Weighted Sizing
- **Discovery**: Options PnL potential is not uniform; it's highest where Gamma is highest (At-The-Money).
- **Implementation**: Scaled trade quantity by `avg_gamma / 0.0005`. 
- **Benefit**: Naturally sizes up high-conviction ATM trades while sizing down lower-convexity OTM/ITM trades, maximizing PnL/Limit efficiency.

### Vega-Aware Entry Hurdles
- **Discovery**: When the underlying (`VFE`) spread is wide, hedging costs eat the option spread.
- **Implementation**: `vega_bump = vega * vfe_spread * penalty`. Adds a dynamic hurdle to the entry mispricing.
- **Benefit**: Filters out "phantom" opportunities where the option mispricing is just a reflection of temporary underlying illiquidity.

### Day Alignment (`VEV_DAY_INIT = 2`)
- **Discovery**: Prosperity upload simulations for "Day 2" actually start with TTE values corresponding to the third day of a sequence.
- **Implementation**: Hard-coded `VEV_DAY_INIT` to align the bot's TTE calculation with the simulation environment.
- **Benefit**: Accurate BS pricing and Greek calculations in the upload slice.

### Theta-Aware Exit Optimization
- **Discovery**: RV pairs often have a Theta (time decay) mismatch. Holding a position that "pays" Theta as $T \to 0$ can erase convergence PnL.
- **Implementation**: Calculated live Theta per strike. Adjusted the exit hurdle: `eff_exit = EXIT_MISPRICING - (pos/100) * theta * weight`. 
- **Benefit**: Tightens exits for long positions to prevent bleed, while allowing short positions (collecting Theta) to stay open longer. Improved full-day PnL from **1,612** to **1,710**.

---

## 4. Future Roadmap
- **Smile-Wide Passive Market Making**: Quoting all 10 strikes simultaneously using the fitted surface.
- **Vanna/Volga Hedging**: Adjusting VFE hedge based on volatility sensitivity.
