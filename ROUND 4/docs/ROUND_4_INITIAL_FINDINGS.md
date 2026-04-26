# Round 4 Initial Findings (Bootstrap)

Date: 2026-04-27

Scope analyzed:

- `ROUND 4/data_capsule/prices_round_4_day_1.csv`
- `ROUND 4/data_capsule/prices_round_4_day_2.csv`
- `ROUND 4/data_capsule/prices_round_4_day_3.csv`
- `ROUND 4/data_capsule/trades_round_4_day_1.csv`
- `ROUND 4/data_capsule/trades_round_4_day_2.csv`
- `ROUND 4/data_capsule/trades_round_4_day_3.csv`

## Product Summary

- `HYDROGEL_PACK` (Protein Snackpacks equivalent in this dataset)
  - Mid range: 9891 to 10081
  - Mean mid: 9994.65
  - Stdev: 34.62
- `VELVETFRUIT_EXTRACT`
  - Mid range: 5191.5 to 5300
  - Mean mid: 5247.65
  - Stdev: 18.08

## Counterparty (Mark) Flow Signals

Net signed flow (buy positive, sell negative) from historical trades:

- `HYDROGEL_PACK`
  - Mark 38: +34
  - Mark 14: -44
  - Mark 22: +10
- `VELVETFRUIT_EXTRACT`
  - Mark 67: +1510 (dominant buyer)
  - Mark 49: -956 (dominant seller)
  - Mark 22: -551 (large seller)
- VEV wings (`VEV_5400`, `VEV_5500`)
  - Mark 01: strong buyer
  - Mark 22: strong seller

Practical use:

- Treat Mark 67 VFE buying pressure as short-horizon bullish context.
- Treat Mark 49/22 VFE selling waves as mean-reversion/downward pressure windows.
- For high-strike VEVs, Mark 01 vs Mark 22 flow can be used as directional timing filter.

## VEV Relative Value Notes

Using VFE as the underlying, option intrinsic proxy `max(VFE - K, 0)`:

- Near ITM:
  - `VEV_5000`: average time value ~3.4
  - `VEV_5100`: average time value ~12.2
  - `VEV_5200`: average time value ~36.3
  - `VEV_5300`: average time value ~53.7
- Higher strikes still show positive floor:
  - `VEV_5400`: ~18.6
  - `VEV_5500`: ~7.35
  - `VEV_6000`, `VEV_6500`: ~0.5 baseline

Initial implication:

- Use a strike-specific time-value floor in fair-value estimates.
- `VEV_5300` appears systematically rich in time value; good candidate for relative-value sell when overstretched.

## Day-1 Alpha Priorities

1. Core market-making on `HYDROGEL_PACK` and `VELVETFRUIT_EXTRACT` with inventory-aware skew.
2. Add Mark-flow micro-signal to skew quotes for VFE.
3. Trade `VEV_*` using intrinsic + strike floor, with tighter thresholds around 5000-5500 strikes.
4. Keep conservative position limits on first deployment; widen after live validation.

## Bootstrap Backtest Result (Current `table.py`)

Command used:

`cargo run --release -- --dataset round4 --trader "C:/Users/ductv/Desktop/Projects/imc prosperity/imc-prosperity-4/ROUND 4/traders/ken/table.py" --products summary`

Result summary:

- Total PnL: `+15,571.5`
- D+1: `+10,819.5`
- D+2: `+736.0`
- D+3: `+4,016.0`

Product decomposition:

- `HYDROGEL_PACK`: `+15,940.0` (primary edge)
- `VEV_4000`: `-471.5`
- `VEV_5400`: `+90.5`
- `VEV_5500`: `+12.5`

Implementation note:

- A previous broader VEV universe version was negative overall.
- Restricting VEV trading to selected strikes (`4000/4500/5400/5500`) and using wider thresholds materially improved robustness.

## Known Limitations

- This is bootstrap analysis from day 1-3 history only.
- No direct latency or fill-priority model in this note.
- Counterparty signals should be decay-weighted in live logic to avoid stale flow overfitting.

