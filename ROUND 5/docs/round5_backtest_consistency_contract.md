# Round 5 Backtest Consistency Contract

## Purpose
Define non-negotiable rules that keep IMC backtest, Rust backtest, and i4bt results comparable and reproducible.

## Contract Rules

## 1) Hard Trading Constraints
- Per-symbol position limit is fixed to `10`.
- Any strategy candidate violating `|pos| <= 10` in any engine is rejected.
- Family caps are soft risk limits but must be identical in all engines when enabled.

## 2) Shared Parameter Source
- Maintain one canonical parameter file (example: `ROUND 5/traders/config/round5_params.json`).
- No engine-specific forks of thresholds, spreads, hold ticks, or clip sizes.
- Any parameter change must increment config version and be logged in validation results.

## 3) Decision Determinism
- Stable symbol iteration order (lexicographic).
- Stable tie-break ordering for equal alpha scores.
- Stable execution preference ordering (passive candidate first, then taker fallback).
- Deterministic cooldown updates and state resets at day rollover.

## 4) Time and State Semantics
- Tick horizon and timestamp step must be treated consistently across engines.
- Day rollover detection must reset equivalent state fields:
  - `entry_ts`
  - per-symbol cooldown markers
  - optional short-horizon signal buffers

## 5) Fill/Cost Normalization
- Keep a common reporting contract for:
  - entry spread
  - exit spread
  - round-trip cost estimate
  - fill ratio assumptions (if approximated)
- If one engine cannot model a field natively, compute a comparable proxy and label it.

## 6) Metrics Schema (Required Fields)
Every run output must include:

- `engine` (`imc`, `rust`, `i4bt`)
- `config_version`
- `dataset_slice`
- `total_pnl`
- `day2_pnl`, `day3_pnl`, `day4_pnl`
- `turnover`
- `max_abs_symbol_pos`
- `family_exposure_peak`
- `trade_count`
- `violations` (array)

## 7) Divergence Tolerance and No-Ship Rules
Reject candidate if any of these occur:

- Hard-limit violation in any engine
- Sign mismatch of `total_pnl` across engines
- Rank instability: candidate loses top-tier rank in more than one engine
- Day-level instability: one engine passes day-level positivity while another fails by large margin

Use a practical tolerance target:

- Total PnL relative spread between engines should remain within a bounded window (e.g. `<= 20%`) for accepted configs.
- If outside tolerance, run diagnosis before further tuning.

## 8) Run Manifest Requirements
Each validation batch must log:

- commit hash
- parameter version
- runner command lines
- run timestamp
- environment note (compiler/runtime version)

## 9) Change Control
- Do not merge strategy updates unless consistency checks pass.
- Any exception requires explicit written waiver in validation notes and rationale.
