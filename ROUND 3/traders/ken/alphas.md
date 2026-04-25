# Prosperity Round 3: Alpha Discoveries

This document tracks and ranks the key quantitative edges (alphas) found during the optimization of the Ken/Generation series.

**Alpha count: 8**

---

## 🏆 Tier 1: Core Performance Drivers (Must-Haves)

### 1. HP Anchor (`HYDROGEL_PACK`)
- **Impact**: High / Most Stable
- **Discovery**: The price mean-reverts heavily around a hard baseline of **9991.0**.
- **Benefit**: Foundation of the bot's base PnL. Prevents chasing noise in the highest-volume instrument.

### 2. Quadratic Smile Fitting
- **Impact**: High / Foundation
- **Discovery**: Individual strike IVs are too noisy for precision trading. A global quadratic fit ($IV = ax^2 + bx + c$) on log-moneyness reveals the "true" fair value.
- **Benefit**: Allows the bot to find mispricing even when spreads are wide, enabling the RV engine to scale across 10 strikes.

### 3. Gamma-Weighted Sizing
- **Impact**: High / PnL Scaler
- **Discovery**: Options PnL potential is concentrated at-the-money (ATM).
- **Implementation**: Trade quantity scaled by `avg_gamma / 0.0005`.
- **Benefit**: Automatically allocates more position limit to high-convexity opportunities, maximizing PnL per contract.

---

## 🥈 Tier 2: Risk & Retention Alphas (Stability)

### 4. VFE Speed Limiters
- **Impact**: Medium / Retention
- **Discovery**: Rapid position accumulation leads to adverse selection (getting "run over").
- **Benefit**: Forces cooling periods after large trades. Drastically improves full-day PnL retention.

### 5. Theta-Aware Exit Optimization
- **Impact**: Medium / Efficiency
- **Discovery**: Holding "Theta-paying" (long) positions as $T \to 0$ bleeds convergence profit.
- **Implementation**: Tighter exit hurdles for long positions; looser for short positions.
- **Benefit**: Captured **+6%** uplift in full-day PnL by managing temporal decay.

---

## 🥉 Tier 3: Execution & Logic Alphas (Precision)

### 6. VFE Micro-Price Tilt
- **Impact**: Low-Medium / Fill Quality
- **Discovery**: Mid-price lags book imbalance.
- **Implementation**: Fair price tilted towards the heavier side of the book.
- **Benefit**: Reduces adverse selection and improves fill rates for the VFE hedge.

### 7. Vega-Aware Entry Hurdles
- **Impact**: Low-Medium / Safety
- **Discovery**: Wide underlying spreads mask the true cost of hedging options.
- **Benefit**: Filters out "phantom" trades where the mispricing is an artifact of VFE illiquidity.

### 8. Day Alignment Logic
- **Impact**: Essential / Accuracy
- **Discovery**: `VEV_DAY_INIT = 2` is required to match the simulation's TTE.
- **Benefit**: Ensures all Greek-based calculations (Delta, Gamma, Theta) are mathematically correct during upload slice simulations.
