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

### 2. HP Anchor (`HYDROGEL_PACK`)
- **Impact**: High / Most Stable
- **Discovery**: The price mean-reverts heavily around a hard baseline of **9991.0**.
- **Benefit**: Foundation of the bot's base PnL. Prevents chasing noise in the highest-volume instrument.

### 3. Quadratic Smile Fitting
- **Impact**: High / Foundation
- **Discovery**: Individual strike IVs are too noisy for precision trading. A global quadratic fit ($IV = ax^2 + bx + c$) on log-moneyness reveals the "true" fair value.
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
| Trader | Upload (10%) | Full Day 2 | Key Alpha Added |
| :--- | :--- | :--- | :--- |
| `we found epsilon` | 11,450 | 1,513 | Baseline |
| `we found greek` | 11,583 | 1,612 | Gamma + Vega |
| `we found theta` | 11,583 | 1,710 | Theta exit |
| `we found smile mm` | 11,583 | 1,872 | Passive MM |
| `we found vfe gold` | **12,028** | **6,328** | **VFE Hedge Opt + Side-Aware MM** |

---

## 🏆 Current Champion: `we found vfe gold.py`
**Total Round 3 PnL: 40,042**
*   **Day 0**: 15,296
*   **Day 1**: 18,418
*   **Day 2**: 6,328
*   **Benchmark**: Firmly in the "Fair" range (30k-50k) for Rust backtester equivalence.
