# Round 4 Bowl Design

**Goal:** Build a new `trader_ken` strategy named `bowl` for Round 4 that starts from a human discretionary reading of the raw market and serves as a conservative but extensible baseline for fast research iteration.

## Why This Exists

Round 4 research has exposed a reliability gap between local backtests, the IMC portal, and live outcomes. The purpose of `bowl` is not to maximize a single simulated PnL number by fitting to one imperfect environment. It is to encode the most believable manual edges in a form that is interpretable, easy to modify, and robust enough to survive repeated iteration.

## Market Read

The current round structure suggests three distinct behaviors:

1. `HYDROGEL_PACK` is the cleanest spread-capture and inventory-management product.
2. `VELVETFRUIT_EXTRACT` has short-horizon directional context from repeated participant flow, especially `Mark 67` versus `Mark 49` and `Mark 22`.
3. `VEV_*` options should not be traded broadly. Only selective, obvious mispricings should be allowed, especially deep ITM synthetic-like strikes such as `VEV_4000` and `VEV_4500`.

## Bowl v1 Strategy Shape

`bowl` v1 should implement a baseline version with the following layers:

### 1. Passive Hydrogel Core

- Quote both sides of `HYDROGEL_PACK`.
- Use mid-price as fair anchor.
- Apply modest inventory skew to avoid one-sided accumulation.
- Allow small opportunistic takes only when quoted edge is clearly favorable.

### 2. Light Velvetfruit Core

- Quote `VELVETFRUIT_EXTRACT` more conservatively than Hydrogel.
- Skew quotes using short-memory participant flow and mild momentum context.
- Keep the strategy focused on temporary pressure rather than persistent directional conviction.

### 3. Tiny Selective VEV Overlay

- Restrict VEV trading to `VEV_4000` and `VEV_4500` only in v1.
- Estimate fair value as intrinsic proxy plus strike floor.
- Only trade when mispricing exceeds a large threshold.
- Use small size and strict position caps so this remains an overlay, not a core risk source.

## Explicit Non-Goals

- No broad VEV strike trading.
- No complex multi-leg hedging engine in v1.
- No heavy dependence on timestamp-dense replay assumptions.
- No optimization solely for local backtest totals without sanity against manual reasoning.

## Promotion Criteria

`bowl` should be considered useful only if it improves on current furniture baselines while remaining simple enough to reason about. Success is not just total PnL. It must also show:

- consistent contribution from core products,
- limited dependence on one narrow window,
- manageable inventory usage,
- and no obvious blow-up from small tuning changes.

## Iteration Loop

The development loop for `bowl` is:

1. implement a simple interpretable baseline,
2. run round 4 backtest,
3. inspect product/day decomposition,
4. modify one small set of parameters or one focused logic block,
5. rerun backtest,
6. repeat while preserving explainability.

## Files In Scope

- Create `ROUND 4/traders/ken/bowl.py`
- Update research docs only if findings materially change
- Reuse existing Round 4 trader structure and datamodel imports

## Risks

- The local backtester may overstate fill density.
- Participant-flow features may decay or invert live.
- Synthetic option logic may appear attractive in replay but degrade badly under sparse execution.

To mitigate this, `bowl` should bias toward passive core edge, small overlay size, and minimal structural assumptions.
