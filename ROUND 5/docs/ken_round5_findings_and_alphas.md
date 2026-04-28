# Round 5 - Independent Findings, Manual Trades, and Alpha Plan

## Scope and method
- Used only raw files in `ROUND 5/data_capsule` (`prices_*`, `trades_*`), without using prior round-5 docs.
- Built ad-hoc analysis/simulation scripts in `ROUND 5/scratch` to inspect structure and test alpha behavior.
- Focused on robust microstructure behavior rather than fitting one pretty backtest curve.

## What the raw data says
- Universe has 50 symbols grouped into 10 families x 5 variants:
  - `PEBBLES`, `SNACKPACK`, `UV_VISOR`, `GALAXY_SOUNDS`, `MICROCHIP`, `TRANSLATOR`, `SLEEP_POD`, `OXYGEN_SHAKE`, `PANEL`, `ROBOT`.
- Each day has 10,000 timestamps (`0` to `999900`, step `100`).
- Strong one-step mean-reversion in mid changes across most symbols:
  - Larger absolute mid moves have stronger next-tick reversal.
  - This appears repeatedly on day 2, day 3, and day 4.
- Highest realized volatility clusters:
  - `PEBBLES` and `MICROCHIP` consistently top risk/return opportunity.
  - `ROBOT` increases sharply on day 4.
- Trade tape (`trades_round_5_day_*.csv`) is dominated by sparse external prints and is less stable as a standalone directional predictor.

## Manual trades (day 3, first 10% ticks only)
Manual process used:
1. Watch single-tick shocks (large `dmid` magnitude).
2. Trade opposite the shock immediately.
3. Exit next tick (manual one-tick scalp).

Top candidate actions came from `ROUND 5/scratch/manual_trade_candidates_day3_first10.csv`.

Examples:
- `ts=57100`, `PEBBLES_XL`: **SELL** after +24.5 jump, next-tick roundtrip edge ~= +87 per unit.
- `ts=44500`, `PEBBLES_XL`: **BUY** after -8.0 drop, next-tick roundtrip edge ~= +79 per unit.
- `ts=87600`, `PEBBLES_XL`: **BUY** after -21.0 drop, next-tick roundtrip edge ~= +67 per unit.
- `ts=56900`, `MICROCHIP_SQUARE`: **SELL** after +10.0 jump, next-tick roundtrip edge ~= +45 per unit.

These manual actions were selected from raw order-book shock/reversal behavior, not from old strategy assumptions.

## Extracted alphas
1. **Shock Snapback Alpha (primary)**  
   - Signal: large one-tick move (`|dmid| >= trigger`)  
   - Action: fade the move  
   - Exit: next tick (short hold, lower model risk)

2. **Volatility-Weighted Product Focus (allocation alpha)**  
   - Allocate larger clip and attention to symbols with persistent shock opportunity:
   - Priority: `PEBBLES_XL`, then `MICROCHIP_SQUARE`, then other high-vol names.

3. **Cross-family diversification (risk alpha)**  
   - Keep multi-family participation to avoid one-product overfitting.
   - Avoid relying on any single symbol/family curve.

## New trader implementation
- Fresh strategy built in `ROUND 5/traders/ken/pot.py` (not reused from prior rounds).
- Behavior:
  - Detects large one-tick shock in each symbol.
  - Enters contrarian via top-of-book.
  - Closes next timestamp.
  - Resets internal state cleanly when timestamp wraps between days.

## Validation status (important)
- Rust IMC runner could not be executed on this machine because `link.exe` (MSVC linker) is unavailable.
- Local conservative simulator results are currently negative after spread costs:
  - see `ROUND 5/scratch/sim_round5_results.json`.
- So this branch now contains:
  - raw-data findings,
  - manual trade playbook,
  - and a clean base strategy implementation ready for your own IMC backtest environment.

## Next tuning plan toward your targets
- Tune only with constraints:
  - improve day-3 first 10% pnl to `>= 20k`,
  - preserve day-2/day-4 pnl,
  - push 3-day total toward 6 digits.
- Practical next knobs:
  - per-symbol trigger (`TRIGGER_MOVE`) map instead of global,
  - asymmetric clips for `PEBBLES_XL` and `MICROCHIP_SQUARE`,
  - dynamic hold (1 vs 2 ticks) when rebound remains strong,
  - spread-aware entry filter to skip expensive shocks.
