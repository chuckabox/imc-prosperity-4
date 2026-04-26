# Round 4 Alpha Log

This file tracks candidate alphas and status for quick iteration.

## Legend

- `NEW`: not yet tested
- `TESTING`: in backtest loop
- `KEEP`: survives robustness checks
- `DROP`: remove from production candidate

## Alpha Table

| ID | Product(s) | Idea | Trigger / Signal | Risk | Status | Notes |
|---|---|---|---|---|---|---|
| A1 | HYDROGEL_PACK | Inventory-aware spread MM around rolling mid | Best bid/ask + inventory skew | Inventory drift in trend | KEEP | Strong contributor in initial Round 4 run |
| A2 | VELVETFRUIT_EXTRACT | Mark-flow skew | Mark 67 buy dominance vs Mark 49/22 sell dominance | Flow regime change | TESTING | Current implementation too conservative (near-zero activity) |
| A3 | VEV_5000..VEV_5500 | Intrinsic + strike floor mispricing | `mid - (max(VFE-K,0)+floor[K])` | Vol regime shift | DROP | Initial broad-strike version caused large losses in 5000/5100/5200 |
| A4 | VEV_5400/5500 | Counterparty-assisted timing | Mark 01 vs Mark 22 imbalance | Overfit to historical IDs | KEEP | Reduced-size constrained-strike version is stable |
| A5 | VFE + VEV basket | Delta-style hedge overlay | Net VEV exposure vs VFE drift | Hedge slippage | NEW | Not enabled yet; candidate for next iteration |

## Guardrails

- Hard cap DD per product before widening quotes.
- Track worst-day and concentration in every batch.
- Prefer stable medium-edge alpha over high-variance spikes.

## Latest Backtest Snapshot (`table.py`)

- Dataset: `round4` (day1-day3)
- Total PnL: `+18,035.0`
- Day PnL: `D+1 +10,796.0`, `D+2 +1,074.0`, `D+3 +6,165.0`
- Main drivers: `HYDROGEL_PACK +15,164.0`, `VELVETFRUIT_EXTRACT +3,239.5`
- Minor drag: `VEV_4000 -471.5`

Tuning notes:

- Added opportunistic take-edge logic around fair value for Hydrogel and VFE.
- Added light momentum tilt to fair-value skew.
- Kept constrained VEV strike universe to avoid previous losses in 5000/5100/5200.

