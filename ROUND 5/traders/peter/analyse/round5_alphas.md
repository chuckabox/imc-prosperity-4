# Round 5 Alpha Catalogue (Peter)

Source artifacts:
- `ROUND 5/data_capsule/prices_round_5_day_{2,3,4}.csv` (raw)
- `ROUND 5/docs/pair_dashboards/summary/top_pairs_by_signal_quality.csv`
- `ROUND 5/docs/pair_dashboards/charts/*__spread_dashboard.png`
- `ROUND 5/docs/item_over_time/summary/top_symbols_by_signal_quality.csv`
- `ROUND 5/docs/item_over_time/charts_per_item/*__item_over_time.png`
- `ROUND 5/docs/item_over_time/charts_family_et/*_et_signal_panel_generated.png`
- `ROUND 5/docs/item_over_time/series_csv/*_et_signal_series_generated.csv`
- Discord screenshot: `ROUND 5/docs/Screenshot 2026-04-28 231708.png`
  ("hard coded values for mean reversion and use ITM options as leveraged positions")

## Universe structure

50 symbols organised into 10 families x 5 variants:
`PEBBLES, SNACKPACK, UV_VISOR, GALAXY_SOUNDS, MICROCHIP, TRANSLATOR, SLEEP_POD, OXYGEN_SHAKE, PANEL, ROBOT`.

Each family has a `underlying_mid -> theo` model and per-variant residual `e_t`. Every symbol's
`rev_corr_et_next_de` is negative (-0.07 to -0.13), so the residual `e_t` mean-reverts on the
next tick across the entire universe.

---

## Alpha 1 - Tight-spread pair convergence (primary)

What: trade the spread `s = mid_A - mid_B` between two same-family variants whose spreads stay
tight at the same time. When both legs are simultaneously tight, the dashboards show large mean
shifts in the 20-step forward-return distribution and monotonically rising cumulative-return
curves on Day 2, Day 3, and Day 4.

Whitelist (score >= 1500, `tight_rate >= 0.8`, all-day positive cum return):

| Pair | Family | Pair quality | Signal ret/tick | tight_rate |
|---|---|---|---|---|
| TRANSLATOR_ASTRO_BLACK / TRANSLATOR_GRAPHITE_MIST | TRANSLATOR | 12970 | 2.11 | 1.00 |
| MICROCHIP_OVAL / MICROCHIP_SQUARE | MICROCHIP | 9019 | 2.64 | 0.55 |
| SLEEP_POD_NYLON / SLEEP_POD_POLYESTER | SLEEP_POD | 7436 | 1.21 | 1.00 |
| MICROCHIP_CIRCLE / MICROCHIP_OVAL | MICROCHIP | 7361 | 1.20 | 1.00 |
| ROBOT_DISHES / ROBOT_VACUUMING | ROBOT | 7303 | 1.19 | 1.00 |
| TRANSLATOR_ECLIPSE_CHARCOAL / TRANSLATOR_GRAPHITE_MIST | TRANSLATOR | 7161 | 1.16 | 1.00 |
| ROBOT_LAUNDRY / ROBOT_VACUUMING | ROBOT | 6672 | 1.08 | 1.00 |
| TRANSLATOR_GRAPHITE_MIST / TRANSLATOR_VOID_BLUE | TRANSLATOR | 5500 | 0.89 | 1.00 |
| ROBOT_LAUNDRY / ROBOT_MOPPING | ROBOT | 5311 | 0.86 | 1.00 |
| MICROCHIP_CIRCLE / MICROCHIP_RECTANGLE | MICROCHIP | 5087 | 0.83 | 1.00 |
| PANEL_2X2 / PANEL_2X4 | PANEL | 4443 | 0.72 | 1.00 |
| MICROCHIP_RECTANGLE / MICROCHIP_SQUARE | MICROCHIP | 4236 | 1.24 | 0.55 |
| OXYGEN_SHAKE_CHOCOLATE / OXYGEN_SHAKE_EVENING_BREATH | OXYGEN_SHAKE | 4199 | 0.98 | 0.69 |
| TRANSLATOR_GRAPHITE_MIST / TRANSLATOR_SPACE_GRAY | TRANSLATOR | 3737 | 0.61 | 1.00 |
| MICROCHIP_RECTANGLE / MICROCHIP_TRIANGLE | MICROCHIP | 3300 | 0.54 | 1.00 |
| TRANSLATOR_ASTRO_BLACK / TRANSLATOR_VOID_BLUE | TRANSLATOR | 3267 | 0.53 | 1.00 |
| PANEL_1X2 / PANEL_2X4 | PANEL | 3206 | 0.62 | 0.83 |
| SLEEP_POD_NYLON / SLEEP_POD_SUEDE | SLEEP_POD | 2252 | 0.36 | 1.00 |
| MICROCHIP_CIRCLE / MICROCHIP_TRIANGLE | MICROCHIP | 1663 | 0.27 | 1.00 |

Rule:
- Maintain rolling `mu, sigma` of `s` per pair (e.g. EWMA over ~200 ticks).
- Gate: only fire when both legs have spread `<= 12`.
- Entry: when `(s - mu)/sigma >= z_in` (e.g. 1.5), short A / long B; symmetric for the other side.
- Exit: when `|s - mu|/sigma <= z_out` (e.g. 0.3) or 20 ticks, whichever first.
- Family caps: at most 2 simultaneous pairs per family (MICROCHIP otherwise dominates).

Anti-pairs (same family but cumulative return drifts, do NOT converge):
- All `SLEEP_POD_*__SLEEP_POD_LAMB_WOOL` / `_COTTON` / `_SUEDE` except `NYLON__POLYESTER` and `NYLON__SUEDE`.
- `PANEL_1X4__*` against the larger panels (PANEL_1X4 is a structural diverger).
- `TRANSLATOR_ASTRO_BLACK__TRANSLATOR_SPACE_GRAY`, `TRANSLATOR_ECLIPSE_CHARCOAL__TRANSLATOR_VOID_BLUE`.
- `ROBOT_DISHES__ROBOT_MOPPING`, `ROBOT_IRONING__ROBOT_LAUNDRY`, `ROBOT_MOPPING__ROBOT_VACUUMING`.
- `MICROCHIP_OVAL__MICROCHIP_RECTANGLE`, `MICROCHIP_OVAL__MICROCHIP_TRIANGLE`, `MICROCHIP_CIRCLE__MICROCHIP_SQUARE`.
- All `OXYGEN_SHAKE__MORNING_BREATH` / `__MINT` divergers.

These are explicitly excluded.

---

## Alpha 2 - Per-symbol residual `e_t` reversion (secondary)

What: every symbol mean-reverts its residual on the next tick. Signal quality score in
`top_symbols_by_signal_quality.csv` is `(-rev_corr) * f(spread, tail_rate)`, so the ranking
already nets out trading cost. Only the upper third clears the spread reliably.

Whitelist (signal_quality_score >= 0.13, median_spread <= 9):

| Symbol | Median spread | rev corr | Quality |
|---|---|---|---|
| ROBOT_DISHES | 7 | -0.134 | 0.254 |
| ROBOT_IRONING | 6 | -0.099 | 0.213 |
| ROBOT_VACUUMING | 7 | -0.087 | 0.173 |
| MICROCHIP_OVAL | 8 | -0.092 | 0.165 |
| MICROCHIP_RECTANGLE | 8 | -0.094 | 0.162 |
| ROBOT_LAUNDRY | 7 | -0.084 | 0.159 |
| ROBOT_MOPPING | 8 | -0.092 | 0.156 |
| MICROCHIP_CIRCLE | 8 | -0.090 | 0.152 |
| TRANSLATOR_ASTRO_BLACK | 8 | -0.086 | 0.151 |
| PANEL_1X4 | 8 | -0.085 | 0.148 |
| MICROCHIP_TRIANGLE | 9 | -0.091 | 0.142 |
| PEBBLES_XS | 9 | -0.092 | 0.140 |
| PANEL_2X2 | 9 | -0.089 | 0.135 |
| TRANSLATOR_ECLIPSE_CHARCOAL | 9 | -0.091 | 0.135 |
| TRANSLATOR_GRAPHITE_MIST | 9 | -0.088 | 0.134 |
| PANEL_4X4 | 9 | -0.089 | 0.132 |
| TRANSLATOR_SPACE_GRAY | 9 | -0.089 | 0.132 |
| SLEEP_POD_NYLON | 9 | -0.088 | 0.131 |

Blacklist (score < 0 or median spread >= 14): SNACKPACK_*, PEBBLES_XL, UV_VISOR_*, GALAXY_SOUNDS_*,
OXYGEN_SHAKE_GARLIC.

Rule (same primitive Ken validated as `reversal@8 hold=1..3`):
- Track `last_mid[s]`.
- On each tick compute `d_mid = mid - last_mid`.
- If `|d_mid| >= max(8, 1.2 * spread)`, take the opposite side.
- Exit on the next tick. Optional 2-tick hold for `MICROCHIP_*` and `ROBOT_*` (their alpha
  edges in the sweep stay positive at hold=2-3).

---

## Alpha 3 - ITM leg sizing (the screenshot hint)

What: per-item charts show every variant in a family shares the same residual shape but trades
at very different mid-price levels. The high-notional leg behaves like an in-the-money option on
the family signal: same residual delta, larger price * size = bigger PnL per unit of correct direction.

Family -> high-notional expression leg (from `average_per_product.png`, days 2-4 averages):

| Family | Signal leg(s) (low spread) | Expression leg (high notional, leveraged) |
|---|---|---|
| PEBBLES | PEBBLES_XS, PEBBLES_S | PEBBLES_XL |
| MICROCHIP | MICROCHIP_OVAL, MICROCHIP_RECTANGLE, MICROCHIP_CIRCLE | MICROCHIP_SQUARE |
| ROBOT | ROBOT_DISHES, ROBOT_VACUUMING | ROBOT_DISHES (already top) |
| TRANSLATOR | TRANSLATOR_ASTRO_BLACK, TRANSLATOR_GRAPHITE_MIST | TRANSLATOR_VOID_BLUE |
| SLEEP_POD | SLEEP_POD_NYLON | SLEEP_POD_POLYESTER |
| PANEL | PANEL_2X2 | PANEL_2X4 |
| OXYGEN_SHAKE | OXYGEN_SHAKE_CHOCOLATE | OXYGEN_SHAKE_EVENING_BREATH |

Rule:
- Compute the family residual `e_t` only off the cheap-spread leg.
- When `|e_t|` exceeds threshold, take the contrarian position **partly on the cheap leg and
  partly on the expression leg**, scaled to position limit (see Alpha 4).
- This is the "ITM options as leveraged positions" pattern from the discord clue: the cheap leg
  generates the signal, the expensive leg amplifies the PnL.

---

## Alpha 4 - Position-limit aware allocator

What: cap per-family exposure so MICROCHIP (4 entries in the top-20 pair list) does not soak up
the whole book.

Rule:
- Per-family hard limits (re-using ken/pot.py values, lightly tuned):
  - PEBBLES 45, MICROCHIP 40, ROBOT 35, OXYGEN_SHAKE 30, PANEL 30,
    GALAXY_SOUNDS 25, TRANSLATOR 25, SLEEP_POD 25, UV_VISOR 25, SNACKPACK 20.
- Per-pair clip = 5 default, doubled to 10 for the top 5 quality scores.
- Per-symbol single-leg clip (Alpha 2) = 5 default, scaled by `min(2, |d_mid| / max(8, spread))`.
- Cross-family diversification: when in doubt, prefer signals from different families to keep the
  book uncorrelated.

---

## Things to skip entirely

- **GALAXY_SOUNDS family** - tight_rate ~ 0.03 across every pair. Edge exists per tick, but the
  gate almost never fires; not worth the symbol slot.
- **SNACKPACK family** - signal quality < 0 across all variants, median spread 16-18.
- **UV_VISOR most pairs** - only `AMBER__ORANGE` even mildly tradable; the rest are 0.03 tight_rate.
- **Trade tape (`trades_round_5_day_*.csv`)** - dominated by sparse external prints; not a stable
  directional predictor on its own.

---

## Implementation plan -> `peter/trader1.py`

1. Maintain rolling EWMA mean/var of pair spreads per whitelisted pair.
2. Per-tick loop:
   - Build mids and spreads per symbol.
   - For each whitelisted pair: if both legs tight, compute z = (s - mu)/sigma.
     If `|z| >= z_in` and not already in the position, enter (short rich, long cheap),
     scale into expression leg per Alpha 3.
   - For each whitelisted symbol: if `|d_mid|` shock >= threshold, fade for 1 tick.
   - For each open pair / single-leg position, exit on `|z| <= z_out` or after `MAX_HOLD` ticks.
3. Reset state on day rollover (`state.timestamp` decreases when a new day starts).
4. Persist `last_mid`, `pair_state`, `entry_ts`, `day_idx` in `traderData` JSON.
