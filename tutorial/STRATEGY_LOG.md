# 📈 IMC Prosperity 4: Strategy Evolution Log

This document tracks the iterative improvements made since commit `b12b4af`, documenting the logic shifts, PnL benchmarks, and 'Alpha' discovered.

---

## 🏛️ Version 1: Legacy Baseline (Commit `b12b4af`)
- **File**: `trader_v1_legacy.py`
- **Logic**: Simple mid-price market making for `KELP`, `RESIN`, and `SQUID_INK`.
- **Pros**: Handles multiple products simultaneously; includes basic pennying.
- **Cons**: No predictive logic; uses hardcoded spreads (±2 or ±4); fails to handle trend shifts (drift).
- **Performance**: Low stability; high risk of being "picked off" by toxic flow.

## 🟡 Version 2: Agent Polynomial MM
- **File**: `trader_v2_poly_mm.py`
- **Logic**: 2nd-order polynomial fair value for `EMERALDS` and `TOMATOES`.
- **Pros**: Introduced **Drift Prediction**; reaction speed improved significantly.
- **Cons**: No volatility awareness; over-trades in noisy markets; static pennying logic.
- **Performance**: ~$1,100 PnL baseline.

## 🚀 Version 3: The 'Golden' Engine (Current)
- **File**: `trader_v3_golden.py`
- **Logic**: Volatility Z-scores (1.5x), Dynamic Squashing, and 95% Emerald Anchoring.
- **Pros**: **Risk Management**: Only enters trades with high edge relative to volatility; **Inventory Control**: Aggressively squashes positions back to neutral.
- **Cons**: Conservative; might miss small-edge fills during low-volatility periods.
- **Performance**: **$1,556 (Day -1)** / **$1,133 (Day -2)**.
