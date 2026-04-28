# Backtest Guide

This repo supports two backtest engines and one live source in the same visualizer:

- Rust backtester -> `backtest_comparison.js`
- Python i4bt backtester -> `i4bt_comparison.js`
- Live logs -> `live_comparison.js`

## 1) Rust Backtester

Wrapper command:

`python tools/runbacktest.py <trader_path> [rust flags]`

Examples:

- Auto-infer dataset from trader path:
  - `python tools/runbacktest.py "ROUND 5/traders/ken/pot.py" --products summary`
- Single day:
  - `python tools/runbacktest.py "ROUND 5/traders/ken/pot.py" --day 2 --products summary`
- Skip rebuild:
  - `python tools/runbacktest.py "ROUND 5/traders/ken/pot.py" --no-build --products summary`

Notes:

- Unknown flags are forwarded to Rust CLI.
- Rust runs are parsed from `external/prosperity_rust_backtester/runs`.

## 2) Python i4bt Backtester

Wrapper command:

`python tools/run_python_bt.py <trader_path> <round-or-day...>`

Examples:

- Whole round:
  - `python tools/run_python_bt.py "ROUND 5/traders/ken/MATH1052.py" 5`
- Specific day:
  - `python tools/run_python_bt.py "ROUND 5/traders/ken/MATH1052.py" 5-2`
- Multiple days:
  - `python tools/run_python_bt.py "ROUND 5/traders/ken/MATH1052.py" 5-2 5-3 5-4`

What this wrapper now does:

- Writes log to `external/imc-prosperity-4-backtester/backtests`
- Uses structured filename: `<trader>__<day-args>__<timestamp>.log`
- Writes sidecar metadata: `<same>.meta.json`

This metadata is used by visualizer parsing so strategy names are readable (`pot`, `MATH1051`, etc.) instead of `unknown`.

## 3) Refresh Data for Visualizer

Start loader server:

`python tools/visualizer_loader_server.py --repo-root . --port 8765`

Then open:

`http://127.0.0.1:8765/visualizer.html`

Click `REFETCH` (or call `/api/load-data`). The server rebuilds:

- Rust: `backtest_comparison.js`
- i4bt: `i4bt_comparison.js`
- Live: `live_comparison.js`

## 4) Compare Sources in Visualizer

In Compare tab:

- Choose Source A and Source B (Backtest / I4BT / Live)
- Optional: toggle `ALL 3: ON` to overlay the third source on the same graph

This lets you compare:

- Rust vs i4bt
- Rust vs Live
- i4bt vs Live
- or all three at once on one chart
