# Round 5 Trader Master Plan

## Goal
Maximize Round 5 total PnL while keeping behavior consistent across IMC backtest, Rust backtest, and i4bt. The strategy must respect hard exchange constraints and avoid brittle, environment-specific tuning.

## Objective Function
Use this as the tuning objective for all parameter searches:

- Primary: maximize `total_pnl_day2_day3_day4`
- Secondary: maximize `min(day2_pnl, day3_pnl, day4_pnl)` to avoid one-day overfit
- Penalty: reduce score for high concentration and unstable fills

Suggested score:

`score = total_pnl + 0.5 * min_day_pnl - 0.2 * pnl_std - 0.1 * inventory_stress_penalty`

## Evidence Baseline
All design choices below are grounded in existing Round 5 outputs:

- `ken_round5_findings_and_alphas.md`: shock-snapback pattern and manual reversions
- `ken_round5_alpha_sweep.md`: robust winners around reversal threshold `8` with short hold
- `ken_round5_execution_sweep.md`: signal alone cannot clear cost without additional filters
- `item_over_time/summary/top_symbols_by_signal_quality.csv`: symbol-level quality and spread regime
- `pair_dashboards/summary/top_pairs_by_signal_quality.csv`: pair-level convergence quality and tightness
- `volatility.md`: family tiering and risk concentration lessons
- `algo.md`: hard rule `|position_per_symbol| <= 10`

## Strategy Architecture
The trader runs as layered modules:

1. Signal extraction (single-symbol shock + pair convergence)
2. Regime filter (whitelist + spread/tightness checks)
3. Alpha scoring and ranking
4. Execution planner (passive-first with controlled crossing)
5. Risk manager (symbol and family caps)
6. State and telemetry

## Alpha Stack
- Primary alpha: one-tick shock fade with dynamic trigger `max(8, k_symbol * spread)`
- Secondary alpha: selected pair convergence overlay for high-quality, frequently tight pairs
- Optional alpha: high-volatility event fades (strict spread and cooldown rules)

## Execution Policy
- Prefer passive entry when queue risk is acceptable
- Use taker fallback only if expected reversion edge exceeds round-trip cost buffer
- Deterministic exit policy:
  - default `hold = 1`
  - allow `hold = 2` only with explicit continuation confirmation and no risk-cap breach

## Risk Policy
- Hard symbol cap: `|pos[symbol]| <= 10`
- Family caps below naive sum of symbol caps to reduce correlated drawdown
- Concurrency limits: bound open legs per family and globally
- Cooldowns to avoid repeated entries in one local shock cluster

## Cross-Backtest Determinism
- One shared parameter bundle
- One shared decision ordering (stable symbol iteration, stable tie-breaks)
- Common interpretation of fills/fees/slippage assumptions in reporting layer

## Deliverables Map
This master plan is implemented by:

- `round5_backtest_consistency_contract.md`
- `round5_alpha_selection.md`
- `round5_execution_playbook.md`
- `round5_validation_matrix.md`
- `round5_tuning_roadmap.md`

## Go-Live Checklist
All items must pass before final submission:

- [ ] Symbol limits never exceed 10 in any engine
- [ ] Same parameter file used for IMC, Rust, i4bt runs
- [ ] Validation matrix acceptance gates pass on latest candidate
- [ ] Top 3 configs keep same rank ordering (or near-equivalent) across engines
- [ ] No single family contributes more than configured concentration cap
- [ ] Day-level PnL is non-negative for validation slices
