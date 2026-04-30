# Round 5 Execution Playbook

## Goal
Convert alpha signals into executable orders while preserving edge after spread costs and maintaining deterministic behavior across backtest engines.

## Entry Logic

## 1) Signal Preconditions
- shock-fade entry candidate exists (`abs(d_mid) >= trigger`)
- symbol or pair is enabled by alpha tier policy
- no active cooldown
- current position allows entry under symbol and family caps

## 2) Trigger Formula
- symbol shock trigger:
  - `trigger_symbol = max(8, k_symbol * spread)`
- pair shock trigger:
  - use pair z-score or spread delta threshold from tuned pair config

## 3) Spread Gate
- reject entry when `spread > spread_cap_symbol`
- for pair overlay, reject when either leg fails spread gate

## 4) Edge Gate
- reject taker entry unless:
  - expected reversion >= round-trip cost + safety buffer

## 5) Cooldown Gate
- enforce per-symbol cooldown after exit to avoid overtrading clustered noise

## Order Priority
Apply this deterministic order:
1. risk-reducing exits
2. pending protective reductions (if caps approached)
3. Tier A entries
4. Tier B entries
5. Tier B event-only entries

Within each bucket, sort by:
- higher alpha score first
- lower spread second
- lexicographic symbol/pair as final tie-break

## Exit Logic
- default exit: close after `hold = 1` tick
- optional extension to `hold = 2` only if:
  - signal continuation rule is positive
  - no risk/cap pressure
  - spread remains within safe bounds
- force exit immediately on risk breach condition

## Position Sizing
Recommended sizing formula:

`size = clamp(min_size, max_size, base_size * magnitude_scale * quality_scale * inv_scale)`

Where:
- `magnitude_scale`: shock magnitude relative to trigger
- `quality_scale`: normalized from signal quality bucket
- `inv_scale`: decreases as family/symbol inventory utilization rises
- `max_size` must never violate per-symbol hard cap

## Family Exposure Control
- maintain per-family notional/position utilization trackers
- deny new entries if family exposure cap exceeded
- prioritize reducing exposure in highest-correlated families first

## Pair Overlay Rules
- activate only for pre-approved pairs
- if one leg becomes non-tradable (spread/liq), cancel new pair entries
- avoid mixing pair overlay and aggressive single-name entries on same symbols in same tick

## Cancellation Behavior
- cancel stale passive orders after timeout window
- cancel if signal invalidates before fill
- cancel if risk budget consumed by higher-priority orders

## Safety Guards
- never place order that can exceed symbol limit 10 after fill
- block duplicate entry orders for same symbol in same tick
- enforce day-roll reset of transient execution state

## Telemetry Requirements
Log per tick:
- candidate signals considered
- rejects by gate type (spread, edge, cooldown, risk)
- submitted orders by bucket
- realized holding duration per trade
