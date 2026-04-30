# Round 5 - Product Volatility Tier List

Source artifacts:
- `ROUND 5/docs/algo.md` (challenge brief, position limits)
- `ROUND 5/docs/pair_dashboards/summary/top_pairs_by_signal_quality.csv`
- `ROUND 5/docs/item_over_time/summary/top_symbols_by_signal_quality.csv`
- `ROUND 5/docs/item_over_time/charts_per_item/*__item_over_time.png`
- `ROUND 5/docs/item_over_time/charts_family_et/*_et_signal_panel_generated.png`
- `ROUND 5/docs/ken_round5_findings_and_alphas.md`

## Hard constraint from algo.md

**Position limit = 10 per product** across all 50 products. Any trader using
limits above 10 (trader100, trader4) is busting this. Quote, take, and
inventory-skew sizing must all respect `|pos| <= 10`.

50 products = 10 families x 5 variants:
PEBBLES, SNACKPACK, UV_VISOR, GALAXY_SOUNDS, MICROCHIP, TRANSLATOR,
SLEEP_POD, OXYGEN_SHAKE, PANEL, ROBOT.

algo.md hint: "some offer more market inefficiencies than others. In certain
groups, strong patterns are embedded in the price movements." Translation:
not every family has tradable alpha. Pick where the pattern is real.

---

## Tier 1 - LOW VOL, strong signal (aim here for stability)

### ROBOT (Domestic Robots)
- Median spread 6-8 (cheapest in universe).
- Signal quality 0.15-0.25 (top of `top_symbols_by_signal_quality.csv`).
- All within-family pairs tight_rate = 1.0 - signal fires every tick.
- Mid prices stable across day 2/3/4, no runaway trend.
- Best names: `ROBOT_DISHES` (q=0.254), `ROBOT_IRONING` (0.213),
  `ROBOT_VACUUMING` (0.173), `ROBOT_LAUNDRY` (0.159), `ROBOT_MOPPING` (0.156).
- Anti-pairs to avoid: `ROBOT_DISHES__ROBOT_MOPPING`,
  `ROBOT_IRONING__ROBOT_LAUNDRY`, `ROBOT_MOPPING__ROBOT_VACUUMING`.

### TRANSLATOR (Instant Translators)
- Median spread 8-9.
- All within-family pairs tight_rate = 1.0 - predictable execution regime.
- Top pair in whole universe: `TRANSLATOR_ASTRO_BLACK / TRANSLATOR_GRAPHITE_MIST`
  (pair_quality 12970, signal_ret 2.11/tick).
- Best names: `TRANSLATOR_ASTRO_BLACK` (q=0.151),
  `TRANSLATOR_ECLIPSE_CHARCOAL` (0.135), `TRANSLATOR_GRAPHITE_MIST` (0.134),
  `TRANSLATOR_SPACE_GRAY` (0.132), `TRANSLATOR_VOID_BLUE` (0.113).
- Anti-pairs: `ASTRO_BLACK__SPACE_GRAY`, `ECLIPSE_CHARCOAL__VOID_BLUE`,
  `ECLIPSE_CHARCOAL__SPACE_GRAY`.

### PANEL (Construction Panels)
- Median spread 8-9.
- `PANEL_2X2 / PANEL_2X4` is the clean convergence pair (score 4443, tight_rate 1.0).
- Best names for solo trade: `PANEL_1X4` (q=0.148), `PANEL_2X2` (0.135),
  `PANEL_4X4` (0.132).
- Anti-pair: `PANEL_1X4__*` against the larger panels - 1X4 structurally diverges.
  Trade 1X4 standalone but not as a pair leg.

---

## Tier 2 - MID VOL, partial signal (selective trading only)

### SLEEP_POD (Vertical Sleeping Pods)
- Median spreads 9-11.
- Only **two** clean convergence pairs: `NYLON / POLYESTER` (score 7436),
  `NYLON / SUEDE` (2252).
- Anti-pairs are massive: COTTON, LAMB_WOOL, SUEDE drift apart from each
  other on all three days. Trading them as pairs loses thousands.
- Best solo name: `SLEEP_POD_NYLON` (q=0.131).
- Use sparingly. Skip COTTON, LAMB_WOOL, POLYESTER, SUEDE for solo trades.

### OXYGEN_SHAKE (Liquid Breath Oxygen Shakes)
- Median spreads 12-15.
- One validated pair: `CHOCOLATE / EVENING_BREATH` (score 4199, tight_rate 0.69).
- Everything else either drifts or rarely tight.
- High spread cost limits MM viability.

---

## Tier 3 - HIGH VOL with tradable shock fade (size carefully)

### MICROCHIP (Organic Microchips)
- Median spread 8-12.
- High realised vol per ken's findings; biggest absolute mid moves of any family.
- Strong shock-fade alpha: `MICROCHIP_SQUARE` was a top manual trade
  candidate in `ken_round5_findings_and_alphas.md`.
- Best names: `MICROCHIP_OVAL` (q=0.165), `MICROCHIP_RECTANGLE` (0.162),
  `MICROCHIP_CIRCLE` (0.152), `MICROCHIP_TRIANGLE` (0.142).
- `MICROCHIP_SQUARE` itself has q=0.084 (median spread 12) but big absolute reversions.
- Anti-pairs: `OVAL__RECTANGLE`, `OVAL__TRIANGLE`, `CIRCLE__SQUARE`.

### PEBBLES (Purification Pebbles)
- Highest realised vol of all families. Median spreads 9-17.
- `PEBBLES_XL` mid trends from ~9500 to ~17000 across 3 days. Big swings.
- `PEBBLES_XL` is the ITM leverage leg per the discord screenshot
  ("hard coded values for mean reversion and use ITM options as leveraged
  positions") - signal off cheap variants (XS, S), express via XL.
- Solo signal quality: only `PEBBLES_XS` (0.140) clears. PEBBLES_XL = -0.031.
- Best for big-shock fade only, not for MM. Position limit 10 caps the
  "leverage" angle hard.

---

## Tier 4 - SKIP (no tradable signal under cost)

### SNACKPACK (Protein Snack Packs)
- Median spread 16-18 - too wide for both MM and shock fade.
- All variants have signal_quality_score **< 0** (after cost).
- Pair tight_rate ~ 0.03 - paths almost never both tight.
- Verdict: skip entirely.

### GALAXY_SOUNDS (Galaxy Sounds Recorders)
- Pair tight_rate ~ 0.03 - signal exists per tick but the gate almost never fires.
- Median spread 13-14. Reversion edge exists but never executable.
- Verdict: skip entirely.

### UV_VISOR (UV-Visors)
- Median spread 10-14.
- Only `AMBER / ORANGE` remotely tradable (tight_rate 0.10).
- Rest tight_rate 0.03-0.05.
- Verdict: skip unless you specifically need AMBER/ORANGE.

---

## Final 13-symbol stable whitelist

For a stability-first trader (smooth upward PnL slope), trade ONLY these:

```
ROBOT_DISHES
ROBOT_IRONING
ROBOT_VACUUMING
ROBOT_LAUNDRY
ROBOT_MOPPING

TRANSLATOR_ASTRO_BLACK
TRANSLATOR_ECLIPSE_CHARCOAL
TRANSLATOR_GRAPHITE_MIST
TRANSLATOR_SPACE_GRAY
TRANSLATOR_VOID_BLUE

PANEL_2X2
PANEL_2X4
PANEL_4X4
```

All capped at position limit 10 per algo.md. Cross-family caps (sum of |pos|):
ROBOT 25, TRANSLATOR 25, PANEL 15. Family caps below 5 x sym_lim because
intra-family signals correlate - we don't want all 5 ROBOT symbols loaded
the same direction.

## Volatility-aware allocation

| Tier | Families | Strategy | Trader |
|---|---|---|---|
| 1 (low vol) | ROBOT, TRANSLATOR, PANEL | passive MM, pair convergence | trader10 |
| 2 (mid vol) | SLEEP_POD (NYLON only), OXYGEN_SHAKE (one pair) | optional pair convergence | overlay |
| 3 (high vol) | MICROCHIP, PEBBLES | shock fade + ITM leverage (capped @ 10) | trader4 light |
| 4 (skip) | SNACKPACK, GALAXY_SOUNDS, UV_VISOR | none | - |
