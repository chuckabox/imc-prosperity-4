# Sid's medium-vol target list

Goal: products less volatile than `PEBBLES_XL`/`MICROCHIP_OVAL` (Ken's picks) but with more profit-per-trade than `kingking`'s thin-spread Tier-1 MM.

## Method

Scanned all 50 products across 3 days of `data_capsule/prices_round_5_day_{2,3,4}.csv`. Per product computed:

- `mid_std` — std of mid price (level vol)
- `abs_dmid_mean` — average abs tick-to-tick mid change (realized vol per tick)
- `shock_14` — count of ticks with |dmid| ≥ 14 (Math1061 trigger)
- `spread_med` — median bid-ask spread
- `ac1` — 1-lag autocorrelation of mid changes (negative = mean-reverting)
- **`edge` = `abs_dmid_mean − spread_med/2`** (rough net edge per move)

Why `edge`: if we fade a move of size `abs_dmid_mean`, we cross the spread once (~spread/2 cost). What's left is the harvestable signal.

## Where Ken trades vs where kingking trades

| Group | Product | mid_std | abs_dmid | spread | shock_14 | edge | ac1 |
|---|---|---|---|---|---|---|---|
| Ken (Tier 3 high-vol) | PEBBLES_XL | 1776 | 24.2 | 17 | 19,502 | **15.7** | 0.008 |
| Ken (Tier 3 high-vol) | MICROCHIP_OVAL | 1552 | 9.75 | 8 | 7,675 | 5.75 | -0.007 |
| Peter (Tier 1 low-vol) | ROBOT_DISHES | 557 | 8.06 | 7 | 4,267 | 4.56 | **-0.232** |
| Peter | TRANSLATOR_ASTRO_BLACK | 490 | 7.52 | 8 | 4,419 | 3.52 | -0.006 |
| Peter | PANEL_2X2 | 675 | 7.65 | 9 | 4,598 | 3.15 | -0.011 |

Observation: kingking trades products with edge ~3–4. Ken trades products with edge ~6–16. The middle ground (edge 5–10, mid_std 600–900) is **untapped**.

## Recommended starter list (medium vol)

**Pick the products with edge ≥ 5.5 AND mid_std ≤ 900** → the sweet spot:

| Rank | Product | mid_std | abs_dmid | spread | shock_14 | edge | ac1 | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | **MICROCHIP_TRIANGLE** | 833 | 11.5 | 9 | 10,357 | **7.00** | -0.007 | Best edge in mid-vol band. ~10k shock entries over 3 days. |
| 2 | **MICROCHIP_RECTANGLE** | 752 | 10.4 | 8 | 8,815 | **6.42** | -0.003 | Lower vol than TRIANGLE, narrower spread, almost as much edge. |
| 3 | **PEBBLES_S** | 833 | 12.0 | 12 | 10,863 | 5.99 | 0.008 | Wider spread but more shocks. |
| 4 | **PEBBLES_M** | 688 | 12.1 | 13 | 10,988 | 5.58 | -0.005 | Same shape as PEBBLES_S, slightly less vol. |
| 5 | **PEBBLES_L** | 622 | 12.0 | 13 | 10,916 | 5.49 | 0.007 | Lowest vol of mid-PEBBLES band. |

### Why these beat MICROCHIP_OVAL on raw shock-fade

- **MICROCHIP_RECTANGLE**: `abs_dmid 10.4 vs OVAL 9.75`, `spread 8 vs OVAL 8`, `shock_14 8,815 vs OVAL 7,675`. **More moves, same spread** → more fade opportunities.
- **MICROCHIP_TRIANGLE**: `abs_dmid 11.5 vs OVAL 9.75`, `shock_14 10,357 vs OVAL 7,675`. **35% more shocks**.

Volatility.md ranks OVAL above RECTANGLE/TRIANGLE because of cross-product `signal_quality_score q` (which considers pairs and execution), but for **standalone shock-fade** the raw move + spread metrics matter more.

## Tier-up candidates (add later when comfortable)

| Product | edge | Reason |
|---|---|---|
| **MICROCHIP_SQUARE** | 10.31 | Biggest edge after PEBBLES_XL, but mid_std 1830 → stress-tier vol. Spread 12. Use after the medium-vol layer is stable. |
| **PEBBLES_XS** | 7.53 | More volatile than the M/L/S pebbles. Good edge but spread 9 + bigger shocks → swingier P&L. |

## Skip (kingking territory or worse)

- All ROBOT, TRANSLATOR, PANEL: edge 3–5. Already covered by `kingking`.
- SLEEP_POD: edge ~3.5–4. Marginal; only NYLON has real signal per volatility.md.
- OXYGEN_SHAKE, GALAXY_SOUNDS, UV_VISOR: edge < 2.5. Spreads eat the move.
- SNACKPACK (entire family): **negative edge** (spread > avg move). Cannot profit.

## Suggested first algo

Take MATH1061 logic (shock-fade with 1-2 tick hold), apply it to:

- **MICROCHIP_RECTANGLE** (primary — best edge/vol ratio)
- **MICROCHIP_TRIANGLE** (secondary — more shocks)

Per-product thresholds (tuned to that product's typical move size):

```
MICROCHIP_RECTANGLE: SHOCK_TRIGGER = 10, BIG_SHOCK = 18
MICROCHIP_TRIANGLE:  SHOCK_TRIGGER = 11, BIG_SHOCK = 20
```

(Math1061 uses 14 / 24 — calibrated for PEBBLES_XL's 24 avg move; we scale down ~60% for these.)

Position limit: hard 10 (algo.md rule). MAX entry size ~4. Hold 1 tick default, 2 ticks on big shock.

Expected daily P&L estimate (rough, 1% capture rate at 5pt avg fade per shock):
- MICROCHIP_RECTANGLE: 8815/3 days * 1% * 5pts * 4 size = ~590/day
- MICROCHIP_TRIANGLE: 10357/3 days * 1% * 5pts * 4 size = ~690/day
- **Combined: ~1,300/day** (very rough; actual depends on slippage and reversion magnitude)

Once optimized → layer in PEBBLES_M and PEBBLES_L (different family = uncorrelated alpha).
