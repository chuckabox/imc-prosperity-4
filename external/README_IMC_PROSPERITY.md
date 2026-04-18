# Rust backtester in this repo

The [prosperity_rust_backtester](https://github.com/GeyzsoN/prosperity_rust_backtester) sources live under `external/prosperity_rust_backtester/` as **normal tracked files** in this repo (vendored copy). If that folder used to look empty after `git clone`, it was because Git had stored only a **submodule pointer** (gitlink) without a `.gitmodules` file—clones do not download submodule contents unless configured. Vendoring avoids that.

## IMC Prosperity data layout here

Official-style capsule CSVs are under each round folder, for example:

- `ROUND 2/data_capsule/prices_round_2_day_*.csv`
- `ROUND 2/data_capsule/trades_round_2_day_*.csv`

The Rust CLI accepts a **directory** that contains paired `prices_*.csv` / `trades_*.csv` files. Pass an absolute path to `ROUND 2/data_capsule` (or `ROUND 1/data_capsule`) as `--dataset`:

```bash
rust_backtester --trader /path/to/trader.py --dataset /path/to/imc-prosperity-4/ROUND\ 2/data_capsule
```

Built-in aliases like `--dataset r2` resolve against the vendored `datasets/round2` tree inside the Rust project, not this repo’s capsule. For competition data, prefer the explicit path above.

## Rounds

| Round | Typical `--dataset` argument |
|-------|------------------------------|
| 1 | `…/ROUND 1/data_capsule` |
| 2 | `…/ROUND 2/data_capsule` |

## Windows

Upstream targets **Linux / WSL2** for building. On Windows, use WSL, or install the published binary with `cargo install rust_backtester` and put it on `PATH` (see upstream README).

## Python dashboard and backtesters

The Streamlit dashboard and `ROUND 2/tools/robust_backtester.py` use **IMC-only** datasets by default. Opt-in flags add scenarios or cached real-world normalized CSVs; network fetches are gated in `real_data_fetcher.py` via `IMC_PROSPERITY_ALLOW_REAL_FETCH=1`.
