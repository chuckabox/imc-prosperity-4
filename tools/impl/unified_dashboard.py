import streamlit as st
import math
import json
import os
import sys
import glob
from pathlib import Path

# Resolve absolute paths for relative imports (datamodel in ../../ROUND 3/config, trader in ../../ROUND 3/traders)
script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
config_path = os.path.join(repo_root, "ROUND 3", "config")
traders_path = os.path.join(repo_root, "ROUND 3", "traders")

if config_path not in sys.path:
    sys.path.insert(0, config_path)
if traders_path not in sys.path:
    sys.path.insert(0, traders_path)

import pandas as pd
import altair as alt
import re
from datamodel import Listing, OrderDepth, TradingState, Observation, Order
import numpy as np


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

# Make root-level `tools` importable (for manual_optimiser package).
_ROOT_TOOLS = os.path.join(REPO_ROOT, "tools")
if _ROOT_TOOLS not in sys.path:
    sys.path.insert(0, _ROOT_TOOLS)
ROUND_DIRS = ["Root"] + sorted(
    d for d in os.listdir(REPO_ROOT)
    if d.startswith("ROUND ") and os.path.isdir(os.path.join(REPO_ROOT, d))
)
DEFAULT_ROUND = "ROUND 3"

# Round 3 datamodel uses 80; dashboard fills must match or simulation is meaningless.
DEFAULT_SIM_POSITION_LIMIT = 80


def robust_csv_trader_label(filename: str) -> str:
    """Strip known robust-result suffixes (ROUND 2 uses ``*_robust_results.csv``; unified tool uses ``*_results.csv``)."""
    for suf in ("_robust_results.csv", "_results.csv"):
        if filename.endswith(suf):
            return filename[: -len(suf)]
    return filename


def robust_results_csv_filenames(results_dir: str) -> list[str]:
    """List robust-style CSVs (exclude Monte Carlo / stress outputs)."""
    if not os.path.isdir(results_dir):
        return []
    out: list[str] = []
    for f in sorted(os.listdir(results_dir)):
        if not f.endswith(".csv"):
            continue
        if f.endswith("_robust_results.csv"):
            out.append(f)
        elif f.endswith("_results.csv") and not f.endswith("_mc_results.csv") and not f.endswith("_stress_results.csv"):
            out.append(f)
    return out


def _sim_position_limit(trader) -> int:
    return int(getattr(trader, "LIMIT", DEFAULT_SIM_POSITION_LIMIT))


def discover_trader_py_files(round_name: str | None = None) -> list[str]:
    td = get_paths(round_name)["traders_dir"]
    out: list[str] = []
    if not os.path.isdir(td):
        return out
    for root, _, files in os.walk(td):
        for f in files:
            if f.endswith(".py") and not f.startswith("__"):
                out.append(os.path.join(root, f))
    return sorted(out)


def load_trader_class_from_path(trader_py_path: str):
    """Load ``Trader`` from an arbitrary ``*.py`` under the active round's ``traders/`` tree."""
    sync_round_import_paths()
    import importlib.util

    tag = abs(hash(trader_py_path)) % (10**9)
    spec = importlib.util.spec_from_file_location(f"dash_trader_{tag}", trader_py_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load trader spec: {trader_py_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "Trader"):
        raise AttributeError(f"No class Trader in {trader_py_path}")
    return mod.Trader


def _gaussian_smooth_1d(y: np.ndarray, sigma: float = 15.0) -> np.ndarray:
    """1D Gaussian smoothing without scipy (convolution with normalized Gaussian kernel)."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 2:
        return y
    half = min(int(4 * sigma) + 1, max(1, n // 2))
    xs = np.arange(-half, half + 1, dtype=float)
    kernel = np.exp(-(xs**2) / (2.0 * sigma * sigma))
    kernel /= kernel.sum()
    return np.convolve(y, kernel, mode="same")


def get_paths(round_name: str | None = None) -> dict:
    rn = round_name or st.session_state.get("active_round", DEFAULT_ROUND)
    base_dir = REPO_ROOT if rn == "Root" else os.path.join(REPO_ROOT, rn)
    return {
        "round": rn,
        "base_dir": base_dir,
        "config_dir": os.path.join(base_dir, "config"),
        "config_file": os.path.join(base_dir, "tools", "config.json"),
        "data_dir": os.path.join(base_dir, "data_capsule"),
        "traders_dir": os.path.join(base_dir, "traders"),
        "results_robust_dir": os.path.join(base_dir, "results", "robust"),
        "tools_dir": os.path.join(base_dir, "tools"),
    }


def sync_round_import_paths(round_name: str | None = None):
    paths = get_paths(round_name)
    for p in [paths["config_dir"], paths["traders_dir"]]:
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)


def _active_round_number() -> str | None:
    rn = st.session_state.get("active_round", DEFAULT_ROUND)
    m = re.search(r"\d+", rn)
    return m.group(0) if m else None


def discover_available_days(data_dir: str) -> list[int]:
    round_num = _active_round_number()
    preferred = sorted(glob.glob(os.path.join(data_dir, f"prices_round_{round_num}_day_*.csv"))) if round_num else []
    files = preferred if preferred else sorted(glob.glob(os.path.join(data_dir, "prices_round_*_day_*.csv")))
    days = []
    for f in files:
        m = re.search(r"prices_round_\d+_day_(-?\d+)\.csv$", os.path.basename(f))
        if m:
            days.append(int(m.group(1)))
    return sorted(set(days))


def _resolve_round_day_file(data_dir: str, file_type: str, day: int) -> str | None:
    round_num = _active_round_number()
    preferred = os.path.join(data_dir, f"{file_type}_round_{round_num}_day_{day}.csv") if round_num else None
    if preferred and os.path.exists(preferred):
        return preferred
    candidates = sorted(glob.glob(os.path.join(data_dir, f"{file_type}_round_*_day_{day}.csv")))
    return candidates[0] if candidates else None

def load_config(round_name: str | None = None):
    defaults = {
        "osmium_active": True,
        "pepper_active": True,
        "osmium_limit": 80,
        "pepper_limit": 80,
        "emerald_active": True, # For legacy compat
        "tomato_active": True,
        "emerald_limit": 80,
        "tomato_limit": 80,
        "target_spread": 2,
        "mr_threshold": 2,
        "edge": 1.5,
        "skew": 0.2,
        "selected_day": -1
    }
    cfg_file = get_paths(round_name)["config_file"]
    if os.path.exists(cfg_file):
        with open(cfg_file, "r") as f:
            try:
                config = json.load(f)
                return {**defaults, **config}
            except:
                pass
    return defaults

def save_config(config, round_name: str | None = None):
    cfg_file = get_paths(round_name)["config_file"]
    with open(cfg_file, "w") as f:
        json.dump(config, f, indent=4)

# Emergency stop removed per user request
try:
    import optuna
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False

import logging
if OPTUNA_AVAILABLE:
    optuna.logging.set_verbosity(optuna.logging.WARNING)


def load_default_trader_class():
    sync_round_import_paths()
    trader_path = os.path.join(get_paths()["traders_dir"], "trader.py")
    if not os.path.exists(trader_path):
        active_round = st.session_state.get("active_round", DEFAULT_ROUND)
        raise FileNotFoundError(
            f"Missing `{active_round}/traders/trader.py`. "
            f"Please add a trader template before running simulation/optimizer.\nPath: {trader_path}"
        )
    import importlib.util
    spec = importlib.util.spec_from_file_location("default_round_trader", trader_path)
    trader_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trader_mod)
    return trader_mod.Trader

def execute_backtest_headless(day, trader_path, config_override=None):
    sync_round_import_paths()
    df_prices, df_trades = load_and_process_data(day)
    if df_prices is None: return 0
    
    # Dynamic Import
    import importlib.util
    spec = importlib.util.spec_from_file_location("trader_optim", trader_path)
    trader_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trader_mod)
    trader = trader_mod.Trader()

    if config_override:
        for k, v in config_override.items():
            if k == "osmium_limit" and hasattr(trader, 'limits'):
                trader.limits['ASH_COATED_OSMIUM'] = v
            elif k == "pepper_limit" and hasattr(trader, 'limits'):
                trader.limits['INTARIAN_PEPPER_ROOT'] = v
            else:
                setattr(trader, k, v)

    products = df_prices["product"].unique()
    listings = {p: Listing(p, p, "SEASHELLS") for p in products}
    positions = {p: 0 for p in products}
    cash = 0.0
    pnl_history = []
    current_trader_data = ""
    
    price_map = {}
    # ... grouping logic ... (kept same)
    for ts, group in df_prices.groupby("timestamp"):
        ts_depths = {}
        for _, row in group.iterrows():
            product = row["product"]
            depth = OrderDepth()
            bv = int(row["bid_volume_1"]) if "bid_volume_1" in row and pd.notna(row.get("bid_volume_1")) else 10
            av = int(row["ask_volume_1"]) if "ask_volume_1" in row and pd.notna(row.get("ask_volume_1")) else 10
            depth.buy_orders = {int(row["bid_price_1"]): max(1, bv)}
            depth.sell_orders = {int(row["ask_price_1"]): -max(1, av)}
            ts_depths[product] = (depth, row["ask_price_1"], row["bid_price_1"])
        price_map[ts] = ts_depths

    timestamps = sorted(price_map.keys())
    for ts in timestamps:
        ts_data = price_map[ts]
        order_depths = {p: d[0] for p, d in ts_data.items()}
        state = TradingState(traderData=current_trader_data, timestamp=ts, listings=listings,
                             order_depths=order_depths, own_trades={}, market_trades={},
                             position=positions, observations=Observation({}, {}))
        try:
            orders, _, new_trader_data = trader.run(state)
            current_trader_data = new_trader_data
        except Exception:
            orders = {}

        if not isinstance(orders, dict):
            orders = {}

        for product, order_list in orders.items():
            if product not in ts_data: continue
            _, curr_ask, curr_bid = ts_data[product]
            lim_attr = getattr(trader, "LIMIT", DEFAULT_SIM_POSITION_LIMIT)
            limit = getattr(trader, "limits", {}).get(product, lim_attr)
            
            for order in order_list:
                qty, price = order.quantity, order.price
                if qty > 0 and price >= curr_ask: # Buy order hitting the ask
                    rem_buy = limit - positions[product]
                    fill = min(qty, rem_buy) if rem_buy > 0 else 0
                    positions[product] += fill; cash -= fill * curr_ask
                elif qty < 0 and price <= curr_bid: # Sell order hitting the bid
                    rem_sell = limit + positions[product]
                    fill = min(-qty, rem_sell) if rem_sell > 0 else 0
                    positions[product] -= fill; cash += fill * curr_bid

        mtm = cash
        for product, pos in positions.items():
            if product in ts_data:
                mid = (ts_data[product][1] + ts_data[product][2]) / 2.0
                mtm += pos * mid
        pnl_history.append(mtm)

    return pnl_history[-1] if pnl_history else 0

def run_stress_backtest(trader_path, prices_dict, products, limits=80):
    """Runs a backtest on multiple price series synchronously."""
    sync_round_import_paths()
    import importlib.util
    spec = importlib.util.spec_from_file_location("trader_stress", trader_path)
    trader_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trader_mod)
    trader = trader_mod.Trader()

    listings = {p: Listing(p, p, "SEASHELLS") for p in products}
    positions = {p: 0 for p in products}
    cash = 0.0
    pnl_history = []
    current_trader_data = ""
    
    length = len(next(iter(prices_dict.values())))

    for ts in range(length):
        order_depths = {}
        mids = {}
        for p in products:
            mid = prices_dict[p][ts]
            mids[p] = mid
            spread = 6 if "PEPPER" in p else 2
            depth = OrderDepth()
            bid = math.floor(mid - spread/2.0)
            ask = math.ceil(mid + spread/2.0)
            depth.buy_orders = {bid: 15}
            depth.sell_orders = {ask: -15}
            order_depths[p] = depth
        
        state = TradingState(
            traderData=current_trader_data,
            timestamp=ts * 100,
            listings=listings,
            order_depths=order_depths,
            own_trades={},
            market_trades={},
            position=positions,
            observations=Observation({}, {})
        )
        
        try:
            orders, _, new_trader_data = trader.run(state)
            current_trader_data = new_trader_data
        except:
            mtm = cash + sum(positions[p] * mids[p] for p in products)
            pnl_history.append(mtm)
            continue

        for p, order_list in orders.items():
            if p not in order_depths: continue
            curr_ask = math.ceil(mids[p] + (6 if "PEPPER" in p else 2)/2.0)
            curr_bid = math.floor(mids[p] - (6 if "PEPPER" in p else 2)/2.0)
            
            p_limits = getattr(trader, 'limits', {})
            p_limit = p_limits.get(p, limits)
            for order in order_list:
                qty, price = order.quantity, order.price
                if qty > 0 and price >= curr_ask:
                    fill = min(qty, p_limit - positions[p])
                    if fill > 0:
                        positions[p] += fill
                        cash -= fill * curr_ask
                elif qty < 0 and price <= curr_bid:
                    fill = min(-qty, p_limit + positions[p])
                    if fill > 0:
                        positions[p] -= fill
                        cash += fill * curr_bid

        mtm = cash + sum(positions[p] * mids[p] for p in products)
        pnl_history.append(mtm)

    return {
        "pnl_curve": pnl_history,
        "final_pnl": pnl_history[-1],
        "max_dd": max([peak - val for peak, val in zip(np.maximum.accumulate(pnl_history), pnl_history)]),
        "final_pos": sum(abs(v) for v in positions.values())
    }

def run_backtest_simulation(day, trader_py_path: str | None = None):
    st.toast(f"Running simulation against Day {day}...")

    df_prices, df_trades = load_and_process_data(day)
    if df_prices is None:
        st.error("Missing data for simulation!")
        return

    if trader_py_path and os.path.isfile(trader_py_path):
        TraderClass = load_trader_class_from_path(trader_py_path)
    else:
        TraderClass = load_default_trader_class()
    trader = TraderClass()
    if not hasattr(trader, "traderData") or trader.traderData is None:
        trader.traderData = ""

    pos_limit = _sim_position_limit(trader)

    products = df_prices["product"].unique()
    listings = {p: Listing(p, p, "SEASHELLS") for p in products}
    positions = {p: 0 for p in products}
    cash = 0.0

    if "trades_log" not in st.session_state:
        st.session_state.trades_log = []
    st.session_state.trades_log = []

    pnl_history = []
    try:
        price_map = {}
        for ts, group in df_prices.groupby("timestamp"):
            ts_depths = {}
            for _, row in group.iterrows():
                product = row["product"]
                depth = OrderDepth()
                bv = (
                    int(row["bid_volume_1"])
                    if "bid_volume_1" in row and pd.notna(row.get("bid_volume_1"))
                    else 10
                )
                av = (
                    int(row["ask_volume_1"])
                    if "ask_volume_1" in row and pd.notna(row.get("ask_volume_1"))
                    else 10
                )
                depth.buy_orders = {int(row["bid_price_1"]): max(1, bv)}
                depth.sell_orders = {int(row["ask_price_1"]): -max(1, av)}
                ts_depths[product] = (depth, row["ask_price_1"], row["bid_price_1"])
            price_map[ts] = ts_depths

        trade_lookup = {}
        if df_trades is not None:
            for ts, group in df_trades.groupby("timestamp"):
                ts_trades = {}
                for product, p_group in group.groupby("product"):
                    ts_trades[product] = p_group.to_dict("records")
                trade_lookup[ts] = ts_trades

        timestamps = sorted(price_map.keys())
        total_steps = max(1, len(timestamps))
        progress_bar = st.progress(0)

        trader_data_state = trader.traderData

        for i, ts in enumerate(timestamps):
            if i % 500 == 0:
                progress_bar.progress((i + 1) / total_steps)

            ts_data = price_map[ts]
            order_depths = {p: d[0] for p, d in ts_data.items()}

            state = TradingState(
                traderData=trader_data_state,
                timestamp=ts,
                listings=listings,
                order_depths=order_depths,
                own_trades={},
                market_trades={},
                position=positions,
                observations=Observation({}, {}),
            )

            try:
                orders, _conversions, trader_data = trader.run(state)
                trader_data_state = trader_data
            except Exception as e:
                st.warning(f"Trader failed at timestamp {ts}: {str(e)}")
                orders = {}

            if not isinstance(orders, dict):
                orders = {}

            for product, order_list in orders.items():
                if product not in ts_data:
                    continue
                _, curr_ask, curr_bid = ts_data[product]

                for order in order_list:
                    qty = order.quantity
                    price = order.price
                    filled = False

                    if qty > 0 and price >= curr_ask:
                        fill_qty = min(qty, pos_limit - positions[product])
                        if fill_qty > 0:
                            positions[product] += fill_qty
                            cash -= fill_qty * curr_ask
                            filled = True
                            st.session_state.trades_log.append(
                                f"TS {ts}: AGG BUY {fill_qty} {product} @ {curr_ask}"
                            )
                    elif qty < 0 and price <= curr_bid:
                        fill_qty = min(-qty, positions[product] + pos_limit)
                        if fill_qty > 0:
                            positions[product] -= fill_qty
                            cash += fill_qty * curr_bid
                            filled = True
                            st.session_state.trades_log.append(
                                f"TS {ts}: AGG SELL {fill_qty} {product} @ {curr_bid}"
                            )

                    if not filled and ts in trade_lookup:
                        mkt_trades = trade_lookup[ts].get(product, [])
                        for trade in mkt_trades:
                            trade_price = int(trade["price"])
                            trade_qty = 1

                            if qty > 0 and price >= trade_price:
                                fill_qty = min(qty, pos_limit - positions[product], trade_qty)
                                if fill_qty > 0:
                                    positions[product] += fill_qty
                                    cash -= fill_qty * trade_price
                                    st.session_state.trades_log.append(
                                        f"TS {ts}: PASSIVE BUY {fill_qty} {product} @ {trade_price}"
                                    )
                                    break
                            elif qty < 0 and price <= trade_price:
                                fill_qty = min(-qty, positions[product] + pos_limit, trade_qty)
                                if fill_qty > 0:
                                    positions[product] -= fill_qty
                                    cash += fill_qty * trade_price
                                    st.session_state.trades_log.append(
                                        f"TS {ts}: PASSIVE SELL {fill_qty} {product} @ {trade_price}"
                                    )
                                    break

            mtm_pnl = cash
            for product, pos in positions.items():
                if product in ts_data:
                    mid = (ts_data[product][1] + ts_data[product][2]) / 2.0
                    mtm_pnl += pos * mid

            pnl_history.append(mtm_pnl)

    except Exception as e:
        st.error(f"Error during simulation: {str(e)}")
        import traceback

        st.code(traceback.format_exc())
        return

    final_pnl = pnl_history[-1] if pnl_history else 0
    st.session_state.sim_result = {
        "pnl": final_pnl,
        "day": day,
        "trader_path": trader_py_path or "",
    }
    st.success(f"Simulation Complete! Final PnL: **{final_pnl:,.2f}**")

    if st.session_state.trades_log:
        with st.expander("📝 View Trade History (Latest 50)", expanded=False):
            for t in reversed(st.session_state.trades_log[-50:]):
                st.text(t)

    if pnl_history:
        pnl_df = pd.DataFrame({"Timestamp": range(len(pnl_history)), "PnL": pnl_history})
        if len(pnl_df) > 1000:
            pnl_df = pnl_df.iloc[:: max(1, len(pnl_df) // 1000)]
        st.line_chart(pnl_df.set_index("Timestamp"), use_container_width=True)

# Disable caching temporarily to ensure fresh data for every backtest
# @st.cache_data
def load_and_process_data(day):
    data_dir = get_paths()["data_dir"]
    available_days = discover_available_days(data_dir)
    days_to_load = available_days if day == "All" else [day]
    all_prices = []
    all_trades = []

    base_day = min(available_days) if available_days else 0

    for d in days_to_load:
        prices_file = _resolve_round_day_file(data_dir, "prices", d)
        trades_file = _resolve_round_day_file(data_dir, "trades", d)

        if prices_file and os.path.exists(prices_file):
            df_p = pd.read_csv(prices_file, sep=";")
            df_p = df_p.dropna(subset=["bid_price_1", "ask_price_1", "timestamp"])
            if day == "All":
                offset = (d - base_day) * 1000000
                df_p["timestamp"] = df_p["timestamp"] + offset
            df_p["day"] = d
            all_prices.append(df_p)

        if trades_file and os.path.exists(trades_file):
            df_t = pd.read_csv(trades_file, sep=";")
            if "symbol" in df_t.columns:
                df_t = df_t.rename(columns={"symbol": "product"})
            if day == "All":
                offset = (d - base_day) * 1000000
                df_t["timestamp"] = df_t["timestamp"] + offset
            df_t["day"] = d
            all_trades.append(df_t)

    if not all_prices:
        return None, None
    
    df_prices = pd.concat(all_prices, ignore_index=True)
    df_prices["mid_price"] = (df_prices["bid_price_1"] + df_prices["ask_price_1"]) / 2.0
    
    # Avoid rounding timestamps as it breaks the drift logic.
    # Just resolve duplicates for the same timestamp/product if they exist.
    df_prices = df_prices.groupby(["timestamp", "product", "day"]).mean(numeric_only=True).reset_index()

    df_trades = pd.concat(all_trades, ignore_index=True) if all_trades else None

    st.info(f"Loaded {len(df_prices)} price rows total (Mode: {day}).")
    return df_prices, df_trades


def _resolve_target_pnls(df: pd.DataFrame, target_col: str, p_filter: str) -> tuple[pd.Series, bool]:
    """Return selected PnL column and whether data was missing for requested product filter."""
    if target_col in df.columns:
        return df[target_col], False
    if p_filter == "All":
        if "final_pnl" in df.columns:
            return df["final_pnl"], False
        return pd.Series([0.0] * len(df)), True
    return pd.Series([0.0] * len(df)), True


def _build_comparison_table(
    selected_files: list[str],
    robust_results_dir: str,
    target_col: str,
    p_filter: str,
    blowup_cutoff: float,
    weights: dict,
) -> pd.DataFrame:
    rows = []
    for filename in selected_files:
        path = os.path.join(robust_results_dir, filename)
        df = pd.read_csv(path)
        trader_name = robust_csv_trader_label(filename)
        pnls, data_missing = _resolve_target_pnls(df, target_col, p_filter)
        df = df.copy()
        df["target_pnl"] = pnls

        # Allow both robust labels (imc, real) and standard labels (round_1, round_2, round_3, real_world)
        imc = df.loc[df["category"].isin(["imc", "round_1", "round_2", "round_3"]), "target_pnl"] if "category" in df.columns else pd.Series([], dtype=float)
        real = df.loc[df["category"].isin(["real", "real_world"]), "target_pnl"] if "category" in df.columns else pd.Series([], dtype=float)
        scen = df.loc[df["category"] == "scenario", "target_pnl"] if "category" in df.columns else pd.Series([], dtype=float)
        allp = df["target_pnl"]

        row = {
            "Trader": trader_name + (" (⚠️ RECALC)" if data_missing else ""),
            "IMC Mean": imc.mean() if len(imc) else np.nan,
            "IMC Worst": imc.min() if len(imc) else np.nan,
            "Real Mean": real.mean() if len(real) else np.nan,
            "Real Win%": (real > 0).mean() * 100 if len(real) else np.nan,
            "Scen Mean": scen.mean() if len(scen) else np.nan,
            "Scen Worst": scen.min() if len(scen) else np.nan,
            "Full Mean": allp.mean() if len(allp) else np.nan,
            "Worst Day": allp.min() if len(allp) else np.nan,
            "Win%": (allp > 0).mean() * 100 if len(allp) else np.nan,
            "Blow-up%": (allp <= -abs(blowup_cutoff)).mean() * 100 if len(allp) else np.nan,
            "N": len(df),
        }
        rows.append(row)

    comp = pd.DataFrame(rows)
    if comp.empty:
        return comp

    for c in ("Real Mean", "Real Win%", "Scen Mean", "Scen Worst"):
        if c in comp.columns and comp[c].notna().sum() == 0:
            comp = comp.drop(columns=[c])

    # Auto-rank score: emphasize IMC + overall robustness (higher is better).
    rank_frame = comp.copy()
    higher_better = [c for c in ["IMC Mean", "Real Mean", "Scen Mean", "Full Mean", "Win%"] if c in rank_frame.columns]
    for c in higher_better:
        rank_frame[c] = rank_frame[c].rank(pct=True, ascending=True)
    lower_better = [c for c in ["IMC Worst", "Scen Worst", "Worst Day"] if c in rank_frame.columns]
    for c in lower_better:
        rank_frame[c] = rank_frame[c].rank(pct=True, ascending=True)
    rank_frame["Blow-up%"] = rank_frame["Blow-up%"].rank(pct=True, ascending=False)

    scen_rank = rank_frame["Scen Mean"] if "Scen Mean" in rank_frame.columns else pd.Series(0.5, index=rank_frame.index)
    comp["AutoScore"] = (
        weights["imc_mean"] * rank_frame["IMC Mean"]
        + weights["full_mean"] * rank_frame["Full Mean"]
        + weights["win_rate"] * rank_frame["Win%"]
        + weights["worst_day"] * rank_frame["Worst Day"]
        + weights["scen_mean"] * scen_rank
        + weights["blowup"] * rank_frame["Blow-up%"]
    ) * 100
    # NaN-safe ranking: files with missing score components are pushed to bottom.
    rank_series = comp["AutoScore"].rank(method="min", ascending=False, na_option="bottom")
    comp["Rank"] = rank_series.fillna(len(comp) + 1).astype(int)
    return comp.sort_values(["Rank", "AutoScore", "IMC Mean"], ascending=[True, False, False]).reset_index(drop=True)


def _algo_key_from_filename(filename: str) -> str:
    """Create a loose comparable key across rounds from robust CSV filename."""
    return robust_csv_trader_label(filename)


def _build_cross_round_comparison(
    selected_rounds: list[str],
    target_col: str,
    p_filter: str,
    blowup_cutoff: float,
    weights: dict,
) -> pd.DataFrame:
    rows = []
    for round_name in selected_rounds:
        r_paths = get_paths(round_name)
        robust_dir = r_paths["results_robust_dir"]
        fallback_dir = r_paths["tools_dir"]

        round_files: list[str] = []
        source_dir = None
        if os.path.isdir(robust_dir):
            candidates = robust_results_csv_filenames(robust_dir)
            if candidates:
                round_files = candidates
                source_dir = robust_dir
        if not round_files and os.path.isdir(fallback_dir):
            candidates = robust_results_csv_filenames(fallback_dir)
            if candidates:
                round_files = candidates
                source_dir = fallback_dir
        if not round_files or source_dir is None:
            continue
        for filename in round_files:
            path = os.path.join(source_dir, filename)
            try:
                df = pd.read_csv(path)
            except Exception:
                continue

            trader_name = robust_csv_trader_label(filename)
            pnls, data_missing = _resolve_target_pnls(df, target_col, p_filter)
            df = df.copy()
            df["target_pnl"] = pnls

            # Allow both robust labels (imc, real) and standard labels (round_1, round_2, round_3, real_world)
            imc = df.loc[df["category"].isin(["imc", "round_1", "round_2", "round_3"]), "target_pnl"] if "category" in df.columns else pd.Series([], dtype=float)
            real = df.loc[df["category"].isin(["real", "real_world"]), "target_pnl"] if "category" in df.columns else pd.Series([], dtype=float)
            scen = df.loc[df["category"] == "scenario", "target_pnl"] if "category" in df.columns else pd.Series([], dtype=float)
            allp = df["target_pnl"]

            rows.append({
                "Round": round_name,
                "Trader": trader_name + (" (⚠️ RECALC)" if data_missing else ""),
                "Algo Key": _algo_key_from_filename(filename),
                "IMC Mean": imc.mean() if len(imc) else np.nan,
                "IMC Worst": imc.min() if len(imc) else np.nan,
                "Real Mean": real.mean() if len(real) else np.nan,
                "Real Win%": (real > 0).mean() * 100 if len(real) else np.nan,
                "Scen Mean": scen.mean() if len(scen) else np.nan,
                "Scen Worst": scen.min() if len(scen) else np.nan,
                "Full Mean": allp.mean() if len(allp) else np.nan,
                "Worst Day": allp.min() if len(allp) else np.nan,
                "Win%": (allp > 0).mean() * 100 if len(allp) else np.nan,
                "Blow-up%": (allp <= -abs(blowup_cutoff)).mean() * 100 if len(allp) else np.nan,
                "N": len(df),
            })

    comp = pd.DataFrame(rows)
    if comp.empty:
        return comp

    for c in ("Real Mean", "Real Win%", "Scen Mean", "Scen Worst"):
        if c in comp.columns and comp[c].notna().sum() == 0:
            comp = comp.drop(columns=[c])

    rank_frame = comp.copy()
    higher_better = [c for c in ["IMC Mean", "Real Mean", "Scen Mean", "Full Mean", "Win%"] if c in rank_frame.columns]
    for c in higher_better:
        rank_frame[c] = rank_frame[c].rank(pct=True, ascending=True)
    lower_better = [c for c in ["IMC Worst", "Scen Worst", "Worst Day"] if c in rank_frame.columns]
    for c in lower_better:
        rank_frame[c] = rank_frame[c].rank(pct=True, ascending=True)
    rank_frame["Blow-up%"] = rank_frame["Blow-up%"].rank(pct=True, ascending=False)

    scen_rank = rank_frame["Scen Mean"] if "Scen Mean" in rank_frame.columns else pd.Series(0.5, index=rank_frame.index)
    comp["AutoScore"] = (
        weights["imc_mean"] * rank_frame["IMC Mean"]
        + weights["full_mean"] * rank_frame["Full Mean"]
        + weights["win_rate"] * rank_frame["Win%"]
        + weights["worst_day"] * rank_frame["Worst Day"]
        + weights["scen_mean"] * scen_rank
        + weights["blowup"] * rank_frame["Blow-up%"]
    ) * 100
    rank_series = comp["AutoScore"].rank(method="min", ascending=False, na_option="bottom")
    comp["Rank"] = rank_series.fillna(len(comp) + 1).astype(int)
    return comp.sort_values(["Rank", "AutoScore", "IMC Mean"], ascending=[True, False, False]).reset_index(drop=True)


def _matplotlib_available() -> bool:
    """``pandas.Styler.background_gradient`` delegates to matplotlib; avoid hard crash if missing."""
    try:
        import matplotlib  # noqa: F401

        return True
    except ImportError:
        return False


def _style_comparison_table(comp_df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    money_cols = ["IMC Mean", "IMC Worst", "Real Mean", "Scen Mean", "Scen Worst", "Full Mean", "Worst Day"]
    pct_cols = ["Real Win%", "Win%", "Blow-up%", "AutoScore"]
    low_is_good_cols = ["Blow-up%"]

    styler = comp_df.style
    if _matplotlib_available():
        for col in money_cols:
            if col in comp_df.columns:
                styler = styler.background_gradient(
                    cmap="RdYlGn",
                    subset=[col],
                    vmin=comp_df[col].min(skipna=True),
                    vmax=comp_df[col].max(skipna=True),
                )
        for col in pct_cols:
            if col in comp_df.columns:
                cmap = "RdYlGn_r" if col in low_is_good_cols else "RdYlGn"
                styler = styler.background_gradient(cmap=cmap, subset=[col])

    return styler.format({
        "Rank": "{:.0f}",
        "IMC Mean": "${:,.0f}",
        "IMC Worst": "${:,.0f}",
        "Real Mean": "${:,.0f}",
        "Scen Mean": "${:,.0f}",
        "Scen Worst": "${:,.0f}",
        "Full Mean": "${:,.0f}",
        "Worst Day": "${:,.0f}",
        "Real Win%": "{:.1f}%",
        "Win%": "{:.1f}%",
        "Blow-up%": "{:.1f}%",
        "AutoScore": "{:.1f}",
        "N": "{:.0f}",
    })

def render_chart(df_prices, df_trades, product, color, show_mean=False):
    df_p = df_prices[df_prices["product"] == product].copy()
    if df_p.empty:
        st.warning(f"No data for {product}")
        return

    is_multi_day = df_p['day'].nunique() > 1
    color_encoding = alt.Color('day:N', scale=alt.Scale(scheme='category10')) if is_multi_day else alt.value(color)

    line = alt.Chart(df_p).mark_line().encode(
        x=alt.X('timestamp:Q', title="Timestamp (Continuous)"),
        y=alt.Y('mid_price:Q', scale=alt.Scale(zero=False), title="Price"),
        color=color_encoding,
        tooltip=['day', 'timestamp', 'mid_price']
    )

    band = alt.Chart(df_p).mark_area(opacity=0.3).encode(
        x='timestamp:Q',
        y='bid_price_1:Q',
        y2='ask_price_1:Q',
        color=color_encoding
    )

    layers = [band, line]

    if show_mean:
        mean_val = df_p["mid_price"].mean()
        mean_line = alt.Chart(pd.DataFrame({'y': [mean_val]})).mark_rule(color='#e67e22', strokeDash=[5, 5], strokeWidth=2).encode(
            y='y:Q'
        )
        layers.append(mean_line)

    if df_trades is not None:
        df_t = df_trades[df_trades["product"] == product].copy()
        if not df_t.empty:
            scatter = alt.Chart(df_t).mark_circle(size=60, color='white', opacity=0.8, stroke='black').encode(
                x='timestamp:Q',
                y='price:Q',
                tooltip=['day', 'timestamp', 'price']
            )
            layers.append(scatter)

    chart = alt.layer(*layers).properties(
        width='container',
        height=320,
        title=f"{product} Price & Spread Overlay {'(All Days Concurrent)' if is_multi_day else ''}"
    ).interactive()

    # Downsample for Performance
    if len(df_p) > 2000:
        step = len(df_p) // 2000
        df_p = df_p.iloc[::step]
    
    st.altair_chart(chart, use_container_width=True)
    return df_p

def render_vev_chain_chart(df_prices, vev_strikes):
    df = df_prices[df_prices["product"].isin(vev_strikes)].copy()
    if df.empty:
        st.warning("No VEV chain data")
        return
    if len(df) > 6000:
        df = df.iloc[::max(1, len(df) // 6000)]
    chart = alt.Chart(df).mark_line(opacity=0.85).encode(
        x=alt.X('timestamp:Q', title="Timestamp"),
        y=alt.Y('mid_price:Q', scale=alt.Scale(zero=False), title="Mid Price"),
        color=alt.Color('product:N', title="Strike", scale=alt.Scale(scheme='turbo')),
        tooltip=['product', 'timestamp', 'mid_price']
    ).properties(width='container', height=320, title="VEV Options Chain Mid Prices").interactive()
    st.altair_chart(chart, use_container_width=True)


def render_total_chart(df_prices, df_trades):
    # Downsample for Performance
    df_p = df_prices.copy()
    if len(df_p) > 3000:
        step = len(df_p) // 3000
        df_p = df_p.iloc[::step]

    # Create a consolidated view of all products
    chart = alt.Chart(df_p).mark_line().encode(
        x=alt.X('timestamp:Q', title="Timestamp (Continuous)"),
        y=alt.Y('mid_price:Q', scale=alt.Scale(zero=False), title="Price"),
        color=alt.Color('product:N', scale=alt.Scale(scheme='set1'), title="Product"),
        tooltip=['day', 'timestamp', 'product', 'mid_price']
    ).properties(
        width='container',
        height=380,
        title="Total Market Price Reconstruction (All Assets)"
    ).interactive()

    st.altair_chart(chart, use_container_width=True)

def render_reversal_chart(df, product, start_idx=0, window=1000):
    # Aesthetic Palette (Match Image)
    TRUE_FV_COLOR = "#2D6A4F"
    INFERRED_FV_COLOR = "#6c757d"
    CRASH_COLOR = "#8B4513"
    BG_COLOR = "#ffffff" # High contrast white like image
    GRID_COLOR = "#dddddd"

    # Data Slicing
    if df is not None and not df.empty and product in df['product'].values:
        df_all = df[df["product"] == product].copy()
        df_p = df_all.iloc[start_idx : start_idx + window].copy()
        x = np.arange(len(df_p))
        y_raw = df_p["mid_price"].values
    else:
        # Synthetic data matching the image's "Crash" pattern
        x = np.linspace(0, 1000, 1000)
        y_true = np.concatenate([
            np.linspace(12000, 12050, 500),
            np.linspace(12050, 11875, 500)
        ])
        y_raw = y_true + np.random.normal(0, 15, 1000)
        y_price = y_true # Smooth line

    # Compute Smooth Line (True FV) — numpy-only (no matplotlib/scipy)
    y_smooth = _gaussian_smooth_1d(y_raw, sigma=15)
    slope = np.gradient(y_smooth)
    crash_idx = int(np.argmax(y_smooth))

    df_plot = pd.DataFrame(
        {"tick": x.astype(float), "y_smooth": y_smooth, "y_raw": y_raw, "slope": slope}
    )

    base_x = alt.X("tick:Q", title="Tick")

    c_smooth = (
        alt.Chart(df_plot)
        .mark_line(strokeWidth=3, color=TRUE_FV_COLOR)
        .encode(base_x, y=alt.Y("y_smooth:Q", title="Fair value", scale=alt.Scale(zero=False)))
    )
    c_raw = (
        alt.Chart(df_plot)
        .mark_line(strokeWidth=1, opacity=0.6, color=INFERRED_FV_COLOR)
        .encode(base_x, y="y_raw:Q")
    )
    c_slope = (
        alt.Chart(df_plot)
        .mark_line(strokeWidth=1, opacity=0.45, color=INFERRED_FV_COLOR)
        .encode(
            base_x,
            y=alt.Y(
                "slope:Q",
                title="Estimated slope / tick",
                axis=alt.Axis(orient="right"),
            ),
        )
    )
    crash_df = pd.DataFrame({"crash_x": [float(crash_idx)]})
    crash_line = (
        alt.Chart(crash_df)
        .mark_rule(color=CRASH_COLOR, strokeWidth=1.5, strokeDash=[6, 4])
        .encode(x=alt.X("crash_x:Q", title="Tick"))
    )

    chart = (
        alt.layer(c_smooth, c_raw, c_slope, crash_line)
        .resolve_scale(y="independent")
        .properties(width="container", height=320, title="Reversal / crash view (Altair)")
    )
    st.altair_chart(chart, use_container_width=True)
    st.caption(f"Crash marker @ local tick {crash_idx} (session offset {start_idx}).")

def forge_trader():
    TRADER_TEMPLATE = os.path.join(get_paths()["traders_dir"], "trader.py")
    if not os.path.exists(TRADER_TEMPLATE):
        st.error(f"Template not found at {TRADER_TEMPLATE}")
        return

    with open(TRADER_TEMPLATE, "r") as f:
        text = f.read()

    derived_spread = max(1, int(st.session_state.analysis["pep_std"] / 2.0))
    derived_fv = int(st.session_state.analysis["os_mean"])

    config_rendered = {
        "osmium_active": st.session_state.config["osmium_active"],
        "pepper_active": st.session_state.config["pepper_active"],
        "osmium_limit": st.session_state.config["osmium_limit"],
        "pepper_limit": st.session_state.config["pepper_limit"],
        "target_spread": derived_spread,
        "mr_threshold": st.session_state.config["mr_threshold"]
    }

    # Use json.dumps but fix the capitalization for Python
    replacement_config = "self.config = " + json.dumps(config_rendered, indent=8).replace("true", "True").replace("false", "False")

    text = re.sub(r"self\.config\s*=\s*\{.*?\}", replacement_config, text, flags=re.DOTALL)

    text = re.sub(r"def load_config\(self\):.*?def send_sell_order", "def load_config(self):\n        pass\n\n    def send_sell_order", text, flags=re.DOTALL)
    text = text.replace("fair_value = 10000", f"fair_value = {derived_fv}")

    # Validation Step: Dummy Check for Python Syntax
    import ast
    try:
        ast.parse(text)
        st.session_state.forged_code = text
        st.toast("Trader.py beautifully forged and validated.")
    except SyntaxError as e:
        st.error(f"Forge failed! Generated code has a syntax error: {e}")

def perform_auto_analysis():
    days = discover_available_days(get_paths()["data_dir"])
    preferred = [d for d in [-2, -1, 0] if d in days]
    sample_days = preferred if preferred else days[:3]
    frames = []
    for d in sample_days:
        df_d, _ = load_and_process_data(d)
        if df_d is not None:
            frames.append(df_d)

    if not frames:
        st.error("Cannot run analysis! No day files found in selected round data_capsule.")
        return

    df = pd.concat(frames)
    stats = {}
    for p in df["product"].unique():
        p_df = df[df["product"] == p]
        stats[f"{p}_mean"] = p_df["mid_price"].mean()
        stats[f"{p}_std"] = p_df["mid_price"].std()

    st.session_state.analysis = stats
    st.toast("Analysis Successful!")


def render_manual_optimizer_tab():
    """Delegates to unified implementation in manual_optimiser.dashboard_tab."""
    from manual_optimiser.dashboard_tab import render_manual_optimizer_tab as _impl
    _impl()


# ---------- Strategy Lab (R3) ----------
import math as _math

VEV_STRIKES_R3 = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]


def _norm_cdf_dash(x):
    return 0.5 * (1 + _math.erf(x / _math.sqrt(2)))


def _bs_call_dash(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K)
    d1 = (_math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * _math.sqrt(T))
    d2 = d1 - sigma * _math.sqrt(T)
    return S * _norm_cdf_dash(d1) - K * _norm_cdf_dash(d2)


def _implied_vol_dash(price, S, K, T, lo=1e-4, hi=2.0, n=80):
    intrinsic = max(0.0, S - K)
    if price <= intrinsic + 1e-6 or price >= S:
        return None
    for _ in range(n):
        mid = 0.5 * (lo + hi)
        if _bs_call_dash(S, K, T, mid) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-5:
            break
    return 0.5 * (lo + hi)


@st.cache_data(show_spinner=False)
def _compute_iv_surface(days_tuple: tuple) -> pd.DataFrame:
    data_dir = get_paths()["data_dir"]
    frames = []
    for d in days_tuple:
        f = os.path.join(data_dir, f"prices_round_3_day_{d}.csv")
        if os.path.exists(f):
            df = pd.read_csv(f, sep=";")
            df["day"] = d
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True).dropna(subset=["bid_price_1", "ask_price_1"])
    df["mid"] = (df["bid_price_1"] + df["ask_price_1"]) / 2.0
    pv = df.pivot_table(index=["day", "timestamp"], columns="product", values="mid").sort_index()
    if "VELVETFRUIT_EXTRACT" not in pv.columns:
        return pd.DataFrame()
    rows = []
    sample = pv.iloc[::50]
    TOTAL_DAYS = 8
    for (d, ts), row in sample.iterrows():
        S = row.get("VELVETFRUIT_EXTRACT")
        if pd.isna(S):
            continue
        TTE = (TOTAL_DAYS - d) - ts / 1_000_000
        if TTE <= 0:
            continue
        for K in VEV_STRIKES_R3:
            p = row.get(f"VEV_{K}")
            if pd.isna(p) or p <= 0:
                continue
            iv = _implied_vol_dash(p, S, K, TTE)
            if iv is None:
                continue
            rows.append({"day": d, "ts": ts, "K": K, "S": S, "price": p, "TTE": TTE, "iv": iv,
                         "moneyness": _math.log(K / S)})
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def _load_r3_prices(days_tuple: tuple) -> pd.DataFrame:
    data_dir = get_paths()["data_dir"]
    frames = []
    for d in days_tuple:
        f = os.path.join(data_dir, f"prices_round_3_day_{d}.csv")
        if os.path.exists(f):
            x = pd.read_csv(f, sep=";")
            x["src_day"] = d
            frames.append(x)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["bid_price_1", "ask_price_1"]).copy()
    out["mid"] = (out["bid_price_1"] + out["ask_price_1"]) / 2.0
    out["spread"] = out["ask_price_1"] - out["bid_price_1"]
    return out


@st.cache_data(show_spinner=False)
def _compute_option_alpha_scan(days_tuple: tuple, ema_span: int, fwd_horizon: int, z_thresh: float) -> pd.DataFrame:
    df = _load_r3_prices(days_tuple)
    if df.empty:
        return pd.DataFrame()

    pv = df.pivot_table(index=["src_day", "timestamp"], columns="product", values="mid").sort_index()
    if "VELVETFRUIT_EXTRACT" not in pv.columns:
        return pd.DataFrame()
    S = pv["VELVETFRUIT_EXTRACT"]

    rows = []
    for K in VEV_STRIKES_R3:
        sym = f"VEV_{K}"
        if sym not in pv.columns:
            continue
        prem = pv[sym] - np.maximum(S - K, 0.0)
        prem = prem.dropna()
        if len(prem) < max(300, fwd_horizon + 20):
            continue

        ema = prem.ewm(span=ema_span, adjust=False).mean()
        dev = prem - ema
        fwd = prem.shift(-fwd_horizon) - prem
        vol = dev.rolling(300, min_periods=120).std()
        z = dev / vol.replace(0, np.nan)
        sig = pd.DataFrame({"dev": dev, "fwd": fwd, "z": z}).dropna()
        if sig.empty:
            continue

        corr = float(sig["dev"].corr(sig["fwd"]))
        extremes = sig[sig["z"].abs() >= z_thresh]
        if extremes.empty:
            hit_rate = np.nan
            edge_ticks = np.nan
            n_extreme = 0
        else:
            good = ((extremes["dev"] > 0) & (extremes["fwd"] < 0)) | ((extremes["dev"] < 0) & (extremes["fwd"] > 0))
            hit_rate = float(good.mean())
            edge_ticks = float(extremes["fwd"].abs().mean())
            n_extreme = int(len(extremes))

        s = df[df["product"] == sym]
        mean_spread = float(s["spread"].mean()) if not s.empty else np.nan
        edge_to_spread = edge_ticks / mean_spread if (pd.notna(edge_ticks) and pd.notna(mean_spread) and mean_spread > 0) else np.nan

        rows.append(
            {
                "Strike": K,
                "Corr(dev, fwdPrem)": corr,
                "ExtremeHitRate": hit_rate,
                "AvgAbsFwdMove": edge_ticks,
                "MeanSpread": mean_spread,
                "MoveToSpread": edge_to_spread,
                "ExtremeSamples": n_extreme,
            }
        )

    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    return out.sort_values(["MoveToSpread", "ExtremeHitRate"], ascending=False)


@st.cache_data(show_spinner=False)
def _compute_alpha_mining_tables(days_tuple: tuple) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw = _load_r3_prices(days_tuple)
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    def _signal_stats(series: pd.Series, span: int, horizon: int, z_thr: float) -> dict:
        x = series.reset_index(drop=True)
        ema = x.ewm(span=span, adjust=False).mean()
        dev = x - ema
        fwd = x.shift(-horizon) - x
        vol = dev.rolling(500, min_periods=250).std().replace(0, np.nan)
        z = dev / vol
        d = pd.DataFrame({"dev": dev, "fwd": fwd, "z": z}).dropna()
        if d.empty:
            return {"n": 0, "hit": np.nan, "edge": np.nan, "corr": np.nan}
        ext = d[d["z"].abs() >= z_thr]
        if ext.empty:
            return {"n": 0, "hit": np.nan, "edge": np.nan, "corr": float(d["dev"].corr(d["fwd"]))}
        hit = (((ext["dev"] > 0) & (ext["fwd"] < 0)) | ((ext["dev"] < 0) & (ext["fwd"] > 0))).mean()
        return {
            "n": int(len(ext)),
            "hit": float(hit),
            "edge": float(ext["fwd"].abs().mean()),
            "corr": float(d["dev"].corr(d["fwd"])),
        }

    under_rows = []
    for p in ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"]:
        sub = raw[raw["product"] == p].sort_values(["src_day", "timestamp"]).copy()
        if sub.empty:
            continue
        s = sub["mid"]
        stt = _signal_stats(s, span=220, horizon=50, z_thr=1.5)
        mean_spread = float(sub["spread"].mean())
        under_rows.append(
            {
                "Product": p,
                "RetLag1AC": float(s.diff().dropna().autocorr(lag=1)),
                "Corr(dev,fwd50)": stt["corr"],
                "ExtremeHitRate": stt["hit"],
                "ExtremeCount": stt["n"],
                "AvgAbsFwdMove": stt["edge"],
                "MeanSpread": mean_spread,
                "MoveToSpread": float(stt["edge"] / mean_spread) if stt["edge"] and mean_spread > 0 else np.nan,
            }
        )
    under_df = pd.DataFrame(under_rows)

    vev_rows = []
    pv = raw.pivot_table(index=["src_day", "timestamp"], columns="product", values="mid").sort_index()
    if "VELVETFRUIT_EXTRACT" in pv.columns:
        S = pv["VELVETFRUIT_EXTRACT"]
        for c in [c for c in pv.columns if str(c).startswith("VEV_")]:
            try:
                K = int(str(c).split("_")[1])
            except Exception:
                continue
            prem = (pv[c] - np.maximum(S - K, 0.0)).dropna()
            if len(prem) < 1200:
                continue
            stt = _signal_stats(prem, span=120, horizon=50, z_thr=1.5)
            mspread = float(raw[raw["product"] == c]["spread"].mean())
            vev_rows.append(
                {
                    "Strike": K,
                    "Corr(dev,fwdPrem50)": stt["corr"],
                    "ExtremeHitRate": stt["hit"],
                    "ExtremeCount": stt["n"],
                    "AvgAbsFwdPremMove": stt["edge"],
                    "MeanSpread": mspread,
                    "MoveToSpread": float(stt["edge"] / mspread) if stt["edge"] and mspread > 0 else np.nan,
                }
            )
    vev_df = pd.DataFrame(vev_rows)
    if not vev_df.empty:
        vev_df = vev_df.sort_values("MoveToSpread", ascending=False)

    lead_rows = []
    if "HYDROGEL_PACK" in pv.columns and "VELVETFRUIT_EXTRACT" in pv.columns:
        h = pv["HYDROGEL_PACK"].reset_index(drop=True).diff()
        v = pv["VELVETFRUIT_EXTRACT"].reset_index(drop=True).diff()
        for lag in [1, 2, 3, 5, 8, 13, 21]:
            d = pd.DataFrame({"h": h, "v_lead": v.shift(-lag)}).dropna()
            if len(d) > 1000:
                lead_rows.append({"Signal": "hydro_ret_t -> vfe_ret_t+lag", "Lag": lag, "Corr": float(d["h"].corr(d["v_lead"]))})
        for lag in [1, 2, 3, 5, 8, 13, 21]:
            d = pd.DataFrame({"v": v, "h_lead": h.shift(-lag)}).dropna()
            if len(d) > 1000:
                lead_rows.append({"Signal": "vfe_ret_t -> hydro_ret_t+lag", "Lag": lag, "Corr": float(d["v"].corr(d["h_lead"]))})
    lead_df = pd.DataFrame(lead_rows)
    if not lead_df.empty:
        lead_df["AbsCorr"] = lead_df["Corr"].abs()
        lead_df = lead_df.sort_values("AbsCorr", ascending=False)

    return under_df, vev_df, lead_df


def render_strategy_lab_tab():
    st.header("🧪 Strategy Lab — R3 Alpha Diagnostics")
    st.caption("Interactive analysis of IV scalping, gamma scalping, mean-reversion. **Days 0+1 only — Day 2 hidden.**")

    days_avail = discover_available_days(get_paths()["data_dir"])
    train_days = [d for d in days_avail if d in (0, 1)]
    if not train_days:
        st.warning("No R3 train data (days 0,1) found.")
        return
    st.info(f"Training set: days {train_days}. Day 2 NOT loaded here.")

    sub = st.tabs(["1. IV Surface", "2. Gamma Edge", "3. Mean Reversion", "4. Hybrid Sizing", "5. Alpha Scanner", "6. Alpha Mining"])

    iv_df = _compute_iv_surface(tuple(train_days))
    if iv_df.empty:
        st.error("Failed to compute IV surface.")
        return

    # --- Tab 1: IV surface + parabolic fit ---
    with sub[0]:
        st.subheader("Implied Vol Surface (per strike)")
        st.markdown("**Fit** `IV = a*moneyness² + b*moneyness + c` per snapshot. Deviation = mispricing signal.")

        iv_stats = iv_df.groupby("K")["iv"].agg(["mean", "std", "count"]).reset_index()
        iv_stats.columns = ["Strike", "Mean IV", "Std IV", "N"]
        st.dataframe(iv_stats, use_container_width=True, hide_index=True)

        c1 = alt.Chart(iv_df).mark_circle(opacity=0.5, size=20).encode(
            x=alt.X("moneyness:Q", title="log(K/S)"),
            y=alt.Y("iv:Q", scale=alt.Scale(zero=False), title="Implied Vol"),
            color=alt.Color("K:N", title="Strike"),
            tooltip=["K", "iv", "moneyness", "S"],
        ).properties(height=380, title="IV vs Moneyness")
        st.altair_chart(c1, use_container_width=True)

        # parabolic fit residuals
        residuals = []
        for (d, ts), grp in iv_df.groupby(["day", "ts"]):
            if len(grp) < 4:
                continue
            try:
                coefs = np.polyfit(grp["moneyness"].values, grp["iv"].values, 2)
            except np.linalg.LinAlgError:
                continue
            for _, r in grp.iterrows():
                fair = np.polyval(coefs, r["moneyness"])
                residuals.append({"day": d, "ts": ts, "K": r["K"], "iv_dev": r["iv"] - fair,
                                  "fair_iv": fair, "S": r["S"], "TTE": r["TTE"], "price": r["price"]})
        res_df = pd.DataFrame(residuals)
        if res_df.empty:
            st.info("Not enough snapshots to estimate IV deviation robustly.")
        else:
            st.markdown("**IV Deviation per Strike** (positive = overpriced vs smile)")
            dev_stats = res_df.groupby("K")["iv_dev"].agg(["mean", "std", "count"]).reset_index()
            st.dataframe(dev_stats, use_container_width=True, hide_index=True)

            # autocorr
            ac_rows = []
            for K, g in res_df.groupby("K"):
                s = g.sort_values(["day", "ts"])["iv_dev"].values
                if len(s) > 20:
                    ac_rows.append({"K": K, "lag1_autocorr": float(np.corrcoef(s[:-1], s[1:])[0, 1]), "n": len(s)})
            ac_df = pd.DataFrame(ac_rows)
            st.markdown("**Lag-1 Autocorrelation of IV Deviation**")
            st.caption("Negative = mean-reverting (good for IV scalping). Positive = trending (avoid naive entry).")
            st.dataframe(ac_df, use_container_width=True, hide_index=True)

    # --- Tab 2: Gamma scalping edge ---
    with sub[1]:
        st.subheader("Realised vs Implied Vol (Gamma Edge)")
        data_dir = get_paths()["data_dir"]
        s_frames = []
        for d in train_days:
            f = os.path.join(data_dir, f"prices_round_3_day_{d}.csv")
            df = pd.read_csv(f, sep=";")
            df = df[df["product"] == "VELVETFRUIT_EXTRACT"].dropna(subset=["bid_price_1", "ask_price_1"])
            df["mid"] = (df["bid_price_1"] + df["ask_price_1"]) / 2.0
            df["day"] = d
            s_frames.append(df[["day", "timestamp", "mid"]])
        S_df = pd.concat(s_frames, ignore_index=True).sort_values(["day", "timestamp"])
        log_ret = np.log(S_df["mid"] / S_df["mid"].shift(1)).dropna()
        real_vol = float(log_ret.std() * _math.sqrt(10000))  # per-day vol
        atm_iv = float(iv_df[iv_df["K"].between(5000, 5500)]["iv"].mean())
        c1, c2, c3 = st.columns(3)
        c1.metric("Realised Vol (per day)", f"{real_vol*100:.2f}%")
        c2.metric("ATM Implied Vol (per day)", f"{atm_iv*100:.2f}%")
        c3.metric("Gamma Edge (real - impl)", f"{(real_vol-atm_iv)*100:+.2f}%",
                  help="Positive => buy gamma + delta-hedge profitable in expectation")
        if real_vol > atm_iv:
            st.success(f"Realised > Implied by {(real_vol-atm_iv)*100:.2f} pp/day. **Gamma scalping has positive expected value.**")
        else:
            st.warning("Implied >= Realised. Gamma scalping unprofitable; sell vol instead.")

        st.markdown("**Suggested σ_model for fair-value pricing:** `0.018` (between realised and impl, conservative haircut).")

    # --- Tab 3: Mean reversion check ---
    with sub[2]:
        st.subheader("EMA Mean Reversion (VFE underlying)")
        S_series = S_df["mid"].reset_index(drop=True)
        rows = []
        for span in [50, 100, 200, 500, 1000]:
            ema = S_series.ewm(span=span, adjust=False).mean()
            dev = S_series - ema
            for fwd_horizon in [50, 100, 200]:
                fwd = S_series.shift(-fwd_horizon) - S_series
                ev = pd.DataFrame({"dev": dev, "fwd": fwd}).dropna()
                if len(ev) < 100:
                    continue
                rows.append({"EMA span": span, "Fwd horizon": fwd_horizon,
                             "corr(dev, fwd)": float(ev["dev"].corr(ev["fwd"]))})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("Negative correlation = mean-reverting (price above EMA → falls). Useful only if magnitude > 0.05.")

        st.subheader("HYDROGEL_PACK Stationarity")
        h_frames = []
        for d in train_days:
            f = os.path.join(data_dir, f"prices_round_3_day_{d}.csv")
            df = pd.read_csv(f, sep=";")
            df = df[df["product"] == "HYDROGEL_PACK"].dropna(subset=["bid_price_1", "ask_price_1"])
            df["mid"] = (df["bid_price_1"] + df["ask_price_1"]) / 2.0
            df["day"] = d
            h_frames.append(df[["day", "timestamp", "mid"]])
        H_df = pd.concat(h_frames, ignore_index=True)
        H = H_df["mid"]
        h_ret = H.diff().dropna()
        c1, c2, c3 = st.columns(3)
        c1.metric("Mean", f"{H.mean():.2f}")
        c2.metric("Std", f"{H.std():.2f}")
        c3.metric("Return Lag-1 AC", f"{float(np.corrcoef(h_ret[:-1], h_ret[1:])[0,1]):+.3f}")
        st.caption("Stationary + negative return autocorr → market-making profitable around mean.")

    # --- Tab 4: hybrid sizing ---
    with sub[3]:
        st.subheader("Hybrid Strategy Sizing")
        st.markdown("""
        Based on diagnostics:

        | Module | Edge source | Size weight | Notes |
        |---|---|---|---|
        | HYDROGEL MM | stationarity + neg autocorr | 40% | Defensive base PnL |
        | VEV gamma | realised >> implied | 40% | Buy ATM, hedge VFE |
        | VFE EMA mean-rev | weak signal | 10% | Small fixed threshold |
        | IV scalping (parabolic) | persistent mispricing | 10% | Trade only strikes with neg autocorr |

        **Sanity check:** if backtest PnL > 200k on train, suspect overfit (oracle ceiling ~155k).
        Train days 0+1, lock all params, run Day 2 ONCE.
        """)
        st.warning("Day 2 evaluation is INTENTIONALLY not exposed in this tab. Use `validate_trader2.py` once.")

    with sub[4]:
        st.subheader("Strike-Level Alpha Scanner")
        st.caption("Ranks option strikes by mean-reversion quality and move-vs-spread efficiency.")
        c1, c2, c3 = st.columns(3)
        with c1:
            ema_span = st.slider("Premium EMA span", min_value=40, max_value=300, value=120, step=10)
        with c2:
            fwd_h = st.slider("Forward horizon", min_value=20, max_value=200, value=50, step=10)
        with c3:
            z_th = st.slider("Extreme threshold |z|", min_value=1.0, max_value=3.0, value=1.5, step=0.1)

        scan = _compute_option_alpha_scan(tuple(train_days), ema_span=ema_span, fwd_horizon=fwd_h, z_thresh=z_th)
        if scan.empty:
            st.info("No option scan rows available with current parameters.")
        else:
            st.dataframe(
                scan,
                column_config={
                    "Strike": st.column_config.NumberColumn("Strike", format="%d"),
                    "Corr(dev, fwdPrem)": st.column_config.NumberColumn("Corr(dev, fwdPrem)", format="%.3f", help="More negative implies stronger premium mean reversion."),
                    "ExtremeHitRate": st.column_config.NumberColumn("Hit rate", format="%.3f", help="At |z| threshold, fraction of times premium reverts in expected direction."),
                    "AvgAbsFwdMove": st.column_config.NumberColumn("Avg |fwd move|", format="%.3f"),
                    "MeanSpread": st.column_config.NumberColumn("Mean spread", format="%.3f"),
                    "MoveToSpread": st.column_config.NumberColumn("Move/spread", format="%.2f", help="Higher means easier to monetize after costs."),
                    "ExtremeSamples": st.column_config.NumberColumn("Samples", format="%d"),
                },
                use_container_width=True,
                hide_index=True,
            )

            top = scan.head(3).copy()
            top["label"] = top["Strike"].astype(str)
            bar = alt.Chart(top).mark_bar().encode(
                x=alt.X("label:N", title="Top Strikes"),
                y=alt.Y("MoveToSpread:Q", title="Move / Spread"),
                color=alt.Color("Corr(dev, fwdPrem):Q", scale=alt.Scale(scheme="redyellowgreen"), title="Corr(dev,fwd)"),
                tooltip=["Strike", "MoveToSpread", "ExtremeHitRate", "ExtremeSamples"],
            ).properties(height=250, title="Most Monetizable Strikes")
            st.altair_chart(bar, use_container_width=True)

        st.markdown("---")
        st.subheader("Underlying Signal Quality (for baseline sizing)")
        raw = _load_r3_prices(tuple(train_days))
        if raw.empty:
            st.info("No base price data loaded.")
        else:
            q_rows = []
            for p in ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"]:
                subp = raw[raw["product"] == p].sort_values(["src_day", "timestamp"]).copy()
                if len(subp) < 1000:
                    continue
                series = subp["mid"].reset_index(drop=True)
                ret = series.diff().dropna()
                ac = float(ret.autocorr(lag=1))
                ema = series.ewm(span=400, adjust=False).mean()
                dev = series - ema
                fwd = series.shift(-100) - series
                ev = pd.DataFrame({"dev": dev, "fwd": fwd}).dropna()
                mr_corr = float(ev["dev"].corr(ev["fwd"])) if not ev.empty else np.nan
                spread = float(subp["spread"].mean())
                q_rows.append(
                    {
                        "Product": p,
                        "Lag1 Ret AC": ac,
                        "Corr(dev, fwd)": mr_corr,
                        "Mean spread": spread,
                        "Mean mid": float(series.mean()),
                    }
                )
            if q_rows:
                qdf = pd.DataFrame(q_rows)
                st.dataframe(qdf, use_container_width=True, hide_index=True)
                st.caption("Interpretation: negative lag1 AC and negative corr(dev, fwd) favor market-making / mean-reversion entries.")

    with sub[5]:
        st.subheader("Alpha Mining (Ranked Signals)")
        st.caption("Data-mined signal ranking focused on monetizable edge (move vs spread), not just raw correlation.")
        under_df, vev_df, lead_df = _compute_alpha_mining_tables(tuple(train_days))

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Underlyings (Hydro / VFE)**")
            if under_df.empty:
                st.info("No underlying mining rows.")
            else:
                st.dataframe(under_df, use_container_width=True, hide_index=True)
        with c2:
            st.markdown("**VEV Strike Ranking**")
            if vev_df.empty:
                st.info("No VEV mining rows.")
            else:
                st.dataframe(vev_df, use_container_width=True, hide_index=True)

        st.markdown("**Lead/Lag Cross-Asset Checks**")
        if lead_df.empty:
            st.info("No lead/lag rows.")
        else:
            st.dataframe(lead_df.head(12), use_container_width=True, hide_index=True)

        if not vev_df.empty:
            chart = (
                alt.Chart(vev_df)
                .mark_circle(size=110, opacity=0.85)
                .encode(
                    x=alt.X("MoveToSpread:Q", title="Move / Spread"),
                    y=alt.Y("ExtremeHitRate:Q", title="Extreme Hit Rate"),
                    color=alt.Color("Corr(dev,fwdPrem50):Q", title="Corr(dev,fwdPrem50)"),
                    tooltip=["Strike", "MoveToSpread", "ExtremeHitRate", "ExtremeCount", "Corr(dev,fwdPrem50)"],
                )
                .properties(height=320, title="VEV Signal Frontier")
                .interactive()
            )
            st.altair_chart(chart, use_container_width=True)

        st.markdown("**Suggested workflow**")
        st.markdown(
            """
            1. Pick 1-3 strikes with highest `MoveToSpread` and acceptable `ExtremeHitRate`.
            2. Prefer underlyings where `RetLag1AC < 0` and `Corr(dev,fwd50) < 0`.
            3. Use lead/lag only if absolute correlation is meaningfully non-zero.
            """
        )


def render_rust_backtester_tab():
    st.header("🦀 Backtester Results (Rust + prosperity4bt)")
    st.markdown(
        "Leaderboard merges native Rust runs **and** [`prosperity4bt`](https://pypi.org/project/prosperity4bt/) runs from "
        "`external/prosperity_rust_backtester/runs/`. Use `tools/compare_rust.py` to generate new data."
    )

    rust_runs_dir = os.path.join(REPO_ROOT, "external", "prosperity_rust_backtester", "runs")
    if not os.path.isdir(rust_runs_dir):
        st.info("No backtester runs found. Run `python tools/compare_rust.py <trader.py>` to generate some.")
        return

    runs = []
    for root, _dirs, files in os.walk(rust_runs_dir):
        if "metrics.json" not in files:
            continue
        metrics_path = os.path.join(root, "metrics.json")
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        run_folder = os.path.basename(root)
        if not data.get("run_id") or data["run_id"] == "backtest":
            data["run_id"] = run_folder
        if not data.get("engine"):
            # Heuristic: prosperity4bt runner writes folders starting with p4bt-
            data["engine"] = "prosperity4bt" if run_folder.startswith("p4bt-") else "rust"
        match = re.search(r"(.+?)-day-(-?\d+)$", run_folder)
        data["base_run_id"] = match.group(1) if match else run_folder
        runs.append(data)

    if not runs:
        st.info("No valid backtest metrics found in the runs directory.")
        return

    df_raw = pd.DataFrame(runs)
    if "generated_at" in df_raw.columns:
        df_raw["generated_at"] = pd.to_datetime(df_raw["generated_at"], errors="coerce", utc=True)
    for col in ("final_pnl_total", "own_trade_count"):
        if col in df_raw.columns:
            df_raw[col] = pd.to_numeric(df_raw[col], errors="coerce")
    df_raw["Trader"] = df_raw.get("trader_path", pd.Series([None] * len(df_raw))).apply(
        lambda x: os.path.basename(x) if isinstance(x, str) else "Unknown"
    )

    def aggregate_pnl_by_product(series):
        merged: dict = {}
        for d in series:
            if isinstance(d, dict):
                for k, v in d.items():
                    merged[k] = merged.get(k, 0) + v
        return merged

    agg_cols = ["base_run_id", "trader_path", "engine"]
    agg_map = {
        "final_pnl_total": "sum",
        "own_trade_count": "sum",
        "generated_at": "max",
        "day": lambda x: "Total (+All)" if len(x) > 1 else str(list(x)[0]),
        "dataset_id": "first",
    }
    daily_win_info = df_raw.groupby(agg_cols).apply(
        lambda x: (x["final_pnl_total"] > 0).mean() * 100
    ).to_dict()
    if "final_pnl_by_product" in df_raw.columns:
        agg_map["final_pnl_by_product"] = aggregate_pnl_by_product

    df_runs = df_raw.groupby(agg_cols).agg(agg_map).reset_index()
    df_runs["WinRateDays"] = df_runs.apply(
        lambda r: daily_win_info.get((r["base_run_id"], r["trader_path"], r["engine"]), 0), axis=1
    )
    df_runs["PnLPerTrade"] = df_runs["final_pnl_total"] / df_runs["own_trade_count"].replace(0, np.nan)
    df_runs["run_id"] = df_runs["base_run_id"]
    df_runs["Trader"] = df_runs["trader_path"].apply(lambda x: os.path.basename(x) if isinstance(x, str) else "Unknown")
    df_runs["DisplayLabel"] = df_runs.apply(
        lambda r: f"{r['Trader']} [{r['engine']}] | Day {r.get('day', '?')} | "
                  f"{r['generated_at'].strftime('%H:%M:%S') if pd.notna(r['generated_at']) else '??'}",
        axis=1,
    )
    consol_runs = df_runs.to_dict("records")

    # ---------- Best & Safest composite ranking ----------
    st.subheader("🥇 Best & Safest Trader")
    st.caption(
        "Each trader is scored across every per-day run we have (Rust **and** prosperity4bt count as "
        "independent observations). Ranking is a z-score blend — higher is better on every column."
    )

    per_day = df_raw.dropna(subset=["final_pnl_total"]).copy()
    if per_day.empty:
        st.info("Not enough per-day data to rank traders yet.")
    else:
        grouped = per_day.groupby("Trader")
        rank_rows = []
        for trader, g in grouped:
            pnls = g["final_pnl_total"].astype(float)
            mean_pnl = pnls.mean()
            std_pnl = pnls.std(ddof=0) if len(pnls) > 1 else 0.0
            min_pnl = pnls.min()
            win_rate = (pnls > 0).mean() * 100
            trades = g["own_trade_count"].astype(float).sum() if "own_trade_count" in g else 0
            total_pnl = pnls.sum()
            sharpe = mean_pnl / std_pnl if std_pnl > 0 else (float("inf") if mean_pnl > 0 else 0.0)
            rank_rows.append({
                "Trader": trader,
                "Engines": ", ".join(sorted(g["engine"].dropna().unique())),
                "Runs": int(len(g)),
                "TotalPnL": total_pnl,
                "MeanDayPnL": mean_pnl,
                "StdDayPnL": std_pnl,
                "WorstDayPnL": min_pnl,
                "WinRate": win_rate,
                "Sharpe": sharpe,
                "Trades": int(trades),
            })
        rank_df = pd.DataFrame(rank_rows)

        def _z(series: pd.Series) -> pd.Series:
            s = series.replace([np.inf, -np.inf], np.nan)
            mu, sd = s.mean(), s.std(ddof=0)
            if not sd or np.isnan(sd):
                return pd.Series(0.0, index=series.index)
            return ((s - mu) / sd).fillna(0.0)

        rank_df["z_total"] = _z(rank_df["TotalPnL"])
        rank_df["z_sharpe"] = _z(rank_df["Sharpe"])
        rank_df["z_worst"] = _z(rank_df["WorstDayPnL"])
        rank_df["z_winrate"] = _z(rank_df["WinRate"])
        rank_df["z_eff"] = _z(rank_df["TotalPnL"] / rank_df["Trades"].replace(0, np.nan))

        # Composite: reward PnL, risk-adjusted return, and downside resilience.
        rank_df["Score"] = (
            0.30 * rank_df["z_total"]
            + 0.25 * rank_df["z_sharpe"]
            + 0.20 * rank_df["z_worst"]
            + 0.15 * rank_df["z_winrate"]
            + 0.10 * rank_df["z_eff"]
        )
        rank_df = rank_df.sort_values("Score", ascending=False).reset_index(drop=True)
        rank_df["Rank"] = rank_df.index + 1

        best_row = rank_df.iloc[0]
        safest_row = rank_df.sort_values(["WorstDayPnL", "StdDayPnL"], ascending=[False, True]).iloc[0]
        most_consistent = rank_df.sort_values("StdDayPnL", ascending=True).iloc[0] if len(rank_df) > 1 else best_row

        c1, c2, c3 = st.columns(3)
        c1.success(f"🏆 **Best overall:** `{best_row['Trader']}`\n\nScore **{best_row['Score']:.2f}**  ·  Total PnL **${best_row['TotalPnL']:,.0f}**")
        c2.info(f"🛡️ **Safest (best worst-day):** `{safest_row['Trader']}`\n\nWorst day **${safest_row['WorstDayPnL']:,.0f}**  ·  Win rate **{safest_row['WinRate']:.0f}%**")
        c3.info(f"📏 **Most consistent:** `{most_consistent['Trader']}`\n\nσ(day PnL) **${most_consistent['StdDayPnL']:,.0f}**  ·  Sharpe **{most_consistent['Sharpe']:.2f}**")

        st.dataframe(
            rank_df[["Rank", "Trader", "Engines", "Runs", "TotalPnL", "MeanDayPnL", "StdDayPnL", "WorstDayPnL", "WinRate", "Sharpe", "Score"]],
            column_config={
                "Rank": st.column_config.NumberColumn("Rank", format="%d"),
                "Trader": "Trader",
                "Engines": st.column_config.TextColumn("Engines", help="Which backtesters fed this row."),
                "Runs": st.column_config.NumberColumn("Day-Runs", help="Total per-day observations (Rust + p4bt combined)."),
                "TotalPnL": st.column_config.NumberColumn("Total PnL", format="$%d"),
                "MeanDayPnL": st.column_config.NumberColumn("Mean Day PnL", format="$%d"),
                "StdDayPnL": st.column_config.NumberColumn("σ Day PnL", format="$%d", help="Lower = more consistent."),
                "WorstDayPnL": st.column_config.NumberColumn("Worst Day", format="$%d", help="Safety proxy — higher = less downside."),
                "WinRate": st.column_config.NumberColumn("Win Rate", format="%.0f%%"),
                "Sharpe": st.column_config.NumberColumn("Mean/σ", format="%.2f", help="Risk-adjusted return."),
                "Score": st.column_config.NumberColumn("Composite", format="%.2f", help="0.30·PnL + 0.25·Sharpe + 0.20·Worst + 0.15·Win% + 0.10·PnL/trade (all z-scored)."),
            },
            use_container_width=True,
            hide_index=True,
        )

        with st.expander("How the composite score is built"):
            st.markdown(
                "- **Total PnL (30%)** — raw profit across all day-runs.\n"
                "- **Sharpe-like mean/σ (25%)** — penalises volatile day-to-day results.\n"
                "- **Worst Day (20%)** — downside safety; a trader that never crashes on any engine/day scores well.\n"
                "- **Win Rate (15%)** — fraction of day-runs that finished green.\n"
                "- **PnL per Trade (10%)** — edge efficiency, keeps a churny trader from gaming raw PnL.\n\n"
                "Each column is z-scored across traders, so the score is *relative* to the other traders you've backtested."
            )

    st.divider()
    st.subheader("🏁 Per-Run Leaderboard")

    label_to_id = dict(zip(df_runs["DisplayLabel"], df_runs["run_id"]))
    all_labels = df_runs.sort_values("generated_at", ascending=False)["DisplayLabel"].tolist()
    engines_avail = sorted(df_runs["engine"].dropna().unique().tolist())
    engine_filter = st.multiselect("Engines", options=engines_avail, default=engines_avail, help="Rust and/or prosperity4bt runs.")
    selected_labels = st.multiselect(
        "Select traders/runs to compare",
        options=all_labels,
        default=all_labels,
        help="Choose multiple backtest runs to see a side-by-side comparison.",
    )

    if selected_labels:
        selected_ids = [label_to_id[l] for l in selected_labels]
        comp_df = df_runs[df_runs["run_id"].isin(selected_ids) & df_runs["engine"].isin(engine_filter)].copy()
        comp_df = comp_df.sort_values("final_pnl_total", ascending=False).reset_index(drop=True)
        comp_df["Rank"] = comp_df.index + 1

        st.dataframe(
            comp_df[["Rank", "DisplayLabel", "engine", "final_pnl_total", "WinRateDays", "PnLPerTrade", "own_trade_count"]],
            column_config={
                "Rank": st.column_config.NumberColumn("Rank", format="%d"),
                "DisplayLabel": "Trader Run Details",
                "engine": "Engine",
                "final_pnl_total": st.column_config.NumberColumn("Total PnL", format="$%d"),
                "WinRateDays": st.column_config.NumberColumn("Day Win %", format="%.0f%%", help="% of days that were profitable"),
                "PnLPerTrade": st.column_config.NumberColumn("Efficiency", format="$%.2f/tr", help="Average PnL made per trade"),
                "own_trade_count": "Total Trades",
            },
            use_container_width=True,
            hide_index=True,
        )

        if not comp_df.empty:
            winner = comp_df.iloc[0]
            st.success(
                f"🏆 **Top run:** {winner['Trader']} ({winner['engine']}) — "
                f"**${winner['final_pnl_total']:,.0f}** on day {winner.get('day', '?')}"
            )

    st.divider()
    st.subheader("🔍 Individual Run Deep Dive")
    selected_run_label = st.selectbox(
        "Select a single run for full details", 
        df_runs.sort_values("generated_at", ascending=False)["DisplayLabel"].tolist()
    )
    if selected_run_label:
        selected_run_id = label_to_id[selected_run_label]
        run_data = next(r for r in consol_runs if r["run_id"] == selected_run_id)
        
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Total PnL", f"${run_data.get('final_pnl_total', 0):,.2f}")
            st.write("**Dataset:**", run_data.get("dataset_id", "N/A"))
            st.write("**Executed At:**", run_data.get("generated_at", "N/A"))
        with c2:
            st.metric("Total Trades", f"{run_data.get('own_trade_count', 0):,}")
            st.write("**Trader:**", run_data.get("trader_path", "N/A"))
            st.write("**Day:**", run_data.get("day", "N/A"))
            
        if "final_pnl_by_product" in run_data:
            st.write("#### PnL by Product")
            pnl_items = run_data["final_pnl_by_product"].items()
            pnl_df = pd.DataFrame(pnl_items, columns=["Product", "PnL"]).sort_values("PnL", ascending=False)
            
            # Simple bar chart
            chart = alt.Chart(pnl_df).mark_bar().encode(
                x=alt.X("PnL:Q", title="PnL ($)"),
                y=alt.Y("Product:N", sort="-x", title=""),
                color=alt.condition(
                    alt.datum.PnL > 0,
                    alt.value("#2ecc71"),  # green
                    alt.value("#e74c3c")   # red
                ),
                tooltip=["Product", "PnL"]
            ).properties(height=max(100, len(pnl_df) * 30))
            st.altair_chart(chart, use_container_width=True)


def main():
    st.set_page_config(
        page_title="P4 Control Center",
        layout="wide"
    )

    if "active_round" not in st.session_state:
        default_round = DEFAULT_ROUND if DEFAULT_ROUND in ROUND_DIRS else (ROUND_DIRS[0] if ROUND_DIRS else DEFAULT_ROUND)
        st.session_state.active_round = default_round
    sync_round_import_paths(st.session_state.active_round)
    if "config_round" not in st.session_state:
        st.session_state.config_round = st.session_state.active_round

    if ROUND_DIRS:
        selected_round = st.sidebar.selectbox(
            "Round Folder",
            ROUND_DIRS,
            index=ROUND_DIRS.index(st.session_state.active_round) if st.session_state.active_round in ROUND_DIRS else 0,
            key="round_selector",
            help="Switch all data/traders/results paths to this round folder.",
        )
        if selected_round != st.session_state.active_round:
            st.session_state.active_round = selected_round
            sync_round_import_paths(selected_round)
            st.session_state.config = load_config(selected_round)
            st.session_state.config_round = selected_round
            st.session_state.pop("sim_result", None)
            st.rerun()

    if "config" not in st.session_state or st.session_state.config_round != st.session_state.active_round:
        st.session_state.config = load_config(st.session_state.active_round)
        st.session_state.config_round = st.session_state.active_round

    # --- PRE-RENDER STATE SYNC (CRITICAL FOR WIDGET UPDATES) ---
    if st.session_state.get("pending_apply"):
        for k, v in st.session_state.best_params.items():
            st.session_state.config[k] = v
            # Initialize or Update the widget key BEFORE it renders
            st.session_state[k] = v
        save_config(st.session_state.config, st.session_state.active_round)
        del st.session_state["pending_apply"]
        st.toast("✅ Optimization parameters applied to configuration!")
        # No rerun here to keep tab state if possible, or use a small toast

    def on_change_callback():
        for key in ["osmium_active", "pepper_active", "osmium_limit", "pepper_limit", "target_spread", "mr_threshold", "edge", "skew"]:
             if key in st.session_state:
                 st.session_state.config[key] = st.session_state[key]
        save_config(st.session_state.config, st.session_state.active_round)

    # --- MAIN CONTENT ---
    st.title("📈 Prosperity Operations Console")
    st.caption(f"Active round: `{st.session_state.active_round}`")


    # Final tab layout

    tab_backtest, tab_strategy, tab_rust, tab_manual, tab_archive = st.tabs([
        "📉 Visual Backtester",
        "🧪 Strategy Lab",
        "🦀 Rust Backtester",
        "♟️ Manual Optimizer",
        "📦 Archive"
    ])

    # Content for the remaining tabs
    # (tab_ai and tab_market are now moved inside tab_archive below)





    with tab_archive:
        tab_robust, tab_stress_lab = st.tabs(["🛡️ Robust Analysis", "🔬 Stress Test Lab"])
        
        with tab_robust:
            st.header("🛡️ Robust Multi-Scenario Analysis")
            st.markdown("""
            Compare **IMC Prosperity** backtest CSVs (per-session PnL). Default workflows use **IMC capsule days only**;
            scenario or real-world rows appear only if you generated those runs (e.g. ``--with-scenarios`` / ``--full-legacy`` on the backtester).
            Leaderboard metrics emphasize **IMC days** and worst-case behavior, not peak PnL on a single session.
            """)

            with st.expander("Optional: Rust backtester (external clone)", expanded=False):
                st.markdown(
                    "See `external/README_IMC_PROSPERITY.md`. Example once `rust_backtester` is on your PATH (often via WSL); "
                    "paths use POSIX form for copy-paste into a Linux shell."
                )
                _active = st.session_state.get("active_round", DEFAULT_ROUND)
                _caps = (Path(REPO_ROOT) / _active / "data_capsule").resolve()
                _tr_candidates = sorted((Path(REPO_ROOT) / _active / "traders").rglob("*.py"))
                _tr = _tr_candidates[0].resolve() if _tr_candidates else (Path(REPO_ROOT) / _active / "traders" / "trader.py").resolve()
                st.code(
                f'rust_backtester --trader "{_tr.as_posix()}" --dataset "{_caps.as_posix()}"',
                language="bash",
            )

            # Robust backtester outputs are now saved under ROUND 2/results/robust.
            # Keep a fallback to ROUND 2/tools for older runs.
            robust_results_dir = get_paths()["results_robust_dir"]
            fallback_tools_dir = get_paths()["tools_dir"]
    
            robust_csvs: list[str] = []
            if os.path.isdir(robust_results_dir):
                robust_csvs = robust_results_csv_filenames(robust_results_dir)
            if not robust_csvs and os.path.isdir(fallback_tools_dir):
                robust_results_dir = fallback_tools_dir
                robust_csvs = robust_results_csv_filenames(robust_results_dir)
    
            if robust_csvs:
                # Dynamically discover PnL columns from the first available file
                sample_df = pd.read_csv(os.path.join(robust_results_dir, robust_csvs[0]))
                pnl_cols = [c for c in sample_df.columns if c.startswith("pnl_")]
                display_cols = ["All"] + [c.replace("pnl_", "").title() for c in pnl_cols]
                
                col_f, _ = st.columns([2, 1])
                with col_f:
                    p_filter_display = st.radio("Product Filter", display_cols, horizontal=True, key="robust_product_filter")
                
                p_filter = p_filter_display if p_filter_display == "All" else f"pnl_{p_filter_display.lower().replace(' ', '_')}"
                target_col = "final_pnl" if p_filter == "All" else p_filter
    
                tab_lead, tab_inspect, tab_stress = st.tabs(["🏆 Leaderboard & Comparison", "📊 Individual Inspection", "🔬 Anti-Overfit Stress Lab"])
    
                # Pre-load all data for leaderboard and comparison
                all_leaderboard_data = []
                all_dfs = []
                for f in robust_csvs:
                    df = pd.read_csv(os.path.join(robust_results_dir, f))
                    name = robust_csv_trader_label(f)
                    
                    # Dynamic column selection with strict fallback for products
                    data_missing = False
                    if target_col in df.columns:
                        pnls = df[target_col]
                    elif p_filter == "All":
                        pnls = df["final_pnl"] if "final_pnl" in df.columns else pd.Series([0]*len(df))
                    else:
                        # Filter is Osmium or Root but column missing
                        pnls = pd.Series([0.0]*len(df))
                        data_missing = True
                    
                    all_leaderboard_data.append({
                        "Trader": name + (" (⚠️ RECALC)" if data_missing else ""),
                        "Mean PnL": pnls.mean(),
                        "Median PnL": pnls.median(),
                        "Worst PnL": pnls.min(),
                        "Win Rate": (pnls > 0).mean() * 100
                    })
                    df["target_pnl"] = pnls # For internal plotting
                    df["trader"] = name
                    all_dfs.append(df)
                
                leaderboard_df = pd.DataFrame(all_leaderboard_data)
                full_df = pd.concat(all_dfs)
    
                with tab_lead:
                    st.subheader("⚔️ Interactive Comparison Matrix")
                    st.caption("Select any robust result files, auto-compute side-by-side metrics, color by quality, and auto-rank.")
    
                    default_selection = robust_csvs
    
                    selected_compare = st.multiselect(
                        "Backtest Result Files",
                        options=sorted(robust_csvs),
                        default=default_selection,
                        format_func=robust_csv_trader_label,
                        key="comparison_files_multi",
                    )
                    cutoff_col, _ = st.columns([1, 3])
                    with cutoff_col:
                        blowup_cutoff = st.number_input(
                            "Blow-up cutoff ($)",
                            min_value=1000,
                            max_value=500000,
                            value=10000,
                            step=1000,
                            key="comparison_blowup_cutoff",
                            help="A run is counted as blow-up when PnL <= -cutoff.",
                        )
    
                    st.markdown("**AutoScore Preset**")
                    preset = st.radio(
                        "Ranking profile",
                        ["Balanced", "IMC-focused", "Safety-first"],
                        horizontal=True,
                        key="comparison_rank_profile",
                    )
    
                    if preset == "IMC-focused":
                        weights = {
                            "imc_mean": 0.48,
                            "full_mean": 0.22,
                            "win_rate": 0.10,
                            "worst_day": 0.08,
                            "scen_mean": 0.08,
                            "blowup": 0.04,
                        }
                    elif preset == "Safety-first":
                        weights = {
                            "imc_mean": 0.18,
                            "full_mean": 0.20,
                            "win_rate": 0.22,
                            "worst_day": 0.20,
                            "scen_mean": 0.08,
                            "blowup": 0.12,
                        }
                    else:
                        weights = {
                            "imc_mean": 0.34,
                            "full_mean": 0.22,
                            "win_rate": 0.16,
                            "worst_day": 0.12,
                            "scen_mean": 0.10,
                            "blowup": 0.06,
                        }
    
                    if selected_compare:
                        comparison_df = _build_comparison_table(
                            selected_compare,
                            robust_results_dir,
                            target_col,
                            p_filter,
                            float(blowup_cutoff),
                            weights,
                        )
                        if not comparison_df.empty:
                            st.dataframe(
                                _style_comparison_table(comparison_df),
                                use_container_width=True,
                                hide_index=True,
                                height=min(700, 120 + len(comparison_df) * 35),
                            )
                            st.caption(
                                f"Preset: {preset}. AutoScore blends IMC mean, full mean, win rate, worst day, scenario mean, and blow-up%. "
                                "Higher rank = better profile under chosen objective."
                            )
    
                            rank_bar = alt.Chart(comparison_df).mark_bar().encode(
                                x=alt.X("AutoScore:Q", title="AutoScore"),
                                y=alt.Y("Trader:N", sort="-x", title="Trader"),
                                color=alt.Color("IMC Mean:Q", scale=alt.Scale(scheme="yellowgreenblue"), title="IMC Mean"),
                                tooltip=["Rank", "Trader", "AutoScore", "IMC Mean", "Full Mean", "Worst Day", "Win%", "Blow-up%"],
                            ).properties(height=max(220, 30 * len(comparison_df)), title="Auto-Rank Overview")
                            st.altair_chart(rank_bar, use_container_width=True)
    
                            st.markdown("**Pairwise Edge vs Baseline**")
                            baseline = st.selectbox(
                                "Baseline trader",
                                options=comparison_df["Trader"].tolist(),
                                key="comparison_baseline_trader",
                            )
                            base_row = comparison_df[comparison_df["Trader"] == baseline].iloc[0]
                            pair_df = comparison_df.copy()
                            pair_df["Edge IMC Mean"] = pair_df["IMC Mean"] - base_row["IMC Mean"]
                            pair_df["Edge Full Mean"] = pair_df["Full Mean"] - base_row["Full Mean"]
                            pair_df["Edge Worst Day"] = pair_df["Worst Day"] - base_row["Worst Day"]
                            pair_df["Edge Win%"] = pair_df["Win%"] - base_row["Win%"]
                            pair_df["Edge Blow-up%"] = base_row["Blow-up%"] - pair_df["Blow-up%"]
    
                            edge_cols = [
                                "Rank",
                                "Trader",
                                "IMC Mean",
                                "Full Mean",
                                "Worst Day",
                                "Win%",
                                "Blow-up%",
                                "Edge IMC Mean",
                                "Edge Full Mean",
                                "Edge Worst Day",
                                "Edge Win%",
                                "Edge Blow-up%",
                            ]
                            pair_view = pair_df[edge_cols].copy().sort_values("Edge Full Mean", ascending=False)
                            pair_styler = pair_view.style
                            if _matplotlib_available():
                                pair_styler = pair_styler.background_gradient(
                                    cmap="RdYlGn",
                                    subset=["Edge IMC Mean", "Edge Full Mean", "Edge Worst Day", "Edge Win%", "Edge Blow-up%"],
                                )
                            pair_styler = pair_styler.format(
                                {
                                    "IMC Mean": "${:,.0f}",
                                    "Full Mean": "${:,.0f}",
                                    "Worst Day": "${:,.0f}",
                                    "Win%": "{:.1f}%",
                                    "Blow-up%": "{:.1f}%",
                                    "Edge IMC Mean": "{:+,.0f}",
                                    "Edge Full Mean": "{:+,.0f}",
                                    "Edge Worst Day": "{:+,.0f}",
                                    "Edge Win%": "{:+.1f}pp",
                                    "Edge Blow-up%": "{:+.1f}pp",
                                }
                            )
                            st.dataframe(pair_styler, use_container_width=True, hide_index=True)
                        else:
                            st.info("No comparable rows found in selected files.")
                    else:
                        st.info("Select one or more result files to build the comparison matrix.")
    
                    st.divider()
                    st.subheader("🌐 Cross-Round Comparison")
                    st.caption("Compare robust results across multiple round folders in one table.")
    
                    selectable_rounds = ROUND_DIRS
                    cross_rounds = st.multiselect(
                        "Rounds to include",
                        options=selectable_rounds,
                        default=[st.session_state.active_round] if st.session_state.active_round in selectable_rounds else selectable_rounds[:1],
                        key="cross_round_selector",
                    )
    
                    if cross_rounds:
                        cross_df = _build_cross_round_comparison(
                            selected_rounds=cross_rounds,
                            target_col=target_col,
                            p_filter=p_filter,
                            blowup_cutoff=float(blowup_cutoff),
                            weights=weights,
                        )
                        if cross_df.empty:
                            st.info("No robust CSV results found in selected rounds.")
                        else:
                            st.dataframe(
                                _style_comparison_table(cross_df),
                                use_container_width=True,
                                hide_index=True,
                                height=min(700, 120 + len(cross_df) * 35),
                            )
    
                            cross_chart = alt.Chart(cross_df).mark_circle(size=120, opacity=0.85).encode(
                                x=alt.X("IMC Mean:Q", title="IMC Mean"),
                                y=alt.Y("Full Mean:Q", title="Full Mean"),
                                color=alt.Color("Round:N", title="Round"),
                                shape=alt.Shape("Round:N", title="Round"),
                                tooltip=["Rank", "Round", "Trader", "Algo Key", "AutoScore", "IMC Mean", "Full Mean", "Worst Day", "Win%", "Blow-up%"],
                            ).properties(height=380, title="Cross-Round Frontier (IMC vs Full Mean)").interactive()
                            st.altair_chart(cross_chart, use_container_width=True)
                    else:
                        st.info("Select at least one round to compare.")
    
                    st.divider()
                    st.subheader("Global Leaderboard")
                    st.dataframe(
                        leaderboard_df.sort_values("Mean PnL", ascending=False),
                        column_config={
                            "Trader": st.column_config.TextColumn("Trader Profile"),
                            "Mean PnL": st.column_config.NumberColumn("Mean PnL", format="$%d"),
                            "Median PnL": st.column_config.NumberColumn("Median PnL", format="$%d"),
                            "Worst PnL": st.column_config.NumberColumn("Worst PnL", format="$%d"),
                            "Win Rate": st.column_config.NumberColumn("Win Rate", format="%.0f%%"),
                        },
                        use_container_width=True,
                        hide_index=True
                    )
    
                    st.divider()
                    st.subheader("Comparative Analysis")
                    
                    col_c1, col_c2 = st.columns(2)
                    with col_c1:
                        dist_chart = alt.Chart(full_df).mark_boxplot(extent='min-max').encode(
                            x=alt.X("trader:N", title="Trader"),
                            y=alt.Y("target_pnl:Q", title=f"PnL ({p_filter}) ($)"),
                            color=alt.Color("trader:N", legend=None)
                        ).properties(height=350)
                        st.altair_chart(dist_chart, use_container_width=True)
    
                    with col_c2:
                        st.markdown(f"**Mean PnL by Category ({p_filter})**")
                        cat_comp = full_df.groupby(["trader", "category"])["target_pnl"].mean().reset_index()
                        cat_chart = alt.Chart(cat_comp).mark_bar().encode(
                            x=alt.X("category:N", title="Category"),
                            y=alt.Y("target_pnl:Q", title=f"Mean PnL ({p_filter}) ($)"),
                            color=alt.Color("trader:N", title="Trader"),
                            xOffset="trader:N"
                        ).properties(height=350)
                        st.altair_chart(cat_chart, use_container_width=True)
    
                    st.divider()
                    st.markdown("**Risk Frontier: PnL vs Max Drawdown (All Scenarios)**")
                    risk_scatter = alt.Chart(full_df).mark_circle(size=60, opacity=0.6).encode(
                        x=alt.X("target_pnl:Q", title=f"PnL ({p_filter}) ($)"),
                        y=alt.Y("max_drawdown:Q", title="Max Drawdown ($)"),
                        color=alt.Color("trader:N", title="Trader"),
                        tooltip=["trader", "name", "target_pnl", "max_drawdown", "category"]
                    ).properties(height=450, title=f"Risk vs Reward (PnL: {p_filter}) - All Scenarios").interactive()
                    st.altair_chart(risk_scatter, use_container_width=True)
    
                    st.divider()
                    st.markdown(f"**PnL by Scenario Comparison (Heatmap - {p_filter})**")
                    heatmap = alt.Chart(full_df).mark_rect().encode(
                        x=alt.X("trader:N", title="Trader", axis=alt.Axis(labelAngle=-45)),
                        y=alt.Y("name:N", title="Scenario", sort="descending"),
                        color=alt.Color("target_pnl:Q", scale=alt.Scale(scheme="redyellowgreen", domainMid=0), title="PnL ($)"),
                        tooltip=["trader", "name", "target_pnl", "category"]
                    ).properties(height=max(400, len(full_df["name"].unique()) * 15))
                    st.altair_chart(heatmap, use_container_width=True)
    
                with tab_inspect:
                    selected_result = st.selectbox(
                        "Select Results File for Deep Dive",
                        robust_csvs,
                        format_func=robust_csv_trader_label,
                    )
                    df_robust = pd.read_csv(os.path.join(robust_results_dir, selected_result))
                    
                    # Dynamic column selection with strict fallback for products
                    data_missing = False
                    if target_col in df_robust.columns:
                        pnls = df_robust[target_col]
                    elif p_filter == "All":
                        pnls = df_robust["final_pnl"] if "final_pnl" in df_robust.columns else pd.Series([0]*len(df_robust))
                    else:
                        pnls = pd.Series([0.0]*len(df_robust))
                        data_missing = True
                    
                    df_robust["target_pnl"] = pnls
    
                    if data_missing:
                        st.warning(f"⚠️ **Granular Data Missing:** This result file does not contain {p_filter}-specific PnL. Please re-run the robust backtester to enable filtering.")
    
                    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                    col_m1.metric(f"Mean PnL ({p_filter})", f"${pnls.mean():,.0f}")
                    col_m2.metric("Median PnL", f"${pnls.median():,.0f}")
                    col_m3.metric("Worst PnL", f"${pnls.min():,.0f}")
                    col_m4.metric("Win Rate", f"{(pnls > 0).mean()*100:.0f}%")
    
                    st.divider()
    
                    st.subheader(f"PnL by Category ({p_filter})")
                    if "category" in df_robust.columns:
                        cat_stats = df_robust.groupby("category")["target_pnl"].agg(["mean", "min", "max", "count"])
                        cat_stats.columns = ["Mean PnL", "Worst PnL", "Best PnL", "Count"]
                        st.dataframe(cat_stats.style.format("${:,.0f}", subset=["Mean PnL", "Worst PnL", "Best PnL"]))
    
                    st.subheader(f"PnL by Scenario ({p_filter})")
                    bar_data = df_robust[["name", "target_pnl", "category"]].copy()
                    bar_data = bar_data.sort_values("target_pnl")
    
                    bar_chart = alt.Chart(bar_data).mark_bar().encode(
                        x=alt.X("target_pnl:Q", title="PnL ($)"),
                        y=alt.Y("name:N", sort="-x", title=""),
                        color=alt.Color("category:N", scale=alt.Scale(scheme="set2")),
                        tooltip=["name", "target_pnl", "category"],
                    ).properties(height=max(300, len(bar_data) * 22), width="container",
                                title=f"PnL Across All Scenarios ({p_filter})")
                    st.altair_chart(bar_chart, use_container_width=True)
    
                    st.subheader(f"PnL Distribution ({p_filter})")
                    hist_chart = alt.Chart(df_robust).mark_bar(opacity=0.8).encode(
                        x=alt.X("target_pnl:Q", bin=alt.Bin(maxbins=25), title="PnL ($)"),
                        y=alt.Y("count()", title="Scenarios"),
                        color=alt.Color("category:N", scale=alt.Scale(scheme="set2")),
                    ).properties(height=300, title=f"PnL Distribution Histogram ({p_filter})")
                    st.altair_chart(hist_chart, use_container_width=True)
    
                    if "max_drawdown" in df_robust.columns:
                        st.subheader(f"Risk: PnL vs Drawdown ({p_filter})")
                        scatter = alt.Chart(df_robust).mark_circle(size=80).encode(
                            x=alt.X("target_pnl:Q", title="PnL ($)"),
                            y=alt.Y("max_drawdown:Q", title="Max Drawdown ($)"),
                            color=alt.Color("category:N", scale=alt.Scale(scheme="set2")),
                            tooltip=["name", "target_pnl", "max_drawdown", "category"],
                        ).properties(height=400, title="PnL vs Drawdown (bottom-right = best)")
                        st.altair_chart(scatter, use_container_width=True)
    
                with tab_stress:
                    st.subheader("🔬 Extreme Multi-Variant Stress Test")
                    st.markdown("""
                    Apply **destructive mutations** to price series to see if your bot relies on 
                    genuine signals or just "got lucky" with a specific trend.
                    """)
    
                    # 1. SETUP
                    trader_search = []
                    trader_base = get_paths()["traders_dir"]
                    for root, _, files in os.walk(trader_base):
                        for f in files:
                            if f.endswith(".py") and not f.startswith("__"):
                                trader_search.append(os.path.relpath(os.path.join(root, f), os.getcwd()))
                    
                    col_s1, col_s2, col_s3 = st.columns(3)
                    with col_s1:
                        sel_trader = st.selectbox("Target Trader", trader_search, key="stress_trader", index=next((i for i, x in enumerate(trader_search) if "v2d" in x), 0))
                    with col_s3:
                        sel_source = st.selectbox("Base Dataset", ["All", -1, -2, 0], index=0)

                    # Discover available assets for stress testing
                    df_sample, _ = load_and_process_data(sel_source)
                    stress_products = sorted(df_sample["product"].unique()) if df_sample is not None else []
                    
                    with col_s2:
                        sel_prod = st.selectbox("Market Asset", stress_products + ["TOTAL (All Assets)"], index=len(stress_products))
    
                    if st.button("☣️ Run Destructive Mutation Suite", type="primary", use_container_width=True):
                        df_p, _ = load_and_process_data(sel_source)
                        if df_p is None:
                            st.error("Base data not found!")
                        else:
                            active_prods = stress_products if "TOTAL" in sel_prod else [sel_prod]
                            
                            base_prices = {}
                            for p in active_prods:
                                p_vals = df_p[df_p["product"] == p]["mid_price"].values
                                if len(p_vals) > 5000:
                                    p_vals = p_vals[::len(p_vals)//3000] # Dynamic downsample
                                base_prices[p] = p_vals
                            
                            # Verify lengths match
                            min_len = min(len(v) for v in base_prices.values())
                            for p in base_prices: base_prices[p] = base_prices[p][:min_len]
    
                            np.random.seed(42)
                            
                            # 2. VARIANTS (Dict of Dicts: variant_name -> product -> prices)
                            variants = {}
                            v_names = ["Original", "Inverted Returns", "Flat + Noise", "Trend Amplified (1.8x)", "Trend Dampened (0.4x)", "Shuffled Segments"]
                            for v in v_names: variants[v] = {}
    
                            for p in active_prods:
                                价格 = base_prices[p]
                                variants["Original"][p] = 价格.copy()
                                
                                rets = np.diff(价格)
                                variants["Inverted Returns"][p] = 价格[0] + np.cumsum(-rets)
                                variants["Flat + Noise"][p] = 价格[0] + np.random.normal(0, 5, len(价格))
                                variants["Trend Amplified (1.8x)"][p] = 价格[0] + np.cumsum(rets * 1.8)
                                variants["Trend Dampened (0.4x)"][p] = 价格[0] + np.cumsum(rets * 0.4)
                                
                                # Shuffled (litera chunks of 50)
                                chunks = [价格[i:i + 50] for i in range(0, len(价格), 50)]
                                shuf_idx = np.random.permutation(len(chunks))
                                variants["Shuffled Segments"][p] = np.concatenate([chunks[i] for i in shuf_idx])
    
                            # 3. RUN BOT
                            stress_results = []
                            pbar = st.progress(0)
                            for i, vname in enumerate(v_names):
                                res = run_stress_backtest(os.path.abspath(sel_trader), variants[vname], active_prods)
                                res["Variant"] = vname
                                stress_results.append(res)
                                pbar.progress((i+1)/len(v_names))
                            
                            df_stress = pd.DataFrame(stress_results)
                            
                            # 4. ROBUSTNESS SCORE
                            # Logic: Mean PnL / (Std PnL + 1) * Penalty for Sign Flips
                            mean_p = df_stress["final_pnl"].mean()
                            std_p = df_stress["final_pnl"].std()
                            flips = sum(1 for p in df_stress["final_pnl"] if p < 0)
                            score = (mean_p / (std_p + 1)) * (1.0 - (flips / len(variants)))
                            
                            # Normalize score 0-100
                            norm_score = max(0, min(100, score * 10))
                            
                            st.divider()
                            c_score, c_stats = st.columns([1, 2])
                            with c_score:
                                st.metric("Overall Robustness Score", f"{norm_score:.1f}/100", 
                                          help="High score = bot makes money regardless of how the price chart is warped.")
                            with c_stats:
                                st.markdown(f"**Detected Failures**: {flips} / {len(variants)} regimes showed losses.")
    
                            # 5. UI TABLE & FLAGS
                            def flag_row(row, base_pnl, base_dd):
                                flags = []
                                if row["final_pnl"] < 0: flags.append("🚩 LOSS")
                                if row["final_pnl"] * base_pnl < 0: flags.append("🔄 SIGN FLIP")
                                if row["max_dd"] > base_dd * 2: flags.append("⚠️ DD SPIKE")
                                if abs(row["final_pos"]) > 40: flags.append("📉 DIRECTIONAL")
                                return ", ".join(flags) if flags else "✅ ROBUST"
    
                            base_pnl = df_stress[df_stress["Variant"] == "Original"]["final_pnl"].values[0]
                            base_dd = df_stress[df_stress["Variant"] == "Original"]["max_dd"].values[0]
                            df_stress["Analysis"] = df_stress.apply(lambda r: flag_row(r, base_pnl, base_dd), axis=1)
    
                            st.dataframe(df_stress[["Variant", "final_pnl", "max_dd", "final_pos", "Analysis"]].style.format({
                                "final_pnl": "${:,.0f}",
                                "max_dd": "${:,.0f}"
                            }), use_container_width=True)
    
                            # 6. VISUALIZATION
                            st.subheader("Variant PnL Trajectories")
                            line_data = []
                            for res in stress_results:
                                for t, val in enumerate(res["pnl_curve"]):
                                    if t % 20 == 0: # Downsample
                                        line_data.append({"Tick": t, "PnL": val, "Variant": res["Variant"]})
                            
                            df_chart = pd.DataFrame(line_data)
                            chart = alt.Chart(df_chart).mark_line().encode(
                                x="Tick:Q",
                                y="PnL:Q",
                                color="Variant:N",
                                tooltip=["Tick", "PnL", "Variant"]
                            ).properties(height=400).interactive()
                            st.altair_chart(chart, use_container_width=True)
    
                            col_sc1, col_sc2 = st.columns(2)
                            with col_sc1:
                                st.markdown("**Mean PnL vs Drawdown**")
                                scatter = alt.Chart(df_stress).mark_circle(size=100).encode(
                                    x=alt.X("final_pnl:Q", title="Final PnL ($)"),
                                    y=alt.Y("max_dd:Q", title="Max Drawdown ($)"),
                                    color="Variant:N",
                                    tooltip=["Variant", "final_pnl", "max_dd"]
                                ).properties(height=400).interactive()
                                st.altair_chart(scatter, use_container_width=True)
                            with col_sc2:
                                st.info("""
                                **Variant Interpretration:**
                                - **Inverted**: Tests if your bot actually finds alpha or just follows a trend.
                                - **Shuffled**: Tests if trade timing/order matters.
                                - **Flat+Noise**: Tests if the bot over-trades (chops) in dead markets.
                                - **Amplified**: Tests if the bot can handle high volatility.
                                """)
    
            else:
                _ar = st.session_state.get("active_round", DEFAULT_ROUND)
                st.warning(f"No robust results found. Run the {_ar} robust backtester (IMC days by default):")
                st.code(f"python \"{_ar}/tools/robust_backtester.py\" \"{_ar}/traders/your_trader.py\" --quick")
                st.caption("Add ``--with-scenarios`` or ``--full-legacy`` only if you want synthetic / cached real-world CSVs in the same run.")


    with tab_backtest:

        paths_bt = discover_trader_py_files()
        if paths_bt:
            pref_idx = next((i for i, p in enumerate(paths_bt) if "trader_ken_v7.py" in p), None)
            if pref_idx is None:
                pref_idx = next(
                    (i for i, p in enumerate(paths_bt) if os.path.basename(p) == "trader.py"),
                    None,
                )
            if pref_idx is None:
                pref_idx = 0
            pref_idx = min(int(pref_idx), len(paths_bt) - 1)
            st.selectbox(
                "Backtest trader (`Trader` class)",
                paths_bt,
                index=pref_idx,
                format_func=lambda p: os.path.relpath(p, REPO_ROOT),
                key="dash_bt_trader_path",
            )
        else:
            st.warning("No `*.py` traders found for this round.")

        def on_day_change():
            st.session_state.config["selected_day"] = st.session_state.day_radio
            save_config(st.session_state.config, st.session_state.active_round)
            tp = st.session_state.get("dash_bt_trader_path")
            run_backtest_simulation(st.session_state.day_radio, tp)

        available_days = discover_available_days(get_paths()["data_dir"])
        day_options = ["All"] + available_days
        current_day = st.session_state.config.get("selected_day", -1)
        if current_day not in day_options:
            current_day = day_options[0]

        cday, crun = st.columns([4, 1])
        with cday:
            selected_day = st.radio(
                "Select Historical Data Day:",
                day_options,
                key="day_radio",
                index=day_options.index(current_day),
                horizontal=True,
                on_change=on_day_change,
            )
        with crun:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("▶ Run", help="Re-run simulation with the selected trader and day"):
                tp = st.session_state.get("dash_bt_trader_path")
                run_backtest_simulation(selected_day, tp)

        sim = st.session_state.get("sim_result", {})
        if (
            sim.get("day") == selected_day
            and sim.get("trader_path", "") == st.session_state.get("dash_bt_trader_path", "")
        ):
            st.metric("Simulated PnL", f"${sim.get('pnl', 0):,.2f}")

        st.markdown("---")

        df_prices, df_trades = load_and_process_data(selected_day)

        if df_prices is not None:
            st.subheader(f"📊 Market Reconstruction (Day {selected_day})")

            products = sorted(df_prices["product"].unique())
            
            # Group VEV strikes together to avoid UI clutter
            vev_strikes = [p for p in products if p.startswith("VEV_")]
            main_products = [p for p in products if not p.startswith("VEV_")]
            
            def _color_for(p: str) -> str:
                if "OSMIUM" in p or "HYDRO" in p:
                    return "#2ecc71"  # green: market-making asset
                if "VELVETFRUIT" in p or "VFE" in p:
                    return "#9b59b6"  # purple: option underlying
                if "PEPPER" in p:
                    return "#e74c3c"  # red: legacy round 2
                return "#f39c12"  # amber: misc

            for p in main_products:
                st.markdown(f"#### {p}")
                render_chart(df_prices, df_trades, p, _color_for(p), show_mean=True)

            if vev_strikes:
                st.markdown(f"#### VEV Options Chain ({len(vev_strikes)} strikes)")
                render_vev_chain_chart(df_prices, vev_strikes)
                with st.expander("🔦 Per-strike detail", expanded=False):
                    for p in vev_strikes:
                        st.markdown(f"##### {p}")
                        render_chart(df_prices, df_trades, p, "#3498db", show_mean=False)

            st.markdown("#### 🌎 Total Market Reconstruction")
            render_total_chart(df_prices, df_trades)

        else:
            data_dir = get_paths()["data_dir"]
            round_num = _active_round_number() or "?"
            st.warning(f"Could not locate data for Day {selected_day} at: {data_dir}")
            st.code(f"Looking for pattern: prices_round_{round_num}_day_{selected_day}.csv")

    with tab_strategy:
        render_strategy_lab_tab()

    with tab_rust:
        render_rust_backtester_tab()

    with tab_manual:
        render_manual_optimizer_tab()

if __name__ == "__main__":
    main()
