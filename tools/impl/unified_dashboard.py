import streamlit as st
import math
import json
import os
import sys
import glob
from pathlib import Path

# Resolve absolute paths for relative imports (datamodel in ../../ROUND 2/config, trader in ../../ROUND 2/traders)
script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
config_path = os.path.join(repo_root, "ROUND 2", "config")
traders_path = os.path.join(repo_root, "ROUND 2", "traders")

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
DEFAULT_ROUND = "ROUND 2"

# Round 2 datamodel uses 80; dashboard fills must match or simulation is meaningless.
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

    listings = {
        "ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "SEASHELLS"),
        "INTARIAN_PEPPER_ROOT": Listing("INTARIAN_PEPPER_ROOT", "INTARIAN_PEPPER_ROOT", "SEASHELLS"),
    }

    positions = {"ASH_COATED_OSMIUM": 0, "INTARIAN_PEPPER_ROOT": 0}
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

    listings = {
        "ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "SEASHELLS"),
        "INTARIAN_PEPPER_ROOT": Listing("INTARIAN_PEPPER_ROOT", "INTARIAN_PEPPER_ROOT", "SEASHELLS"),
    }

    positions = {"ASH_COATED_OSMIUM": 0, "INTARIAN_PEPPER_ROOT": 0}
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
    
    for d in days_to_load:
        prices_file = _resolve_round_day_file(data_dir, "prices", d)
        trades_file = _resolve_round_day_file(data_dir, "trades", d)
        
        if prices_file and os.path.exists(prices_file):
            df_p = pd.read_csv(prices_file, sep=";")
            df_p = df_p.dropna(subset=["bid_price_1", "ask_price_1", "timestamp"])
            # Offset timestamp for continuity if showing All
            if day == "All":
                # days are -2, -1, 0 -> normalized to index 0, 1, 2 for continuous timeline
                offset = (d + 2) * 1000000 
                df_p["timestamp"] = df_p["timestamp"] + offset
            df_p["day"] = d
            all_prices.append(df_p)
            
        if trades_file and os.path.exists(trades_file):
            df_t = pd.read_csv(trades_file, sep=";")
            if "symbol" in df_t.columns:
                df_t = df_t.rename(columns={"symbol": "product"})
            if day == "All":
                offset = (d + 2) * 1000000
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

        # Allow both robust labels (imc, real) and standard labels (round_1, round_2, real_world)
        imc = df.loc[df["category"].isin(["imc", "round_1", "round_2"]), "target_pnl"] if "category" in df.columns else pd.Series([], dtype=float)
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

            # Allow both robust labels (imc, real) and standard labels (round_1, round_2, real_world)
            imc = df.loc[df["category"].isin(["imc", "round_1", "round_2"]), "target_pnl"] if "category" in df.columns else pd.Series([], dtype=float)
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
    os_mean = df[df["product"] == "ASH_COATED_OSMIUM"]["mid_price"].mean()
    pep_std = df[df["product"] == "INTARIAN_PEPPER_ROOT"]["mid_price"].std()

    st.session_state.analysis = {"os_mean": os_mean, "pep_std": pep_std}
    st.toast("Analysis Successful!")


def render_manual_optimizer_tab():
    """Delegates to unified implementation in manual_optimiser.dashboard_tab."""
    from manual_optimiser.dashboard_tab import render_manual_optimizer_tab as _impl
    _impl()


def render_rust_backtester_tab():
    st.header("🦀 Rust Backtester Results")
    st.markdown("""
    Explore high-performance backtest results from the Rust engine. 
    Results are automatically loaded from `external/prosperity_rust_backtester/runs/`.
    """)
    
    rust_runs_dir = os.path.join(REPO_ROOT, "external", "prosperity_rust_backtester", "runs")
    if not os.path.isdir(rust_runs_dir):
        st.info("No Rust backtester runs found. Use the CLI or `run_backtest.ps1` to generate results first.")
        return
        
    runs = []
    # Walk to find all metrics.json even in subdirectories
    for root, dirs, files in os.walk(rust_runs_dir):
        if "metrics.json" in files:
            metrics_path = os.path.join(root, "metrics.json")
            try:
                with open(metrics_path, "r") as f:
                    data = json.load(f)
                    # Extract the base directory name to help with grouping
                    run_folder = os.path.basename(root)
                    if not data.get("run_id") or data["run_id"] == "backtest":
                         data["run_id"] = run_folder
                    
                    # Extract the base prefix (removing -day-X) to group multi-day runs
                    # backtest-1776586006173-data-capsule-day-1 -> backtest-1776586006173-data-capsule
                    match = re.search(r"(backtest-\d+-[^/]+?)-day-", run_folder)
                    data["base_run_id"] = match.group(1) if match else run_folder
                    runs.append(data)
            except:
                pass
                
    if not runs:
        st.info("No valid backtest metrics found in the runs directory.")
        return
        
    df_raw = pd.DataFrame(runs)
    if "generated_at" in df_raw.columns:
        df_raw["generated_at"] = pd.to_datetime(df_raw["generated_at"])
    
    # Aggregation Logic: Group by base_run_id and trader_path to get a "Total" view
    def aggregate_pnl_by_product(series):
        merged = {}
        for d in series:
            if isinstance(d, dict):
                for k, v in d.items():
                    merged[k] = merged.get(k, 0) + v
        return merged

    agg_cols = ["base_run_id", "trader_path"]
    agg_map = {
        "final_pnl_total": "sum",
        "own_trade_count": "sum",
        "generated_at": "max",
        "day": lambda x: "Total (+All)" if len(x) > 1 else str(list(x)[0]),
        "dataset_id": "first"
    }
    
    # Store daily win info for later
    daily_win_info = df_raw.groupby(agg_cols).apply(
        lambda x: (x["final_pnl_total"] > 0).mean() * 100
    ).to_dict()

    if "final_pnl_by_product" in df_raw.columns:
        agg_map["final_pnl_by_product"] = aggregate_pnl_by_product
        
    df_runs = df_raw.groupby(agg_cols).agg(agg_map).reset_index()
    
    # Map back the Win Rate %
    df_runs["WinRateDays"] = df_runs.apply(lambda r: daily_win_info.get((r["base_run_id"], r["trader_path"]), 0), axis=1)
    
    # Calculate PnL per Trade (Efficiency)
    df_runs["PnLPerTrade"] = df_runs["final_pnl_total"] / df_runs["own_trade_count"].replace(0, np.nan)
    
    # Use the base_run_id as the primary identifier now
    df_runs["run_id"] = df_runs["base_run_id"]
    
    # Create the consolidated list for the deep dive lookup
    consol_runs = df_runs.to_dict("records")
    
    # Enrich df with trader name for easier comparison
    if "trader_path" in df_runs.columns:
        df_runs["Trader"] = df_runs["trader_path"].apply(lambda x: os.path.basename(x))
    else:
        df_runs["Trader"] = "Unknown"

    # Create a nice label combining trader name and timestamp
    df_runs["DisplayLabel"] = df_runs.apply(
        lambda r: f"{r['Trader']} | Day {r.get('day', '?')} | {r['generated_at'].strftime('%H:%M:%S') if pd.notna(r['generated_at']) else '??'}", 
        axis=1
    )

    st.subheader("🏁 Trader Comparison Leaderboard")
    
    # Create mapping for selectors
    label_to_id = dict(zip(df_runs["DisplayLabel"], df_runs["run_id"]))
    
    all_labels = df_runs.sort_values("generated_at", ascending=False)["DisplayLabel"].tolist()
    selected_labels = st.multiselect(
        "Select traders/runs to compare",
        options=all_labels,
        default=all_labels,
        help="Choose multiple backtest runs to see a side-by-side comparison."
    )

    if selected_labels:
        selected_ids = [label_to_id[l] for l in selected_labels]
        comp_df = df_runs[df_runs["run_id"].isin(selected_ids)].copy()
        
        # Sort and Rank
        comp_df = comp_df.sort_values("final_pnl_total", ascending=False).reset_index(drop=True)
        comp_df["Rank"] = comp_df.index + 1
        
        # Comparison Metrics Table - simplified to essentials
        st.dataframe(
            comp_df[["Rank", "DisplayLabel", "final_pnl_total", "WinRateDays", "PnLPerTrade", "own_trade_count"]],
            column_config={
                "Rank": st.column_config.NumberColumn("Rank", format="%d"),
                "DisplayLabel": "Trader Run Details",
                "final_pnl_total": st.column_config.NumberColumn("Total PnL", format="$%d"),
                "WinRateDays": st.column_config.NumberColumn("Day Win %", format="%.0f%%", help="% of days that were profitable"),
                "PnLPerTrade": st.column_config.NumberColumn("Efficiency", format="$%.2f/tr", help="Average PnL made per trade"),
                "own_trade_count": "Total Trades",
            },
            use_container_width=True,
            hide_index=True
        )

        # Highlight Winner
        winner = comp_df.iloc[0]
        st.success(f"🏆 **Winner:** {winner['Trader']} with **${winner['final_pnl_total']:,.0f}** PnL (Day {winner.get('day', '?')})")

        # Comparative Chart
        st.write("#### PnL Performance Comparison")
        bar_chart = alt.Chart(comp_df).mark_bar().encode(
            x=alt.X("final_pnl_total:Q", title="Final PnL ($)"),
            y=alt.Y("DisplayLabel:N", sort="-x", title="Trader Run"),
            color=alt.Color("Trader:N", title="Trader Script"),
            tooltip=["Trader", "run_id", "final_pnl_total", "own_trade_count"]
        ).properties(height=max(200, len(comp_df) * 40))
        st.altair_chart(bar_chart, use_container_width=True)

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

    tab_backtest, tab_rust, tab_robust, tab_manual = st.tabs([
        "📉 Visual Backtester",
        "🦀 Rust Backtester",
        "🛡️ Robust Analysis",
        "♟️ Manual Optimizer"
    ])

    # Content for the remaining tabs
    # (tab_ai and tab_market are now moved inside tab_archive below)





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
            _caps = (Path(REPO_ROOT) / "ROUND 2" / "data_capsule").resolve()
            _tr = (Path(REPO_ROOT) / "ROUND 2" / "traders" / "ken" / "trader_ken_v6.py").resolve()
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
            col_f, col_spacer = st.columns([1, 2])
            with col_f:
                p_filter = st.radio("Product Filter", ["All", "Osmium", "Root"], horizontal=True, key="robust_product_filter")
            
            p_col_map = {"All": "final_pnl", "Osmium": "pnl_osmium", "Root": "pnl_pepper"}
            target_col = p_col_map[p_filter]

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
                with col_s2:
                    sel_prod = st.selectbox("Market Asset", ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT", "TOTAL (Both Assets)"], index=2)
                with col_s3:
                    sel_source = st.selectbox("Base Dataset", ["All (Round 1 Data)", -1, -2, 0], index=0)

                if st.button("☣️ Run Destructive Mutation Suite", type="primary", use_container_width=True):
                    source_key = "All" if sel_source == "All (Round 1 Data)" else sel_source
                    df_p, _ = load_and_process_data(source_key)
                    if df_p is None:
                        st.error("Base data not found!")
                    else:
                        active_prods = ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"] if "TOTAL" in sel_prod else [sel_prod]
                        
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
            st.warning("No robust results found. Run the Round 2 robust backtester (IMC days by default):")
            st.code("python \"ROUND 2/tools/robust_backtester.py\" \"ROUND 2/traders/your_trader.py\" --quick")
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

            st.markdown("#### 💎 ASH COATED OSMIUM (Mean Reversion)")
            df_os = render_chart(df_prices, df_trades, "ASH_COATED_OSMIUM", "#2ecc71", show_mean=True)
            
            if df_os is not None:
                os_mean = df_os["mid_price"].mean()
                if abs(os_mean - 10000) < 100:
                    st.info(f"**Fair Value Found:** Osmium average is stable around {os_mean:.2f}. Anchoring to 10,000 is optimal.")

            st.markdown("#### 🌶️ INTARIAN PEPPER ROOT (Trend MM)")
            render_chart(df_prices, df_trades, "INTARIAN_PEPPER_ROOT", "#e74c3c", show_mean=False)

            st.markdown("#### 🌎 Total Market Reconstruction")
            render_total_chart(df_prices, df_trades)

        else:
            data_dir = get_paths()["data_dir"]
            round_num = _active_round_number() or "?"
            st.warning(f"Could not locate data for Day {selected_day} at: {data_dir}")
            st.code(f"Looking for pattern: prices_round_{round_num}_day_{selected_day}.csv")

    with tab_rust:
        render_rust_backtester_tab()

    with tab_manual:
        render_manual_optimizer_tab()

if __name__ == "__main__":
    main()
