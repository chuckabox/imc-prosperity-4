# Round 5 Execution Sweep

Signal fixed to robust alpha: `reversal` with threshold `8.0`.
Swept execution knobs: hold, spread cap, size scale, taker/passive mix.

## Result
- In this conservative proxy model, **no robust positive-all-days configuration** was found in the tested grid.
- Best overall proxy is still negative, which means execution alone (with this signal and these assumptions) is insufficient.

Best config (overall):
- hold: 1
- spread_max: 8
- size_scale: 0.15
- taker_frac: 0.2
- day3 first 10% pnl proxy: -80522.66
- day2/day3/day4 pnl proxy: -549777.73 / -843776.10 / -137447.17
- total 3 days pnl proxy: -1531001.00

Outputs:
- `ROUND 5/scratch/round5_execution_sweep.csv`
- `ROUND 5/scratch/round5_execution_sweep_top30.json`
- `ROUND 5/scratch/round5_execution_sweep_robust.csv`

## Practical takeaway
- Keep `reversal@8` as a signal primitive, but do not deploy it as standalone strategy.
- Next step is **signal stacking** (reversal + product whitelist + session gating + event filters) before further execution tuning.
