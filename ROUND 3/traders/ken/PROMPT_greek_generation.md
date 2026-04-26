# Greek Generation Prompt (Ken Trader)

Use this prompt to build a new generation trader focused on greek-aware options trading for Prosperity Round 3.

## Role
You are optimizing a Prosperity Round 3 trader for upload-slice PnL while preserving reasonable full-day retention.

## Objective
- Create a new trader file: `ROUND 3/traders/ken/we found greek.py`
- Baseline to beat:
  - `we found epsilon.py` upload slice PnL: `11,450`
  - `we found epsilon.py` full day2 PnL: `1,513`
- Primary target: upload slice `>= 12,000`
- Secondary target: full day2 should not collapse (aim `>= 1,200`)

## Hard Constraints
- Do **not** import old trader classes/files; keep a standalone `Trader` implementation.
- Keep compatibility with existing `datamodel.py`.
- Respect position limits (200 for `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`; 100 per option symbol).
- Keep day alignment logic (`VEV_DAY_INIT = 2` compatible with upload simulation).

## Starting Point
- Copy `ROUND 3/traders/ken/we found epsilon.py` into `we found greek.py`.
- Implement greek-aware improvements in `we found greek.py` only.

## What To Build (Greek Generation)
Add a greek-aware overlay on top of the current RV engine:

1. **Dynamic per-strike delta (replace static approximation bias)**
   - Compute option delta from Black-Scholes (`N(d1)`) for each strike using current `S`, `K`, `T`, and fitted IV.
   - Use this to compute portfolio net delta target for `VFE` hedge.
   - Keep a safe fallback to existing `DELTA_APPROX` if IV/inputs unavailable.

2. **Gamma-weighted position sizing**
   - Compute gamma (`phi(d1)/(S*sigma*sqrt(T))`) per strike.
   - Increase pair size when both legs are high-liquidity and gamma profile is favorable.
   - Decrease size when gamma risk is too concentrated or hedge cost is high.

3. **Vega-aware entry filter**
   - Estimate vega for candidate legs.
   - Require stronger mispricing for high-vega trades when VFE spread is wide (hedging expensive).
   - Allow easier entry when vega is moderate and hedge conditions are good.

4. **Dual-pair opportunity mode**
   - Current logic typically enters one pair (`5000/5100` vs `5200/5300` buckets).
   - Add optional second pair entry in same tick only when:
     - global and per-strike caps allow,
     - delta/gamma/vega envelope remains within configured risk bounds,
     - top-of-book liquidity supports execution.

5. **Risk guards**
   - Cap absolute portfolio greek exposure with configurable thresholds:
     - max net delta
     - max net gamma proxy
     - max net vega proxy
   - If any threshold breached, force defensive behavior:
     - tighten new entry gate,
     - prioritize decay/flatten logic.

## Suggested Parameters To Add
- `VEV_MAX_NET_DELTA`
- `VEV_MAX_NET_GAMMA`
- `VEV_MAX_NET_VEGA`
- `VEV_GAMMA_SIZE_MULT_MIN/MAX`
- `VEV_VEGA_ENTRY_BUMP_MIN/MAX`
- `VEV_DUAL_PAIR_ENABLE`
- `VEV_DUAL_PAIR_EXTRA_QTY`
- `VFE_SPREAD_HEDGE_PENALTY`

## Evaluation Protocol (must follow)
For every meaningful change, run:

1) Upload-like slice:
`python tools/run_prosperity4bt.py --trader "ROUND 3/traders/ken/we found greek.py" --dataset "ROUND 3/data_capsule_day2_first10pct" --day 2 --no-progress`

2) Full day2:
`python tools/run_prosperity4bt.py --trader "ROUND 3/traders/ken/we found greek.py" --dataset "ROUND 3/data_capsule" --day 2 --no-progress`

3) Compare against baseline `we found epsilon.py`.

## Deliverables
Return:
- final parameter set
- upload slice PnL
- full day2 PnL
- short explanation of why greek overlay improved (or failed)
- next 3 high-value follow-up experiments

## Stop Condition
Stop when one of these is true:
- Achieved upload `>= 12,000` with acceptable retention (`>= 1,200`), or
- Completed at least 3 substantial greek-architecture iterations and no further uplift appears.
