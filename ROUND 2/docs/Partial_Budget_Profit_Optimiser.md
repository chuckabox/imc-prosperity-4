# Partial-Budget Profit Optimiser (R2 Manual)

Companion to the main Manual Optimiser. The main one forces
`x + y + z = 100` (spend the full 50,000 XIRECs); this one lets the
total float between 0% and 100% and scores allocations on **Net
Profit**, flagging anything that doesn't clear a user-set threshold
(default 50k) as not worth playing.

## Why a second optimiser?

The challenge PnL is `Research(x) * Scale(y) * Speed(z) - Budget_Used`,
where `Budget_Used = 500 * (x+y+z)`. Nothing forces us to spend the
whole 50,000 budget — we should only commit capital where marginal
return beats marginal cost. The default app hides that choice by
rebalancing sliders to sum to 100%. This app surfaces it:

- Free sliders — `x + y + z` can be anywhere in `[0, 100]`.
- Explicit **profit threshold** (default 50,000 XIRECs, i.e. "playing
  is only worth it if we clear the full budget in profit").
- Three optimiser picks:
  - **Max Net Profit** — standard objective.
  - **Cheapest clear** — smallest spend whose mean Net Profit still
    exceeds the threshold (saves unused budget for other rounds / risk
    capacity).
  - **Max profit / XIREC** — best capital efficiency
    (`mean_net_profit / budget_used`).
- **Partial-budget frontier** — plots the best achievable Net Profit
  for every total allocation level (0%, 5%, … 100%). A flat or
  declining tail means extra spend isn't buying extra profit.
- Break-even (`Net = 0`) and threshold lines drawn on every chart so
  you can eyeball feasibility.

## How to open it

From the repo root:

```bash
streamlit run tools/manual_optimiser/app_profit.py
```

Sidebar controls:

| Control | What it does |
| --- | --- |
| Competitor scenario | Pick one of the 8 distributions from [scenarios.py](../../tools/manual_optimiser/scenarios.py) (Beta(2,5) lazy, bimodal, aggressive, etc.). |
| MC iterations | Monte Carlo sample count (higher = smoother). |
| Competitor pop seed | RNG seed — change to stress-test stability. |
| Min profit threshold | The "worth playing" bar. Default 50,000 (our granted budget). |
| Run / refresh Monte Carlo | Rebuild the grid with the current settings. |

## Reading the output

- **Top metrics row** — total allocation %, budget spent vs saved,
  gross PnL, Net Profit with delta vs threshold.
- **Status banner** — red (loss), yellow (positive but sub-threshold),
  green (clears threshold).
- **Optimiser picks** — click *Apply* on any card to push that
  allocation into the sliders.
- **Frontier chart** — x-axis is XIRECs spent, y-axis is Net Profit.
  Mean and P05 (pessimistic) curves. Read this to decide the spend
  level before drilling into the exact `(x, y, z)`.
- **Heatmap** — mean Net Profit over `(x, y)` at your current `z`.
- **Export** — writes `tools/manual_optimiser/partial_profit_config.json`
  with current allocation, breakdown, optima, and the frontier table.

## Relationship to the main optimiser

The two apps share [engine.py](../../tools/manual_optimiser/engine.py)
and [simulation.py](../../tools/manual_optimiser/simulation.py), so
the underlying math and MC are identical. Differences live entirely
in the UI layer:

| | `app.py` (main) | `app_profit.py` (this one) |
| --- | --- | --- |
| Slider constraint | forced to `x+y+z=100` | free, clamped to `≤100` |
| Primary metric | Net PnL vs 200k target | Net Profit vs user threshold |
| Optimisers | Global / Safety | Max profit / Cheapest clear / Efficiency |
| Unique view | Safety-probability optimum | Partial-budget frontier |
| Export file | `optimum_config.json` | `partial_profit_config.json` |

Use the main app when you've already decided to spend the full 50k
and want to pick the best point on that simplex. Use this one when
the question is _"should we even spend the full budget, or is a
smaller commitment more profitable?"_
