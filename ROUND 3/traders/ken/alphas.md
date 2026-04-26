# Prosperity Round 3: Alpha Discoveries

This document tracks and ranks the key quantitative edges (alphas) found during the optimization of the Ken/Generation series.

**Alpha count: 9**

---

## 🏆 Tier 1: Core Performance Drivers (Must-Haves)

### 1. VFE Hedge Optimization ⭐ NEW
- **Impact**: Very High / Profit Protector
- **Discovery**: Over-aggressive hedging of VEV delta was bleeding -2,000+ per day in VFE taker costs.
- **Implementation**: Widened `VFE_HEDGE_BAND` to **35**. 
- **Benefit**: Full-day PnL improved from **1,872 → 6,319** (+237%). VFE turned from a cost center into a profit source (+2,376) by capturing spreads instead of crossing them.

### 2. Smile-Based Passive Market Making
- **Impact**: Medium / Revenue Generator
- **Discovery**: VEV_5400 is **chronically underpriced** and VEV_5300 is **chronically overpriced** relative to the fitted smile.
- **Implementation**: Passively quote bid/ask on these strikes using the smile fair value. Position-skewed to prevent inventory blowup.
- **Benefit**: Full-day PnL improved from **1,710 → 1,872** (+9.5%). 

### 1. The VEV "Voucher" Alpha (Smile Residuals)
- **Impact**: Critical / High
- **Discovery**: Option prices in `round3` exhibit a consistent smile skew relative to Black-Scholes. By fitting a second-order parabola to the IV smile, we identify "Voucher" opportunities where specific strikes are mispriced by 1.5+ seashells.
- **Implementation**: Smile-based passive MM + Aggressive Taker triggers for high-conviction mispricing.
- **Benefit**: Foundation for 50k+ PnL rounds.

### 2. Adin-Sync Hydrogel (AS-Maker)
- **Impact**: High / Stability
- **Discovery**: Hydrogel follows a tight mean-reversion around anchor **9993.0**. Using the Avellaneda-Stoikov (AS) model for inventory-skewed quoting captures 13k+ PnL per day.
- **Lesson**: Rust backtester enforces a strict **80-unit limit** for Hydrogel. Exceeding this causes silent order rejection.
- **Benefit**: Provides the 13k "Base" PnL that Adin v2 relies on.
- **Benefit**: Powers both the RV engine and the new passive MM. Enables stable fair pricing across all 10 strikes.

### 4. Gamma-Weighted Sizing
- **Impact**: High / PnL Scaler
- **Discovery**: Options PnL potential is concentrated at-the-money (ATM).
- **Implementation**: Trade quantity scaled by `avg_gamma / 0.0005`.
- **Benefit**: Automatically allocates more position limit to high-convexity opportunities.

---

## 🥈 Tier 2: Risk & Retention Alphas (Stability)

### 5. VFE Speed Limiters
- **Impact**: Medium / Retention
- **Discovery**: Rapid position accumulation leads to adverse selection (getting "run over").
- **Benefit**: Forces cooling periods after large trades. Drastically improves full-day PnL retention.

### 6. Theta-Aware Exit Optimization
- **Impact**: Medium / Efficiency
- **Discovery**: Holding "Theta-paying" (long) positions as $T \to 0$ bleeds convergence profit.
- **Implementation**: Tighter exit hurdles for long positions; looser for short positions.
- **Benefit**: Captured **+6%** uplift in full-day PnL by managing temporal decay.

---

## 🥉 Tier 3: Execution & Logic Alphas (Precision)

### 7. VFE Micro-Price Tilt
- **Impact**: Low-Medium / Fill Quality
- **Discovery**: Mid-price lags book imbalance.
- **Implementation**: Fair price tilted towards the heavier side of the book.
- **Benefit**: Reduces adverse selection and improves fill rates for the VFE hedge.

### 8. Vega-Aware Entry Hurdles
- **Impact**: Low-Medium / Safety
- **Discovery**: Wide underlying spreads mask the true cost of hedging options.
- **Benefit**: Filters out "phantom" trades where the mispricing is an artifact of VFE illiquidity.

### 9. Day Alignment Logic
- **Impact**: Essential / Accuracy
- **Discovery**: `VEV_DAY_INIT = 2` is required to match the simulation's TTE.
- **Benefit**: Ensures all Greek-based calculations (Delta, Gamma, Theta) are mathematically correct.

---

## 📈 Performance Progression
| Trader | Upload (10%) | Day 0 | Day 1 | Day 2 | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `we found epsilon` | 11,450 | - | - | 1,513 | Baseline |
| `we found greek` | 11,583 | - | - | 1,612 | Gamma + Vega |
| `we found theta` | 11,583 | - | - | 1,710 | Theta exit |
| `we found smile mm` | 11,583 | - | - | 1,872 | Passive MM |
| we found vfe gold (Gold v2) | 40,042 | 15.3k | 18.4k | 6.3k | **Oracle Tier**. Optimized for all days. |
| **Ken Gold v2.1 (Rust)** | **~47k** | **~15k** | **~18k** | **14.8k** | **RUST CHAMPION**. Beats Adin v2. |

---

## 🗝️ Key Discovery: The "Rust Reality" Gap
During the Round 3 optimization, we identified why many high-performing Python bots fail in Rust:
1. **Passive Fills**: Rust uses a queue-based model. Passive orders at the touch (Bid/Ask) often have **zero fill rate**.
2. **Aggressive Hedging**: You **must** be a Taker for the VFE Delta hedge. Saving 2 seashells in maker fees isn't worth losing 500 seashells in unhedged price movement.
3. **The 80-Limit Wall**: The Rust `round3` dataset rejects orders for `HYDROGEL_PACK` if the limit exceeds 80, even though the official competition limit is 200. Staying at 80 is the "Secret" to the 13k/day Hydrogel run.

---

## 🏆 Current Champion: `we found vfe gold.py`
**Total Round 3 PnL: 40,042**
*   **Day 0**: 15,296
*   **Day 1**: 18,418
*   **Day 2**: 6,328
*   **Benchmark**: Firmly in the "Fair" range (30k-50k) for Rust backtester equivalence.
