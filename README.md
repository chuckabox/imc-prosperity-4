# IMC Prosperity 4 Trading Suite

Repository for multi-round strategy development, backtesting, and analysis.

## Project Layout

- `ROUND 1/`, `ROUND 2/`, ...: round-specific code and data
- `ROUND_TEMPLATE/`: scaffold for new rounds
- `tools/dashboard.py`: unified dashboard entrypoint (round selector built in)
- `imc-prosperity-4-backtester/`: external/backtesting reference engine

## Unified Dashboard

Run one dashboard for all rounds:

- `streamlit run "tools/dashboard.py" --server.port 8501 --server.headless true`

Inside the UI, use **Round Folder** in the sidebar to switch between `ROUND *` directories.

## Backtesting

Run robust backtests per round:

- `python "ROUND 1/tools/robust_backtester.py" "ROUND 1/traders/<your_file>.py" --quick`
- `python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/<your_file>.py" --quick`

## Create a New Round

1. Copy `ROUND_TEMPLATE/`
2. Rename it (example: `ROUND 3`)
3. Add data under `data_capsule/` and strategy files under `traders/`
4. Open unified dashboard and select the new round
