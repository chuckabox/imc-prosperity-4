# ROUND_TEMPLATE

Scaffold for creating a new round folder that works with the unified dashboard.

## How to use

1. Copy this folder
2. Rename (example: `ROUND 3`)
3. Add your data files into `data_capsule/`
4. Implement your strategy in `traders/trader.py` (or add more files)
5. Run:
   - `streamlit run "tools/dashboard.py"`
6. Select the new round from **Round Folder** in the sidebar

## Included structure

- `archive/`
- `config/` (includes `datamodel.py`, `config.json`, `__init__.py`)
- `data/`
- `data_capsule/`
- `docs/`
- `manual_trade/`
- `results/`
- `scratch/`
- `tools/` (includes `config.json`)
- `traders/` (includes starter `trader.py`)
