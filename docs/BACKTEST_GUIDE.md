# Backtest Guide

This repo uses the Rust backtester at `external/prosperity_rust_backtester`.

## Quick Start (recommended)

Use the new wrapper:

`python tools/runbacktest.py <trader_path> <other rust options>`

Examples:

- Round 4 trader, default dataset auto-inferred from trader path:
  - `python tools/runbacktest.py "ROUND 4/traders/ken/table.py" --products summary`
- Specific day:
  - `python tools/runbacktest.py "ROUND 4/traders/ken/desk.py" --day 2 --products summary`
- Override dataset:
  - `python tools/runbacktest.py "ROUND 4/traders/ken/chair.py" --dataset "ROUND 4/data_capsule" --products summary`
- Skip build step:
  - `python tools/runbacktest.py "ROUND 4/traders/ken/lamp.py" --no-build --products summary`

Notes:

- `tools/runbacktest.py` forwards unknown flags directly to the Rust backtester.
- If `--dataset` is not set, it is inferred from `ROUND N` in the trader path.

## Direct Rust Command

If you prefer raw Rust CLI:

`cargo run --release -- --trader "<absolute_or_relative_trader_path>" --dataset "<dataset_dir>" --products summary`

Run this inside:

- `external/prosperity_rust_backtester`

## Typical Workflow

1. Run backtest with `tools/runbacktest.py`.
2. Parse runs into `backtest_comparison.js`:
   - `python tools/parse_runs.py`
3. Open `visualizer.html` and click `REFRESH DATA`.
