# Round 4 Master Findings

Date: 2026-04-28  
Scope: Consolidated findings from:
- `ROUND 4/docs/ROUND_4_INITIAL_FINDINGS.md`
- `ROUND 4/docs/alphas.md`
- `ROUND 4/docs/MANUAL_TRADING_PLAYBOOK.md`

## Why This Document Exists

This is the Round 4 single source of truth to reduce overlap, resolve contradictions, and define a practical path from research to robust live-ready execution.

---

## Executive Summary

1. `HYDROGEL_PACK` remains the most stable core edge and should stay as primary PnL anchor.
2. `VELVETFRUIT_EXTRACT` has useful short-horizon directional context from participant flow (`Mark 67` buy pressure vs `Mark 49/22` sell pressure).
3. `VEV_*` should be traded selectively, not broadly. Broad strike exposure was unstable in prior iterations.
4. Manual-playbook additions are strong: Hydrogel-as-volatility-oracle and deep-ITM synthetic framing are promising, but require guardrails and precise execution.
5. Strategy quality must be judged with robustness metrics, not single backtest totals.

---

## Consolidated Market Structure Findings

## 1) Core Underlyings

- `HYDROGEL_PACK`
  - Range observed: `9891` to `10081`
  - Mean mid: `9994.65`
  - Stdev: `34.62`
  - Practical role: primary spread-capture and inventory-managed MM instrument.

- `VELVETFRUIT_EXTRACT`
  - Range observed: `5191.5` to `5300`
  - Mean mid: `5247.65`
  - Stdev: `18.08`
  - Practical role: secondary MM edge + directional skew from flow regime.

## 2) Counterparty Flow Signal (Short-Horizon Context)

- `VELVETFRUIT_EXTRACT`:
  - `Mark 67` net strong buyer
  - `Mark 49` and `Mark 22` net strong sellers
- `HYDROGEL_PACK`:
  - `Mark 38` net buy tendency
  - `Mark 14` net sell tendency
- VEV wings (`VEV_5400`, `VEV_5500`):
  - `Mark 01` strong buyer vs `Mark 22` strong seller

Interpretation:
- Flow signal is useful for temporary quote skew and participation sizing.
- Flow signal should be decay-weighted; stale flow must not dominate decisions.

## 3) VEV Relative Value and Strike Behavior

- Intrinsic proxy reference: `max(VFE - K, 0)`.
- Strike-specific average time-value floors were observed.
- Previous broad VEV universe exposure produced unstable outcomes.
- Selective-strike approach (notably `4000/4500/5400/5500` in some versions) improved robustness.

Interpretation:
- VEV edge exists, but is conditional and execution-sensitive.
- Strike gating is mandatory.

---

## Consolidated Alpha Stack (Current)

## A1 - Hydrogel Inventory-Aware MM (`KEEP`)
- Most consistent contributor.
- Keep as baseline alpha and inventory stabilizer.

## A2 - VFE Mark-Flow Skew (`TESTING`)
- Signal quality appears real.
- Current implementation likely under-participates.
- Tune participation conservatively.

## A3 - Broad VEV Intrinsic-Floor Mispricing (`DROP`)
- Historical evidence shows instability and excess variance.
- Keep dropped unless a clearly constrained redesign is introduced.

## A4 - Selective VEV Timing (5400/5500 etc.) (`KEEP`)
- Works better as a filtered/timing layer than standalone broad options alpha.

## A5 - VFE + VEV Hedge Overlay (`NEW`)
- Promising for drawdown smoothing.
- Add only after core stack remains stable.

## Candidate to Add Explicitly

## A6 - Hydrogel Volatility Oracle for VEV (`TESTING`)
- Hypothesis: Hydrogel contains short-horizon volatility information useful for VEV pricing/skew.
- This should be treated as a distinct alpha candidate, not a return to broad VEV trading.

---

## Manual Trading Framework -> Automation Mapping

## Mode 1: Passive MM (Default)
- Instruments: Hydrogel + VFE.
- Objective: high-quality passive fills and spread capture.
- Core controls: inventory skew and quote-width adaptation.

## Mode 2: Flow-Follow (Event-Driven)
- Trigger: clustered directional activity from known participants.
- Objective: temporary quote skew, not long-horizon directional bets.

## Mode 3: Volatility/Relative-Value (Constrained)
- Trigger: strong misalignment between VEV pricing and constrained fair-value model.
- Objective: capture dislocation; no broad strike spraying.

## Mode 4: Deep-ITM Synthetic Opportunities (Execution-Sensitive)
- Instruments: e.g., `VEV_4000`, `VEV_4500`.
- Reframe from "risk-free arb" to "low directional risk with execution risk."
- Must include max unhedged exposure time and strict edge thresholds.

---

## Contradictions Resolved

1. **Broad VEV trading**
   - Resolved stance: remain `DROP` at broad-universe level.
   - Allowed exception: constrained strike subsets with strict filters.

2. **"Risk-free" synthetic language**
   - Resolved stance: do not call risk-free in production docs.
   - Correct framing: low directional risk, execution-risk dependent.

3. **Backtest totals mismatch**
   - Resolved stance: treat as different strategy versions/snapshots.
   - Requirement: all future result blocks must include strategy filename + date + config note.

---

## Robustness Standards (Promotion Gate)

A strategy moves to production candidate only if it passes all:

1. **Execution quality**
   - Acceptable fill-to-cancel ratio
   - Controlled immediate adverse selection after fills
   - Positive realized spread capture

2. **Stability**
   - Positive or resilient behavior across day slices and regimes
   - Not dependent on one isolated session

3. **Concentration control**
   - PnL not overly dominated by one product/signal/window

4. **Fragility resistance**
   - Small parameter perturbations do not invert performance sign

5. **Live realism**
   - Logic remains viable under sparse timestamps and uncertain queue position

---

## Practical Guardrails (Round 4)

- Hard inventory caps per product and per strategy mode.
- Max unhedged hold time for multi-leg or synthetic trades.
- Minimum edge threshold before taking liquidity.
- Quote widening + participation reduction after stress/adverse flow windows.
- Flow signal decay and reset rules to avoid stale overfitting.

---

## Prioritized Next Steps

1. Add `A6` as explicit testing alpha in `alphas.md` with clear acceptance metrics.
2. Define numerical trigger thresholds per mode (entry/exit/unwind) and save in one config section.
3. Add version tags to all result snapshots (`trader file`, `date`, `config delta`).
4. Run robustness batch focused on:
   - threshold perturbations
   - strike subset perturbations
   - participation-rate perturbations
5. Promote only if strategy passes robustness gate, not only total PnL.

---

## Working Principle for Round 4

Prefer a medium-edge strategy that is stable across data imperfections over a high-backtest-PnL strategy that depends on simulation artifacts.
