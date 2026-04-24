# Round 3 traders

Starter trader: [`ken/trader_ken_v1.py`](ken/trader_ken_v1.py).

Three independent modules, each toggleable via a class constant:

| Module | Flag | Responsibility |
|---|---|---|
| HYDROGEL MM | `ENABLE_HYDROGEL` | Mean-reversion market-making around ~9,995 |
| VEV book | `ENABLE_VEV` | Buy options where IV < model σ (0.018/day) |
| VFE delta hedge | `ENABLE_HEDGE` | Keep portfolio delta ≈ 0 by trading VFE |

**To A/B test contributions** — flip one flag off at a time and backtest.

## Running

From the repo root:

```bash
# Full trader
python "ROUND 3/scratch/vev_iv_scan.py"
python "ROUND 3/scratch/hydrogel_stats.py"

# Backtest (once harness is wired for R3)
python tools/run_rust_backtester.py "ROUND 3/traders/ken/trader_ken_v1.py" --round 3
```

## Known knobs (tune in backtest)

- `VEV_SIGMA_DAY` — model vol. Start 0.018 (conservative vs 0.0215 realised).
  Lower → more aggressive edge threshold. Higher → fewer but safer trades.
- `VEV_MIN_EDGE` — XIRECs of edge before we enter. Start 4.
- `HEDGE_DEAD_BAND` — how off-delta before we rebalance. Start 10 (VFE units).
- `HP_ANCHOR` — HYDROGEL fair value anchor. Capsule mean is 9,990.8; anchor
  9,995 biases slightly to the upside given the mild drift on the last day.

## Unverified at starter time

- **Per-product position limits** (`LIMITS` dict). Guessed 80 for
  HYDROGEL/VFE (R2 value) and 60 for each VEV. First live tick should
  query `state` and log any constraint violation.
- **How many live days** the round will run. Affects late-TTE gamma sizing.
- **The `La_trahison_des_images.png`** file inside the data capsule —
  possibly a puzzle/hint. Open it manually and check against manual-trade
  docs.
