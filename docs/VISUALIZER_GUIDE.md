# Visualizer Guide

This document explains the current behavior of `visualizer.html`, including multi-source workflows (Rust backtest + i4bt + live logs).

## Purpose

The visualizer helps compare strategy behavior and readiness via:

- Portfolio PnL curves
- Risk and selection heuristics
- Product-level attribution
- Cross-day stability
- Backtest vs live comparison
- Data cleanup and duplicate management

## Data Inputs

Primary files:

- `backtest_comparison.js` (`BACKTEST_DATA`)
- `i4bt_comparison.js` (`I4BT_DATA`)
- `live_comparison.js` (`LIVE_LOG_DATA`)

Live data is generated from `ROUND */live_logs/**` by:

- `tools/build_live_comparison.py`
- API trigger via `tools/visualizer_loader_server.py` (`/api/load-data`)

i4bt data is generated from `external/imc-prosperity-4-backtester/backtests/*.log` by:

- `tools/build_i4bt_comparison.py`
- API trigger via `tools/visualizer_loader_server.py` (`/api/load-data`)

Typical run fields:

- `trader`, `round`, `day`
- `final_pnl`, `final_pnl_by_product`
- `history` (symbol-level PnL snapshots)

## Running with File-Backed Actions

Use the loader server if you want `REFETCH` / manager actions to rewrite files:

`python tools/visualizer_loader_server.py --repo-root . --port 8765`

Open:

- [http://127.0.0.1:8765/visualizer.html](http://127.0.0.1:8765/visualizer.html)

## Navigation

Top tabs:

- `OVERLAY`: core curve + leaderboard
- `COMPARE`: multi-source overlay
- `ATTRIBUTION`: product breakdown and asset leaderboard
- `STABILITY`: day consistency matrix + heatmap
- `MANAGER`: duplicate scan/cleanup

Sidebar filters:

- Source: `BACKTEST` / `I4BT` / `LIVE LOGS`
- Round: `R3` / `R4` / `R5`
- Day:
  - Backtest + i4bt: `TOTAL`, `D0`, `D1`, `D2`, `D3` (as available by source)
  - Live logs: day-only (`D#`), no `TOTAL`

Header actions:

- `REFETCH`: rebuild/clean datasets through loader API
- `EXPORT SNAPSHOT`: export computed analytics payload

## Day Filter Behavior

- `D#`: show runs only for that day.
- `TOTAL`: show all runs in selected round.

Special handling in `BACKTEST + TOTAL`:

- Sidebar groups by strategy name and exposes variants:
  - `TraderName V1`
  - `TraderName V2`
  - ...
- Each variant can represent a different run track across days.

## OVERLAY Tab

### Chart

- Uses portfolio-level equity curves from `history` (`buildEquityCurve`).
- In day mode: standard single-day timeline.
- In `TOTAL`: builds a concatenated multi-day timeline with day-zone shading.

### Leaderboard Metrics

- `PNL`
- `MAX DD`
- `CALMAR`
- `SHARPE*` (simplified)
- `GREEN TICKS`
- `SELECTION SCORE`
- `STATUS` (`GREEN/AMBER/RED`)
- `WHY`
- `READINESS`

## COMPARE Tab

Compares selected strategies across multiple sources on the same chart.

Key behavior:

- Requires explicit strategy selection (empty selection shows no chart).
- Uses round-level matching and multi-day zoning.
- Source A and Source B are user-selectable (`BACKTEST` / `I4BT` / `LIVE`).
- Optional `ALL 3: ON` overlays the third source on the same graph.
- Source A timeline is used to define day zones.
- Orange gap rendering shows divergence detail by segment.
- Zoom/pan enabled:
  - wheel zoom (x-axis)
  - pinch zoom
  - drag pan (x-axis)

Summary table includes:

- Trader
- Source A PnL
- Source B PnL
- Source C PnL (when `ALL 3: ON`)
- Delta (B - A)
- Common ticks
- Coverage

## ATTRIBUTION Tab

Uses selected strategies only.

- If nothing selected: chart and table are cleared.
- Duplicate trader labels are deduped (keeps strongest selected run per trader).

Outputs:

- Grouped product attribution chart
- Asset leaderboard (`best`, `max`, `min`, `spread`)

## STABILITY Tab

Two panels:

- Cross-day matrix per strategy
- Per-asset day heatmap

Day columns are dynamic based on available data in selected round.

## MANAGER Tab

Purpose: detect duplicate runs and apply file-backed cleanup.

Capabilities:

- Duplicate grouping by fingerprint
- Keep newest candidate, mark others for removal
- Round/trader/run-id filters
- Batch selection + remove

Backtest-mode remove:

- Removes selected run ids from `backtest_comparison.js`
- Runs backtest dedupe/cleanup rewrite
- Best-effort removal of matching artifact files

Live-mode remove:

- Removes selected underlying live log files
- Removes sibling `.json`/`.log` artifacts for same stem
- Cleans duplicate JSON content (`activitiesLog`, `tradeHistory`)
- Rebuilds `live_comparison.js`

## REFETCH Behavior

When called via loader server API:

- Runs backtest cleanup + rewrite
- Rebuilds i4bt dataset
- Runs live log cleanup + rebuild
- Updates `backtest_comparison.js`, `i4bt_comparison.js`, and `live_comparison.js`

## Export Snapshot

`EXPORT SNAPSHOT` writes a JSON with:

- current filters
- selected ids
- computed performance, attribution, and stability views
- compare summary rows and compare note text
- source/day mode metadata (`sourceMode`, `dayMode`)

Useful for offline analysis or AI-assisted review.

## Current Limitations

- No per-fill trade markers on curves.
- `SHARPE*` is simplified.
- Consistency metric is heuristic.
- Variant grouping in `BACKTEST + TOTAL` is rank-based (by run id ordering per day), not semantic model-version metadata.

## File Map

- UI + interaction logic: `visualizer.html`
- Loader/API server: `tools/visualizer_loader_server.py`
- Live data builder: `tools/build_live_comparison.py`
- i4bt data builder: `tools/build_i4bt_comparison.py`
- Backtest payload: `backtest_comparison.js`
- i4bt payload: `i4bt_comparison.js`
- Live payload: `live_comparison.js`
