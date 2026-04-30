# Round 5 Alpha Selection

## Selection Principle
Use only signal regimes supported by both:
- positive/strong symbol quality in `top_symbols_by_signal_quality.csv`
- tradable pair quality and tightness in `top_pairs_by_signal_quality.csv`

Avoid families where spread/tightness profile makes edge non-executable.

## Tier A (Always On)
Low-cost, high-consistency core set.

### Families
- ROBOT
- TRANSLATOR
- Selected PANEL symbols

### Symbol Priority
- ROBOT: `ROBOT_DISHES`, `ROBOT_IRONING`, `ROBOT_VACUUMING`, `ROBOT_LAUNDRY`, `ROBOT_MOPPING`
- TRANSLATOR: all 5 variants, with priority to `ASTRO_BLACK`, `ECLIPSE_CHARCOAL`, `GRAPHITE_MIST`
- PANEL: `PANEL_2X2`, `PANEL_2X4`, `PANEL_4X4` as stable core; `PANEL_1X4` only for selective single-name fades

### Alpha Modes
- A1: single-name shock fade
- A2: pair convergence overlay for high tight-rate pairs

## Tier B (Conditional On)
Higher-volatility opportunities with stricter gating.

### Families
- MICROCHIP
- Selective PEBBLES events
- Optional SLEEP_POD narrow subset

### Alpha Modes
- B1: shock fade on large moves, dynamic trigger, strict spread gate
- B2: pair overlay only where pair quality and tightness are adequate

### Special Notes
- `MICROCHIP_SQUARE` and `PEBBLES_XL` can be included as event-driven instruments only.
- These symbols require stricter spread caps and lower base clip due to cost and variance.

## Tier C (Off by Default)
Disabled unless new evidence appears.

### Families
- SNACKPACK
- GALAXY_SOUNDS
- most UV_VISOR pairs/symbols

### Why
- weak net signal under costs or low tightness availability in current analysis snapshots.

## Enable/Disable Criteria

## Symbol Enable
Enable symbol if all hold:
- `signal_quality_score > 0.10` (default baseline; can be stricter for Tier A)
- current spread <= configured symbol spread cap
- no active cooldown
- risk budget available

## Pair Enable
Enable pair if all hold:
- `pair_quality_score` in top validated bucket
- sufficient `tight_rate` for repeatable execution
- pair is not listed in project anti-pair set

## Disable Triggers
- repeated negative contribution over rolling validation windows
- unstable cross-engine ranking
- concentration risk breach attributable to symbol/pair

## Risk Caps (Alpha-Level)
- hard cap each symbol: `10`
- recommended family caps:
  - ROBOT: `25`
  - TRANSLATOR: `25`
  - PANEL: `15`
  - MICROCHIP: `15`
  - PEBBLES: `10`
  - SLEEP_POD: `10`
- max concurrent open legs:
  - global: `<= 12`
  - per family: `<= 4`

## Recommended Default Activation Set
- Tier A fully enabled
- Tier B enabled for:
  - MICROCHIP: `OVAL`, `RECTANGLE`, `CIRCLE`, `TRIANGLE`
  - Event-only: `MICROCHIP_SQUARE`, `PEBBLES_XL`
- Tier C disabled
