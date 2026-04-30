# Sid traders

## Goal

Capture the medium-vol band that's untapped between Ken's high-vol shock-fade
(`MATH1061.py` on PEBBLES_XL / MICROCHIP_OVAL) and Peter's low-vol passive MM
(`kingking.py` on ROBOT / TRANSLATOR / PANEL).

Per `ROUND 5/scratch/sid_target_picks.md`, the unclaimed sweet spot is:

| Product | abs_dmid | spread | shock_14 | edge | mid_std |
|---|---|---|---|---|---|
| MICROCHIP_TRIANGLE | 11.5 | 9 | 10,357 | 7.00 | 833 |
| MICROCHIP_RECTANGLE | 10.4 | 8 | 8,815 | 6.42 | 752 |

Both have more shock-fade opportunities than MICROCHIP_OVAL (7,675 shocks at
threshold 14) and lower realized vol than PEBBLES_XL (mid_std 1776).

## Files

- `sid_v1.py` — shock-fade starter, two products only. Same skeleton as
  `MATH1061.py` but with per-product thresholds, position limit clamped to 10
  (algo.md rule), and no late-session skip.

## Iteration plan

1. Backtest `sid_v1` to validate basic profit signal.
2. Inspect logs for: shock trigger frequency, hit rate, P&L per fade.
3. Tune triggers / hold lengths per product.
4. Add PEBBLES_M, PEBBLES_S, PEBBLES_L (different family — uncorrelated alpha).
5. Stress with day_4 data.
6. Once stable, fold in MICROCHIP_SQUARE (highest edge in mid-vol, but
   mid_std 1830 = volatile).

## Config (sid_v1)

```python
PARAMS = {
    "MICROCHIP_RECTANGLE": {"trigger": 12.0, "big_shock": 20.0, "max_spread": 11},
    "MICROCHIP_TRIANGLE":  {"trigger": 13.0, "big_shock": 22.0, "max_spread": 12},
}
POS_LIMIT = 10
HOLD_DEFAULT = 1
HOLD_BIG = 2
COOLDOWN_TICKS = 4
ENTRY_SIZE_DEFAULT = 3
ENTRY_SIZE_BIG = 5
```

## What I want from logs

- Total trades per product
- Realized P&L per product
- Avg fade-entry move size vs avg exit P&L
- Distribution of d_mid that triggered fades
- Cooldown / spread / position-cap rejections
- Any "stuck position" cases (entered but couldn't exit within hold)
