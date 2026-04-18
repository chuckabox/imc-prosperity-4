import streamlit as st
import math
import json
import os
import sys
import glob
import pandas as pd
import altair as alt
import re
import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import make_interp_spline
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
ROUND_DIRS = sorted(
    d for d in os.listdir(REPO_ROOT)
    if d.startswith("ROUND ") and os.path.isdir(os.path.join(REPO_ROOT, d))
)
DEFAULT_ROUND = ROUND_DIRS[0] if ROUND_DIRS else "ROUND 1"

# Bootstrap datamodel path
sys.path.insert(0, os.path.join(REPO_ROOT, DEFAULT_ROUND, "config"))

from datamodel import Listing, OrderDepth, TradingState, Observation, Order

def get_paths(round_name: str | None = None) -> dict:
    rn = round_name or st.session_state.get("active_round", DEFAULT_ROUND)
    base_dir = os.path.join(REPO_ROOT, rn)
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
        "emerald_active": True,
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

try:
    import optuna
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False

if OPTUNA_AVAILABLE:
    import logging
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
    import importlib.util
    spec = importlib.util.spec_from_file_location("trader_optim", trader_path)
    trader_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trader_mod)
    trader = trader_mod.Trader()

    if config_override:
        for k, v in config_override.items():
            if k == "osmium_limit" and hasattr(trader, "limits"):
                trader.limits["ASH_COATED_OSMIUM"] = v
            elif k == "pepper_limit" and hasattr(trader, "limits"):
                trader.limits["INTARIAN_PEPPER_ROOT"] = v
            else:
                setattr(trader, k, v)

    listings = {
        "ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "XIRECS"),
        "INTARIAN_PEPPER_ROOT": Listing("INTARIAN_PEPPER_ROOT", "INTARIAN_PEPPER_ROOT", "XIRECS")
    }
    positions = {"ASH_COATED_OSMIUM": 0, "INTARIAN_PEPPER_ROOT": 0}
    cash = 0.0
    pnl_history = []
    current_trader_data = ""
    price_map = {}
    for ts, group in df_prices.groupby("timestamp"):
        ts_depths = {}
        for _, row in group.iterrows():
            product = row["product"]
            depth = OrderDepth()
            depth.buy_orders = {int(row["bid_price_1"]): 10}
            depth.sell_orders = {int(row["ask_price_1"]): -10}
            ts_depths[product] = (depth, row["ask_price_1"], row["bid_price_1"])
        price_map[ts] = ts_depths

    timestamps = sorted(price_map.keys())
    for ts in timestamps:
        ts_data = price_map[ts]
        order_depths = {p: d[0] for p, d in ts_data.items()}
        state = TradingState(traderData=current_trader_data, timestamp=ts, listings=listings,
                             order_depths=order_depths, own_trades={}, market_trades={},
                             position=positions, observations=Observation({}, {}))
        orders, _, new_trader_data = trader.run(state)
        current_trader_data = new_trader_data

        for product, order_list in orders.items():
            if product not in ts_data: continue
            _, curr_ask, curr_bid = ts_data[product]
            limit = trader.limits.get(product, 20)
            for order in order_list:
                qty, price = order.quantity, order.price
                if qty > 0 and price >= curr_ask:
                    rem_buy = limit - positions[product]
                    fill = min(qty, rem_buy) if rem_buy > 0 else 0
                    positions[product] += fill; cash -= fill * curr_ask
                elif qty < 0 and price <= curr_bid:
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
    sync_round_import_paths()
    import importlib.util
    spec = importlib.util.spec_from_file_location("trader_stress", trader_path)
    trader_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trader_mod)
    trader = trader_mod.Trader()

    listings = {p: Listing(p, p, "XIRECS") for p in products}
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
        state = TradingState(traderData=current_trader_data, timestamp=ts * 100, listings=listings,
                             order_depths=order_depths, own_trades={}, market_trades={},
                             position=positions, observations=Observation({}, {}))
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
            p_limits = getattr(trader, "limits", {})
            p_limit = p_limits.get(p, limits)
            for order in order_list:
                qty, price = order.quantity, order.price
                if qty > 0 and price >= curr_ask:
                    fill = min(qty, p_limit - positions[p])
                    if fill > 0:
                        positions[p] += fill; cash -= fill * curr_ask
                elif qty < 0 and price <= curr_bid:
                    fill = min(-qty, p_limit + positions[p])
                    if fill > 0:
                        positions[p] -= fill; cash += fill * curr_bid
        mtm = cash + sum(positions[p] * mids[p] for p in products)
        pnl_history.append(mtm)
    return {
        "pnl_curve": pnl_history,
        "final_pnl": pnl_history[-1],
        "max_dd": max([peak - val for peak, val in zip(np.maximum.accumulate(pnl_history), pnl_history)]),
        "final_pos": sum(abs(v) for v in positions.values())
    }

def run_backtest_simulation(day):
    st.toast(f"Running simulation against Day {day}...")
    df_prices, df_trades = load_and_process_data(day)
    if df_prices is None:
        st.error("Missing data for simulation!")
        return

    TraderClass = load_default_trader_class()
    trader = TraderClass()
    listings = {
        "ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "XIRECS"),
        "INTARIAN_PEPPER_ROOT": Listing("INTARIAN_PEPPER_ROOT", "INTARIAN_PEPPER_ROOT", "XIRECS")
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
                depth.buy_orders = {int(row["bid_price_1"]): 10}
                depth.sell_orders = {int(row["ask_price_1"]): -10}
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
        total_steps = len(timestamps)
        progress_bar = st.progress(0)
        for i, ts in enumerate(timestamps):
            if i % 500 == 0: progress_bar.progress((i + 1) / total_steps)
            ts_data = price_map[ts]
            order_depths = {p: d[0] for p, d in ts_data.items()}
            state = TradingState(traderData=trader.traderData, timestamp=ts, listings=listings,
                                 order_depths=order_depths, own_trades={}, market_trades={},
                                 position=positions, observations=Observation({}, {}))
            orders, conversions, trader_data = trader.run(state)
            trader.traderData = trader_data
            for product, order_list in orders.items():
                if product not in ts_data: continue
                _, curr_ask, curr_bid = ts_data[product]
                for order in order_list:
                    qty, price, filled = order.quantity, order.price, False
                    if qty > 0 and price >= curr_ask:
                        fill_qty = min(qty, 20 - positions[product])
                        if fill_qty > 0:
                            positions[product] += fill_qty; cash -= fill_qty * curr_ask; filled = True
                            st.session_state.trades_log.append(f"TS {ts}: AGG BUY {fill_qty} {product} @ {curr_ask}")
                    elif qty < 0 and price <= curr_bid:
                        fill_qty = min(-qty, positions[product] + 20)
                        if fill_qty > 0:
                            positions[product] -= fill_qty; cash += fill_qty * curr_bid; filled = True
                            st.session_state.trades_log.append(f"TS {ts}: AGG SELL {fill_qty} {product} @ {curr_bid}")
                    if not filled and ts in trade_lookup:
                        mkt_trades = trade_lookup[ts].get(product, [])
                        for trade in mkt_trades:
                            trade_price, trade_qty = int(trade["price"]), 1
                            if qty > 0 and price >= trade_price:
                                fill_qty = min(qty, 20 - positions[product], trade_qty)
                                if fill_qty > 0:
                                    positions[product] += fill_qty; cash -= fill_qty * price
                                    st.session_state.trades_log.append(f"TS {ts}: PASSIVE BUY {fill_qty} {product} @ {price}")
                                    break
                            elif qty < 0 and price <= trade_price:
                                fill_qty = min(-qty, positions[product] + 20, trade_qty)
                                if fill_qty > 0:
                                    positions[product] -= fill_qty; cash += fill_qty * price
                                    st.session_state.trades_log.append(f"TS {ts}: PASSIVE SELL {fill_qty} {product} @ {price}")
                                    break
            mtm_pnl = cash
            for product, pos in positions.items():
                if product in ts_data: mtm_pnl += pos * ((ts_data[product][1] + ts_data[product][2]) / 2.0)
            pnl_history.append(mtm_pnl)
    except Exception as e:
        st.error(f"Error during simulation: {str(e)}"); return
    final_pnl = pnl_history[-1] if pnl_history else 0
    st.session_state.sim_result = {"pnl": final_pnl, "day": day}
    st.success(f"Simulation Complete! Final PnL: **{final_pnl:,.2f}**")
    if pnl_history:
        pnl_df = pd.DataFrame({"Timestamp": range(len(pnl_history)), "PnL": pnl_history})
        if len(pnl_df) > 1000: pnl_df = pnl_df.iloc[::len(pnl_df)//1000]
        st.line_chart(pnl_df.set_index("Timestamp"), width="stretch")

def load_and_process_data(day):
    data_dir = get_paths()["data_dir"]
    available_days = discover_available_days(data_dir)
    days_to_load = available_days if day == "All" else [day]
    all_prices, all_trades = [], []
    for d in days_to_load:
        prices_file = _resolve_round_day_file(data_dir, "prices", d)
        trades_file = _resolve_round_day_file(data_dir, "trades", d)
        if prices_file and os.path.exists(prices_file):
            df_p = pd.read_csv(prices_file, sep=";")
            df_p = df_p.dropna(subset=["bid_price_1", "ask_price_1", "timestamp"])
            if day == "All": df_p["timestamp"] = df_p["timestamp"] + (d + 2) * 1000000
            df_p["day"] = d; all_prices.append(df_p)
        if trades_file and os.path.exists(trades_file):
            df_t = pd.read_csv(trades_file, sep=";")
            if "symbol" in df_t.columns: df_t = df_t.rename(columns={"symbol": "product"})
            if day == "All": df_t["timestamp"] = df_t["timestamp"] + (d + 2) * 1000000
            df_t["day"] = d; all_trades.append(df_t)
    if not all_prices: return None, None
    df_prices = pd.concat(all_prices, ignore_index=True)
    df_prices["mid_price"] = (df_prices["bid_price_1"] + df_prices["ask_price_1"]) / 2.0
    df_prices = df_prices.groupby(["timestamp", "product", "day"]).mean(numeric_only=True).reset_index()
    return df_prices, pd.concat(all_trades, ignore_index=True) if all_trades else None

def render_chart(df_prices, df_trades, product, color, show_mean=False):
    df_p = df_prices[df_prices["product"] == product].copy()
    if df_p.empty: return
    is_multi_day = df_p["day"].nunique() > 1
    color_encoding = alt.Color("day:N", scale=alt.Scale(scheme="category10")) if is_multi_day else alt.value(color)
    line = alt.Chart(df_p).mark_line().encode(x="timestamp:Q", y=alt.Y("mid_price:Q", scale=alt.Scale(zero=False)), color=color_encoding)
    band = alt.Chart(df_p).mark_area(opacity=0.3).encode(x="timestamp:Q", y="bid_price_1:Q", y2="ask_price_1:Q", color=color_encoding)
    layers = [band, line]
    if show_mean: layers.append(alt.Chart(pd.DataFrame({"y": [df_p["mid_price"].mean()]})).mark_rule(color="#e67e22", strokeDash=[5, 5]).encode(y="y:Q"))
    if df_trades is not None:
        df_t = df_trades[df_trades["product"] == product].copy()
        if not df_t.empty: layers.append(alt.Chart(df_t).mark_circle(size=60, color="white", stroke="black").encode(x="timestamp:Q", y="price:Q"))
    st.altair_chart(alt.layer(*layers).properties(width="container", height=320).interactive(), use_container_width=True)
    return df_p

def render_manual_optimizer_tab():
    st.subheader("♟️ Manual Challenge Optimizer")
    
    with st.expander("📖 The Pillars (Official Documentation)", expanded=False):
        st.markdown("""
        **Research** determines how strong your trading edge is. It grows **logarithmically** from `0` to `200 000`.
        **Scale** determines how broadly you deploy your strategy. It grows **linearly** from `0` to `7`.
        **Speed** is **rank-based** across all players (0.9 multiplier for top, 0.1 for bottom).
        """)

    st.markdown("### 1. Advanced Competitiveness Modeler")
    if "competitor_clusters" not in st.session_state:
        st.session_state.competitor_clusters = pd.DataFrame([
            {"Cluster Name": "The Zeroes", "Speed Center": 0, "Spread (Std Dev)": 0, "% of Population": 20},
            {"Cluster Name": "The Herd", "Speed Center": 40, "Spread (Std Dev)": 5, "% of Population": 75},
            {"Cluster Name": "The Maxers", "Speed Center": 100, "Spread (Std Dev)": 0, "% of Population": 5}
        ])

    edited_df = st.data_editor(
        st.session_state.competitor_clusters,
        num_rows="dynamic",
        use_container_width=True
    )
    
    pop_size = st.number_input("Sim Population", 10, 10000, 1000)
    np.random.seed(42)
    pop = []
    tot_pct = edited_df["% of Population"].sum() or 1
    for _, row in edited_df.iterrows():
        n = int((row["% of Population"] / tot_pct) * pop_size)
        if n > 0:
            if row["Spread (Std Dev)"] <= 0: pop.extend([row["Speed Center"]] * n)
            else: pop.extend(np.random.normal(row["Speed Center"], row["Spread (Std Dev)"], n))
    
    comp_speeds = np.clip(np.round(pop or [40] * pop_size), 0, 100).astype(int)
    total_players = len(comp_speeds) + 1

    def get_multiplier(z_val):
        rank = np.sum(comp_speeds > z_val) + 1
        return 0.9 - (0.8 * (rank - 1) / (total_players - 1))

    # Optim Curve
    best_pnl_for_z, optimal_x_for_z = [], []
    for test_z in range(101):
        mult, max_n, best_x = get_multiplier(test_z), -float('inf'), 0
        rem = 100 - test_z
        for test_x in range(rem + 1):
            n = (200_000 * np.log(1 + test_x) / np.log(101)) * (0.07 * (rem - test_x)) * mult - 50000
            if n > max_n: max_n, best_x = n, test_x
        best_pnl_for_z.append(max_n)
        optimal_x_for_z.append(best_x)

    best_z = int(np.argmax(best_pnl_for_z))
    
    st.markdown("### 2. Projected Optimal Curve")
    chart_df = pd.DataFrame({"Speed": range(101), "Max_PnL": best_pnl_for_z})
    st.altair_chart(alt.Chart(chart_df).mark_line(color="#2ecc71").encode(
        x="Speed:Q", y="Max_PnL:Q", tooltip=["Speed", "Max_PnL"]
    ).properties(height=300).interactive(), use_container_width=True)

    st.markdown("### 3. Allocation")
    z = st.slider("Select Speed (z)", 0, 100, best_z)
    x = st.slider("Select Research (x)", 0, 100 - z, optimal_x_for_z[z])
    y = 100 - z - x
    
    res_val = 200_000 * np.log(1 + x) / np.log(101)
    scale_val = 0.07 * y
    mult = get_multiplier(z)
    net_pnl = res_val * scale_val * mult - 50000

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Research", f"{res_val:,.0f}")
    col2.metric("Scale", f"{scale_val:.3f}")
    col3.metric("Multiplier", f"{mult:.3f}x")
    col4.metric("Net Projected PnL", f"{net_pnl:,.0f} XIRECs")

def main():
    st.set_page_config(page_title="P4 Control Center", layout="wide")
    if "active_round" not in st.session_state:
        st.session_state.active_round = DEFAULT_ROUND if DEFAULT_ROUND in ROUND_DIRS else (ROUND_DIRS[0] if ROUND_DIRS else DEFAULT_ROUND)
    sync_round_import_paths(st.session_state.active_round)
    if ROUND_DIRS:
        selected_round = st.sidebar.selectbox("Round Folder", ROUND_DIRS, index=ROUND_DIRS.index(st.session_state.active_round) if st.session_state.active_round in ROUND_DIRS else 0)
        if selected_round != st.session_state.active_round:
            st.session_state.active_round = selected_round; sync_round_import_paths(selected_round); st.rerun()

    st.title("📈 Prosperity Operations Console")
    tab_backtest, tab_robust, tab_manual = st.tabs(["📉 Visual Backtester", "🛡️ Robust Analysis", "♟️ Manual Optimizer"])
    
    with tab_manual:
        render_manual_optimizer_tab()

    with tab_robust:
        st.header("🛡️ Robust Multi-Scenario Analysis")
        st.markdown("""
        Test traders against **real-world market data** and **synthetic regime scenarios**.
        The goal: **best average PnL across ANY situation**.
        """)
        
        paths = get_paths()
        res_dir = paths["results_robust_dir"]
        if os.path.exists(res_dir):
            files = [f for f in os.listdir(res_dir) if f.endswith("_robust_results.csv")]
            if files:
                selected = st.selectbox("Select Result Profile", files)
                df_res = pd.read_csv(os.path.join(res_dir, selected))
                st.dataframe(df_res, use_container_width=True)
            else:
                st.info("No robust results found in " + res_dir)
        else:
            st.warning("Robust results directory not found.")
    
    with tab_backtest:
        available_days = discover_available_days(get_paths()["data_dir"])
        day = st.radio("Day", ["All"] + available_days, horizontal=True)
        if st.button("Run Simulation"): run_backtest_simulation(day)
        df_p, df_t = load_and_process_data(day)
        if df_p is not None:
            render_chart(df_p, df_t, "ASH_COATED_OSMIUM", "#2ecc71", True)
            render_chart(df_p, df_t, "INTARIAN_PEPPER_ROOT", "#e74c3c", False)

if __name__ == "__main__":
    main()
