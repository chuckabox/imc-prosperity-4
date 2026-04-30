# Round 5 Validation Matrix

## Purpose
Provide one acceptance framework for IMC backtest, Rust backtest, and i4bt so strategy promotion decisions are objective and reproducible.

## Validation Dataset Slices
Run every candidate on:
- day 2 full
- day 3 full
- day 4 full
- day 3 first 10% (stress focus window used in prior analysis)

## Required Engines
- IMC backtest
- Rust backtest
- i4bt

No candidate is considered validated until all available engines are run or a documented blocker is recorded.

## Report Template (Per Engine x Slice)
Capture:
- `config_version`
- `total_pnl`
- `day_pnl` (for slice)
- `trade_count`
- `turnover`
- `max_abs_symbol_pos`
- `family_exposure_peak`
- `gate_reject_counts` (spread/edge/cooldown/risk)
- `violations`

## Comparison Matrix
Create a matrix table for each candidate:

- rows: `(engine, slice)`
- columns: core metrics listed above

Then compute:
- cross-engine total pnl spread
- rank consistency against other candidates
- day-level pass/fail flags

## Acceptance Gates
Candidate passes only if all conditions hold:

1. Hard constraints:
   - no symbol limit violation (`<=10`)
   - no invalid order-state transitions

2. Profitability robustness:
   - positive pnl on each validation day slice (or explicitly approved exception)
   - positive total pnl on day2+day3+day4 per engine

3. Cross-engine consistency:
   - no sign flip of total pnl across engines
   - stable top-tier rank across engines
   - bounded divergence between engines

4. Risk profile:
   - family exposure stays below configured caps
   - no repeated severe concentration spikes

## Severity Levels
- **Blocker**: any hard-limit breach or total pnl sign inconsistency
- **Major**: day-level failure in one engine but pass in others
- **Minor**: small divergence beyond target but ranking preserved

## Diagnosis Workflow (If Failing)
1. verify same config version used everywhere
2. verify same symbol iteration and tie-break logic
3. inspect gate reject counts to locate engine behavior drift
4. rerun with deterministic logging enabled
5. classify issue as model mismatch vs strategy instability

## Promotion Decision
- **Promote**: all acceptance gates pass
- **Hold**: minor issues only, no blocker/major
- **Reject**: any blocker or repeated major issue
