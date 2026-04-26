# Visualizer Guide

This document explains how to use `visualizer.html` and how to interpret each metric.

## Purpose

The visualizer is designed to help you compare strategies for competition readiness by showing:

- PnL and risk behavior over time
- Product-level attribution
- Cross-day stability
- A practical selection score with risk gates

## Data Source

The app reads from `backtest_comparison.js` (`BACKTEST_DATA` object).

Each run typically includes:

- `trader`
- `round`
- `day`
- `final_pnl`
- `final_pnl_by_product`
- `history` (symbol-level PnL snapshots over time)

## Navigation

Top tabs:

- `OVERLAY` -> performance and ranking
- `ATTRIBUTION` -> product contribution comparison
- `STABILITY` -> cross-day consistency and heatmap

Left sidebar:

- Context filters: `Round` and `Day`
- Strategy list: click one or more strategies to include in analytics
- `RESET ALL`: clear current strategy selection

## Global Table Behavior

All leaderboard tables use:

- Sticky headers
- Sort controls in header cells (click to toggle descending/ascending)
- Isolated scroll areas (title/header does not scroll with rows)

Sort icon meanings:

- `v` = descending
- `^` = ascending
- `-` = inactive

## OVERLAY Tab

### PnL Overlay Chart

Shows selected strategies as equity curves over time.

Important detail:

- The curve is built from aggregated symbol-level PnL snapshots (`buildEquityCurve`), not raw per-symbol lines.
- This gives a portfolio-level view per strategy.

### Batch Metrics Table

Columns:

- `STRATEGY`: selected strategy name
- `PNL`: final PnL for selected round/day run
- `MAX DD`: maximum drawdown from portfolio curve (negative value)
- `CALMAR`: `final_pnl / abs(max_drawdown)`
- `SHARPE*`: simplified Sharpe-like score from curve deltas
- `GREEN TICKS`: percentage of positive curve deltas
- `SELECTION SCORE`: custom 0-100 readiness score (see below)
- `STATUS`: `GREEN / AMBER / RED` risk-gated classification
- `READINESS`: legacy bar score retained for quick visual scan

### Quick Stats Tiles

Top tiles summarize currently selected strategies:

- Top PnL strategy
- Best Sharpe strategy
- Lowest drawdown strategy
- Average green ticks

## ATTRIBUTION Tab

### Grouped Product Attribution Chart

Bar chart of `final_pnl_by_product` per selected strategy.

### Asset Performance Leaderboard

For each asset:

- Best strategy
- Max profit
- Least profit
- Spread (`max - min`)

Use this table to detect assets with large strategy dispersion (high spread = edge may be strategy-specific).

## STABILITY Tab

This tab has two separate panels.

### Cross-Day Matrix

Per trader (within selected round):

- `D0 / D1 / D2 PNL`
- `AVG`: mean across available days
- `RANGE`: `max(day pnl) - min(day pnl)`
- `CONSISTENCY`: inverse normalized range heuristic

Interpretation:

- Lower range + higher consistency is generally better.

### Per-Asset Day Stability Heatmap

For each asset:

- Average PnL on D0, D1, D2
- Spread across days

Color coding:

- Green shades: positive
- Red shades: negative
- Stronger color: larger magnitude

## Selection Score and Status

`SELECTION SCORE` is a composite indicator used to rank strategies for deployment decisions.

It combines:

- Return quality (`CALMAR`, `SHARPE*`, `GREEN TICKS`)
- Cross-day robustness (avg PnL, worst day, day range)
- Concentration penalty (single-asset dependency via `final_pnl_by_product`)

Then hard risk gates produce `STATUS`:

- `RED`: severe risk profile
- `AMBER`: medium risk / caution
- `GREEN`: comparatively robust candidate

Note:

- Status and score are internal heuristics for triage.
- Final decisions should still review raw PnL, drawdown profile, and day-by-day behavior.

## Recommended Workflow

1. Filter round/day context.
2. Select candidate strategies.
3. In `OVERLAY`, sort by `SELECTION SCORE` and check `STATUS`.
4. Reject obvious `RED` strategies unless needed for exploration.
5. In `ATTRIBUTION`, inspect spread and asset dependence.
6. In `STABILITY`, validate cross-day robustness and per-asset consistency.
7. Keep a shortlist of `GREEN` and strongest `AMBER` with acceptable drawdown.

## Current Limitations

- No exact per-strategy buy/sell fill markers (input data currently lacks strategy-resolved trade fills in this visualizer dataset).
- `SHARPE*` is simplified (no risk-free rate/calendar normalization).
- `CONSISTENCY` is heuristic, not a formal statistical stability test.

## File Map

- UI + logic: `visualizer.html`
- Data payload: `backtest_comparison.js`

