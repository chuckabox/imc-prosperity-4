# Round 5 Tuning Roadmap

## Objective
Tune toward maximum robust PnL under strict consistency constraints, without drifting into engine-specific overfit.

## Stage 1: Lock Invariants (Do First)
Freeze non-negotiables before any alpha tuning:
- symbol hard cap = 10
- family cap policy
- deterministic decision ordering
- baseline exit semantics (`hold=1` default)
- shared parameter schema and versioning

### Exit Criteria
- all engines run baseline config with no contract violations
- logs confirm deterministic order flow and rollover behavior

## Stage 2: Tune Shock and Spread Gates
Tune by symbol tier (not globally):
- `k_symbol` in `trigger = max(8, k_symbol * spread)`
- symbol spread caps
- cooldown lengths

Process:
1. Tune Tier A first (ROBOT/TRANSLATOR/PANEL core)
2. Apply accepted settings, then tune Tier B event-driven symbols
3. Keep Tier C disabled unless evidence changes

### Exit Criteria
- candidate improves total and min-day pnl vs baseline
- validation matrix passes without new instability

## Stage 3: Tune Pair Overlay Weight
Add pair convergence overlay on top of stable single-name core.

Tune:
- pair activation threshold
- pair sizing multiplier
- max concurrent pair overlays
- conflict resolution vs single-name entries

### Exit Criteria
- overlay increases total pnl and/or reduces variance
- no degradation of consistency gates

## Stage 4: Stress and Robustness
Run expanded validation:
- all engines, all standard slices
- sensitivity checks around top config (+/- small parameter perturbations)
- concentration and turnover checks

### Exit Criteria
- top config remains near-top under perturbation
- no blocker-level failures in validation matrix

## Stage 5: Freeze and Release Candidate
- freeze parameter file version
- produce final run manifest
- record go-live decision with evidence links

## Tuning Cadence
- one controlled parameter batch per iteration
- keep experiment log with:
  - config delta
  - rationale
  - validation outcome
- avoid parallel conflicting tuning branches unless isolated and compared through same matrix

## Anti-Overfit Rules
- never tune against only one day/slice
- require improvement across at least two independent slices
- reject configs that win via concentration spikes
- reject configs with unstable cross-engine rank behavior
