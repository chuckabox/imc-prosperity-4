import streamlit as st
import math
import json
import os
import sys

# Resolve absolute paths for relative imports (datamodel in ../config, trader in ../traders)
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.abspath(os.path.join(script_dir, "..", "config"))
traders_path = os.path.abspath(os.path.join(script_dir, "..", "traders"))

if config_path not in sys.path:
    sys.path.insert(0, config_path)
if traders_path not in sys.path:
    sys.path.insert(0, traders_path)

import pandas as pd
import altair as alt
import re
from datamodel import Listing, OrderDepth, TradingState, Observation, Order
import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import make_interp_spline

CONFIG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "config.json"))
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data_capsule"))

def load_config():
    defaults = {
        "osmium_active": True,
        "pepper_active": True,
        "osmium_limit": 80,
        "pepper_limit": 80,
        "target_spread": 2,
        "mr_threshold": 2,
        "edge": 1.5,
        "skew": 0.2
    }
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            try:
                config = json.load(f)
                return {**defaults, **config}
            except:
                pass
    return defaults

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
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

from trader import Trader, logger as trader_logger

def execute_backtest_headless(day, trader_path, config_override=None):
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
        "ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "XIRECS"),
        "INTARIAN_PEPPER_ROOT": Listing("INTARIAN_PEPPER_ROOT", "INTARIAN_PEPPER_ROOT", "XIRECS")
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

def run_backtest_simulation(day, round_filter="All"):
    st.toast(f"Running simulation against {round_filter} Day {day}...")

    df_prices, df_trades = load_and_process_data(day, round_filter)
    if df_prices is None:
        st.error("Missing data for simulation!")
        return

    trader = Trader()
    trader.traderData = ""
    # Mock symbols and listings
    listings = {
        "ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "XIRECS"),
        "INTARIAN_PEPPER_ROOT": Listing("INTARIAN_PEPPER_ROOT", "INTARIAN_PEPPER_ROOT", "XIRECS")
    }

    total_pnl = 0.0
    positions = {"ASH_COATED_OSMIUM": 0, "INTARIAN_PEPPER_ROOT": 0}
    cash = 0.0

    if "trades_log" not in st.session_state:
        st.session_state.trades_log = []
    st.session_state.trades_log = []

    pnl_history = []
    try:
        # --- OPTIMIZATION: Pre-process data into efficient lookups ---
        # Prices: timestamp -> {product: depth_obj}
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

        # Trades: timestamp -> {product: [trade_rows]}
        trade_lookup = {}
        if df_trades is not None:
            for ts, group in df_trades.groupby("timestamp"):
                ts_trades = {}
                for product, p_group in group.groupby("product"):
                    ts_trades[product] = p_group.to_dict('records')
                trade_lookup[ts] = ts_trades

        timestamps = sorted(price_map.keys())
        total_steps = len(timestamps)
        progress_bar = st.progress(0)

        for i, ts in enumerate(timestamps):
            if i % 500 == 0:
                progress_bar.progress((i + 1) / total_steps)

            ts_data = price_map[ts]
            order_depths = {p: d[0] for p, d in ts_data.items()}

            state = TradingState(
                traderData=trader.traderData,
                timestamp=ts,
                listings=listings,
                order_depths=order_depths,
                own_trades={},
                market_trades={},
                position=positions,
                observations=Observation({}, {})
            )

            orders, conversions, trader_data = trader.run(state)
            trader.traderData = trader_data

            # --- Optimized Fill Logic ---
            limits = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
            full_tick_data = [] # To store metrics for every single tick

            for product, order_list in orders.items():
                if product not in ts_data: continue
                _, curr_ask, curr_bid = ts_data[product]
                mid_fill = (curr_ask + curr_bid) / 2.0
                limit = limits.get(product, 80)

                for order in order_list:
                    qty = order.quantity
                    price = order.price
                    fill_info = None

                    if qty > 0 and price >= curr_ask:
                        fill_qty = min(qty, limit - positions[product])
                        if fill_qty > 0:
                            positions[product] += fill_qty
                            cash -= fill_qty * curr_ask
                            fill_info = {"ts": ts, "product": product, "qty": fill_qty, "price": curr_ask, "side": "BUY", "type": "AGG", "mid_fill": mid_fill}
                    elif qty < 0 and price <= curr_bid:
                        fill_qty = min(-qty, positions[product] + limit)
                        if fill_qty > 0:
                            positions[product] -= fill_qty
                            cash += fill_qty * curr_bid
                            fill_info = {"ts": ts, "product": product, "qty": -fill_qty, "price": curr_bid, "side": "SELL", "type": "AGG", "mid_fill": mid_fill}

                    if fill_info is None and ts in trade_lookup:
                        mkt_trades = trade_lookup[ts].get(product, [])
                        for trade in mkt_trades:
                            trade_price = int(trade["price"])
                            trade_qty = 1

                            if qty > 0 and price >= trade_price:
                                fill_qty = min(qty, limit - positions[product], trade_qty)
                                if fill_qty > 0:
                                    positions[product] += fill_qty
                                    cash -= fill_qty * trade_price
                                    fill_info = {"ts": ts, "product": product, "qty": fill_qty, "price": trade_price, "side": "BUY", "type": "PASSIVE", "mid_fill": mid_fill}
                                    break
                            elif qty < 0 and price <= trade_price:
                                fill_qty = min(-qty, limit + positions[product], trade_qty)
                                if fill_qty > 0:
                                    positions[product] -= fill_qty
                                    cash += fill_qty * trade_price
                                    fill_info = {"ts": ts, "product": product, "qty": -fill_qty, "price": trade_price, "side": "SELL", "type": "PASSIVE", "mid_fill": mid_fill}
                                    break
                    
                    if fill_info:
                        st.session_state.trades_log.append(fill_info)

            # Mark-to-market
            mtm_pnl = cash
            for product, pos in positions.items():
                if product in ts_data:
                    mid = (ts_data[product][1] + ts_data[product][2]) / 2.0
                    mtm_pnl += pos * mid

            pnl_history.append(mtm_pnl)
            
            # Record tick-level metrics for Pattern/Inventory analysis
            tick_metrics = {"ts": ts, "mtm": mtm_pnl}
            for p, pos in positions.items():
                tick_metrics[f"pos_{p}"] = pos
                if p in ts_data:
                    tick_metrics[f"mid_{p}"] = (ts_data[p][1] + ts_data[p][2]) / 2.0
            
            full_tick_data.append(tick_metrics)

    except Exception as e:
        st.error(f"Error during simulation: {str(e)}")
        import traceback
        st.code(traceback.format_exc())
        return

    final_pnl = pnl_history[-1] if pnl_history else 0
    st.session_state.sim_result = {
        "pnl": final_pnl, 
        "day": day, 
        "round": round_filter,
        "trades": st.session_state.trades_log,
        "ticks": full_tick_data
    }
    st.success(f"Simulation Complete! Final PnL: **{final_pnl:,.2f}**")

    st.success(f"Simulation Complete! Final PnL: **{final_pnl:,.2f}**")

    if pnl_history:
        pnl_df = pd.DataFrame({"Timestamp": range(len(pnl_history)), "PnL": pnl_history})
        if len(pnl_df) > 1000:
            pnl_df = pnl_df.iloc[::len(pnl_df)//1000]
        st.line_chart(pnl_df.set_index("Timestamp"), width="stretch")

# Disable caching temporarily to ensure fresh data for every backtest
# @st.cache_data
def load_and_process_data(day, round_filter="All"):
    all_prices = []
    all_trades = []
    
    # Map Round selection to numeric
    r_target = None
    if round_filter == "Round 1": r_target = 1
    elif round_filter == "Round 2": r_target = 2

    # Discovery logic
    price_files = [f for f in os.listdir(DATA_DIR) if f.startswith("prices_round_") and f.endswith(".csv")]
    
    days_to_load_files = []
    for f in price_files:
        match = re.search(r"round_(\d+)_day_(-?\d+)", f)
        if not match: continue
        
        r_num = int(match.group(1))
        d_num = int(match.group(2))
        
        # Filter logic
        round_matches = (r_target is None or r_num == r_target)
        day_matches = (day == "All" or d_num == int(day))
        
        if round_matches and day_matches:
            days_to_load_files.append((f, f.replace("prices_", "trades_")))

    for p_file, t_file in days_to_load_files:
        prices_full_path = os.path.join(DATA_DIR, p_file)
        trades_full_path = os.path.join(DATA_DIR, t_file)
        
        # Extract day and round from filename
        match = re.search(r"round_(\d+)_day_(-?\d+)", p_file)
        r_num = int(match.group(1)) if match else 1
        d_num = int(match.group(2)) if match else 0

        if os.path.exists(prices_full_path):
            df_p = pd.read_csv(prices_full_path, sep=";")
            df_p = df_p.dropna(subset=["bid_price_1", "ask_price_1", "timestamp"])
            if day == "All":
                # offset for unique continuous timeline across rounds/days
                offset = (r_num * 10 + d_num + 10) * 1000000 
                df_p["timestamp"] = df_p["timestamp"] + offset
            df_p["day"] = d_num
            df_p["round"] = r_num
            all_prices.append(df_p)
            
        if os.path.exists(trades_full_path):
            df_t = pd.read_csv(trades_full_path, sep=";")
            if "symbol" in df_t.columns:
                df_t = df_t.rename(columns={"symbol": "product"})
            if day == "All":
                offset = (r_num * 10 + d_num + 10) * 1000000
                df_t["timestamp"] = df_t["timestamp"] + offset
            df_t["day"] = d_num
            df_t["round"] = r_num
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




def render_manual_optimizer_tab():
    st.subheader("♟️ Manual Challenge Optimizer")
    
    with st.expander("📖 The Pillars (Official Documentation)", expanded=False):
        st.markdown("""
        **Research** determines how strong your trading edge is. It grows **logarithmically** from `0` (for `0` invested) to `200 000` (for `100` invested). The exact formula is `research(x) = 200_000 * np.log(1 + x) / np.log(1 + 100)`. Here, `np.log` is a python function from NumPy package for natural logarithm.

        **Scale** determines how broadly you deploy your strategy across markets. It grows **linearly** from `0` (for `0` invested) to `7` (for `100` invested).

        **Speed** determines how often you win the trades you target. It is **rank-based** across all players:

        - Highest speed investment receives a `0.9` multiplier.
        - Lowest receives `0.1`.
        - Everyone in between is scaled linearly by rank, equal investments share the same rank.
        - For example, if people invested `70, 70, 70, 50, 40, 40, 30`, they get the following ranks: `1, 1, 1, 4, 5, 5, 7`. First three players get `0.9` for hit rate multiplier, last player gets `0.1`, and everybody in between gets linearly scaled between top and bottom rank. Another example, if you have three players investing `95, 20, 10`, their ranks are `1, 2, 3`, and their hit rates are `0.9, 0.5, 0.1`.

        Your Research, Scale, and Speed outcomes are multiplied together to form your gross PnL, after which the used part of your budget is deducted.

        Every decision you make reflects a real trade-off faced by modern market makers: capital is finite, competition is relentless, and edge alone is never enough. Good luck!
        """)

    st.markdown("### 1. Advanced Competitiveness Modeler")
    st.markdown("Define the exact strategic breakdown of the competitor population. You can add as many clusters as you want to try out complex game-theory scenarios. **Set Spread to 0** if you want players to pick the exact center value instead of a bell curve.")
    
    if "competitor_clusters" not in st.session_state:
        st.session_state.competitor_clusters = pd.DataFrame([
            {"Cluster Name": "The Zeroes", "Speed Center": 0, "Spread (Std Dev)": 0, "% of Population": 20},
            {"Cluster Name": "The Herd", "Speed Center": 40, "Spread (Std Dev)": 5, "% of Population": 75},
            {"Cluster Name": "The Maxers", "Speed Center": 100, "Spread (Std Dev)": 0, "% of Population": 5}
        ])

    edited_df = st.data_editor(
        st.session_state.competitor_clusters,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Speed Center": st.column_config.NumberColumn("Speed Center", min_value=0, max_value=100),
            "Spread (Std Dev)": st.column_config.NumberColumn("Spread (Std Dev)", min_value=0),
            "% of Population": st.column_config.NumberColumn("% of Population", min_value=0)
        }
    )
    
    tot_pct = edited_df["% of Population"].sum()
    if tot_pct != 100 and tot_pct > 0:
        st.info(f"Percentages sum to {tot_pct}%. They will be mathematically normalized to 100% in the simulation.")

    pop_size = st.number_input("Simulation Population Size", min_value=10, max_value=10000, value=1000, help="How many total opponents to simulate. Larger = smoother bell curves.")

    # Generate population
    np.random.seed(42)
    pop = []
    if tot_pct > 0:
        for _, row in edited_df.iterrows():
            n_players = int((row["% of Population"] / tot_pct) * pop_size)
            if n_players > 0:
                if row["Spread (Std Dev)"] <= 0:
                    pop.extend(np.ones(n_players) * row["Speed Center"])
                else:
                    cluster = np.random.normal(row["Speed Center"], row["Spread (Std Dev)"], n_players)
                    pop.extend(cluster)
    
    if len(pop) == 0:
        pop = [40] * pop_size
    
    comp_speeds = np.array(pop)
    comp_speeds = np.clip(np.round(comp_speeds), 0, 100).astype(int)
    total_players = len(comp_speeds) + 1

    with st.expander("📊 View Generated Opponent Distribution", expanded=False):
        dist_df = pd.DataFrame({"Opponent Speed": comp_speeds})
        dist_chart = alt.Chart(dist_df).mark_bar(color="#5dade2").encode(
            x=alt.X("Opponent Speed:O", title="Speed Choice (0-100)"),
            y=alt.Y("count()", title="Number of Players")
        ).properties(height=250)
        st.altair_chart(dist_chart, use_container_width=True)

    def get_multiplier(z_val):
        rank = np.sum(comp_speeds > z_val) + 1
        return 0.9 - (0.8 * (rank - 1) / (total_players - 1))

    # Pre-calculate Max PnL for every possible Z (0 to 100)
    best_pnl_for_z = []
    optimal_x_for_z = []
    for test_z in range(101):
        mult = get_multiplier(test_z)
        max_n = -float('inf')
        best_x = 0
        rem = 100 - test_z
        for test_x in range(rem + 1):
            test_y = rem - test_x
            r = 200_000 * np.log(1 + test_x) / np.log(101)
            s = 0.07 * test_y
            n = r * s * mult - 50000
            if n > max_n:
                max_n = n
                best_x = test_x
        best_pnl_for_z.append(max_n)
        optimal_x_for_z.append(best_x)

    best_overall_z = int(np.argmax(best_pnl_for_z))
    best_overall_pnl = best_pnl_for_z[best_overall_z]
    best_overall_x = optimal_x_for_z[best_overall_z]
    best_overall_y = 100 - best_overall_z - best_overall_x

    st.markdown("---")
    st.markdown("### 2. Projected Optimal Curve")
    st.markdown("This curve shows the **Maximum possible Net PnL** for any chosen Speed (x-axis), assuming you optimally distribute the *remaining* budget between Research and Scale.")

    curve_df = pd.DataFrame({
        "Speed Investment": list(range(101)),
        "Max Net PnL": best_pnl_for_z,
        "Optimal Research": optimal_x_for_z
    })
    
    # Calculate a baseline y=0 line
    zero_line = pd.DataFrame({"Speed Investment": list(range(101)), "Max Net PnL": [0]*101})
    zero_chart = alt.Chart(zero_line).mark_line(color="orange", strokeDash=[5, 5]).encode(x="Speed Investment:Q", y="Max Net PnL:Q")

    chart = alt.Chart(curve_df).mark_line(color="#2ecc71").encode(
        x="Speed Investment:Q",
        y="Max Net PnL:Q",
        tooltip=["Speed Investment", "Max Net PnL", "Optimal Research"]
    ).properties(height=400, title="Optimal Net PnL vs Speed Investment")
    
    opt_pt = pd.DataFrame({"Speed Investment": [best_overall_z], "Max Net PnL": [best_overall_pnl]})
    pt = alt.Chart(opt_pt).mark_point(color="white", size=100, filled=True, stroke="black", strokeWidth=2).encode(x="Speed Investment:Q", y="Max Net PnL:Q")
    
    st.altair_chart(zero_chart + chart + pt, use_container_width=True)

    
    st.success(f"**Mathematical Peak:** With this competitor distribution, the max theoretical PnL is at **Speed {best_overall_z}**, with Research **{best_overall_x}** and Scale **{best_overall_y}**.")

    st.markdown("---")
    st.markdown("### 3. Your Allocation")
    st.markdown("Select your Speed based on the curve above, then allocate the remainder.")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        z = st.slider("Step 1: Speed (z)", min_value=0, max_value=100, value=best_overall_z, step=1)
    
    remaining_budget = 100 - z
    
    with col2:
        x = st.slider(f"Step 2: Research (x)", min_value=0, max_value=remaining_budget, value=min(best_overall_x, remaining_budget), step=1)
        
    y = remaining_budget - x
    with col3:
        st.metric(f"Step 3: Scale (y) [Auto-calculated]", f"{y} points")

    # --- MATH LOGIC ---
    base_research = 200_000 * np.log(1 + x) / np.log(101)
    base_scale = 0.07 * y
    speed_mult = get_multiplier(z)
    rank = np.sum(comp_speeds > z) + 1
    
    gross_pnl = base_research * base_scale * speed_mult
    budget_cost = 50000 
    net_pnl = gross_pnl - budget_cost

    # --- LIVE METRICS ---
    st.markdown("---")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Research Value", f"{base_research:,.0f}")
    m2.metric("Scale Value", f"{base_scale:.3f}")
    m3.metric("Simulated Rank", f"{rank} / {total_players}")
    m4.metric("Speed Multiplier", f"{speed_mult:.3f}x")
    m5.metric("Net Projected PnL", f"{net_pnl:,.0f} XIRECs", delta=f"{net_pnl - 173635:,.0f} vs Baseline")

    col_chart1, col_chart2 = st.columns(2)
    with col_chart1:
        st.markdown(f"**Research vs Scale tradeoff given {z} Speed points**")
        
        # Simple grid evaluation for 1D line chart
        grid_res = []
        for rx in range(0, remaining_budget + 1):
            sy = remaining_budget - rx
            R = 200_000 * np.log(1 + rx) / np.log(101)
            S = 0.07 * sy
            G = R * S * speed_mult
            N = G - 50000
            grid_res.append({"Research": rx, "Scale": sy, "Net_PnL": N})
            
        heat_df = pd.DataFrame(grid_res)
        if not heat_df.empty:
            heat = alt.Chart(heat_df).mark_line(color="#3498db").encode(
                x=alt.X("Research:Q", title=f"Research Points (out of {remaining_budget})"),
                y=alt.Y("Net_PnL:Q", title="Net PnL"),
                tooltip=["Research", "Scale", "Net_PnL"]
            ).properties(height=350).interactive()
            
            # Active setup point
            current_point = pd.DataFrame({"Research": [x], "Scale": [y], "Net_PnL": [net_pnl]})
            curr_mark = alt.Chart(current_point).mark_point(size=150, color="orange", filled=True, stroke="black").encode(
                x="Research:Q", y="Net_PnL:Q", tooltip=["Research", "Scale", "Net_PnL"]
            )
            
            st.altair_chart(heat + curr_mark, use_container_width=True)
            
    with col_chart2:
        st.markdown("**Research Diminishing Returns**")
        x_vals = np.linspace(0, 100, 100)
        r_vals = 200_000 * np.log(1 + x_vals) / np.log(101)
        line_df = pd.DataFrame({"Investment": x_vals, "Research Value": r_vals})
        chart = alt.Chart(line_df).mark_line(color="#e67e22").encode(
            x=alt.X("Investment:Q", title="Research Points invested"),
            y=alt.Y("Research Value:Q", title="Value Provided")
        ).properties(height=350)
        current_x = pd.DataFrame({"Investment": [x], "Research Value": [base_research]})
        point = alt.Chart(current_x).mark_point(color="red", size=150, filled=True, stroke="black").encode(x="Investment:Q", y="Research Value:Q")
        st.altair_chart(chart + point, use_container_width=True)

def main():
    st.set_page_config(
        page_title="P4 Control Center",
        layout="wide"
    )

    # --- MAIN CONTENT ---
    st.title("📈 Prosperity 4: Operations Console")

    # Final tab layout
    tab_backtest, tab_robust, tab_manual = st.tabs([
        "📉 Visual Backtester",
        "🛡️ Robust Analysis",
        "♟️ Manual Optimizer"
    ])



    with tab_robust:
        st.header("🛡️ Robust Multi-Scenario Analysis")
        st.markdown("""
        Test traders against **real-world market data** and **synthetic regime scenarios** to prevent overfitting.
        The goal: **best average PnL across ANY situation**, not peak PnL on known data.
        """)

        # Robust backtester outputs are now saved under results/robust.
        # Keep a fallback to tools for older runs.
        robust_results_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "results", "robust"))
        fallback_tools_dir = os.path.dirname(os.path.abspath(__file__))

        robust_csvs = []
        if os.path.isdir(robust_results_dir):
            robust_csvs = [f for f in os.listdir(robust_results_dir) if f.endswith("_robust_results.csv")]
        if not robust_csvs and os.path.isdir(fallback_tools_dir):
            robust_results_dir = fallback_tools_dir
            robust_csvs = [f for f in os.listdir(robust_results_dir) if f.endswith("_robust_results.csv")]

        if robust_csvs:
            p_filter = "All"
            target_col = "final_pnl"

            tab_lead, tab_inspect, tab_stress = st.tabs(["🏆 Leaderboard & Comparison", "📊 Individual Inspection", "🔬 Anti-Overfit Stress Lab"])

            # Pre-load all data for leaderboard and comparison
            all_leaderboard_data = []
            all_dfs = []
            for f in robust_csvs:
                df = pd.read_csv(os.path.join(robust_results_dir, f))
                name = f.replace("_robust_results.csv", "")
                
                pnls = df["final_pnl"] if "final_pnl" in df.columns else pd.Series([0.0]*len(df))
                
                all_leaderboard_data.append({
                    "Trader": name,
                    "Mean PnL": pnls.mean(),
                    "Median PnL": pnls.median(),
                    "Worst PnL": pnls.min(),
                    "Win Rate": (pnls > 0).mean() * 100 if not pnls.empty else 0
                })
                df["target_pnl"] = pnls
                df["trader"] = name
                all_dfs.append(df)
            
            leaderboard_df = pd.DataFrame(all_leaderboard_data)
            full_df = pd.concat(all_dfs)

            with tab_lead:
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
                        y=alt.Y("target_pnl:Q", title="PnL ($)"),
                        color=alt.Color("trader:N", legend=None)
                    ).properties(height=350)
                    st.altair_chart(dist_chart, use_container_width=True)

                with col_c2:
                    st.markdown("**Mean PnL by Category**")
                    cat_comp = full_df.groupby(["trader", "category"])["target_pnl"].mean().reset_index()
                    cat_chart = alt.Chart(cat_comp).mark_bar().encode(
                        x=alt.X("category:N", title="Category"),
                        y=alt.Y("target_pnl:Q", title="Mean PnL ($)"),
                        color=alt.Color("trader:N", title="Trader"),
                        xOffset="trader:N"
                    ).properties(height=350)
                    st.altair_chart(cat_chart, use_container_width=True)

                st.divider()
                st.markdown("**Risk Frontier: PnL vs Max Drawdown (All Scenarios)**")
                risk_scatter = alt.Chart(full_df).mark_circle(size=60, opacity=0.6).encode(
                    x=alt.X("target_pnl:Q", title="PnL ($)"),
                    y=alt.Y("max_drawdown:Q", title="Max Drawdown ($)"),
                    color=alt.Color("trader:N", title="Trader"),
                    tooltip=["trader", "name", "target_pnl", "max_drawdown", "category"]
                ).properties(height=450, title="Risk vs Reward (Total PnL) - All Scenarios").interactive()
                st.altair_chart(risk_scatter, use_container_width=True)

                st.divider()
                st.markdown("**PnL by Scenario Comparison (Heatmap)**")
                heatmap = alt.Chart(full_df).mark_rect().encode(
                    x=alt.X("trader:N", title="Trader", axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y("name:N", title="Scenario", sort="descending"),
                    color=alt.Color("target_pnl:Q", scale=alt.Scale(scheme="redyellowgreen", domainMid=0), title="PnL ($)"),
                    tooltip=["trader", "name", "target_pnl", "category"]
                ).properties(height=max(400, len(full_df["name"].unique()) * 15))
                st.altair_chart(heatmap, use_container_width=True)

            with tab_inspect:
                selected_result = st.selectbox("Select Results File for Deep Dive", robust_csvs, format_func=lambda x: x.replace("_robust_results.csv", ""))
                df_robust = pd.read_csv(os.path.join(robust_results_dir, selected_result))
                
                pnls = df_robust["final_pnl"] if "final_pnl" in df_robust.columns else pd.Series([0.0]*len(df_robust))
                df_robust["target_pnl"] = pnls

                col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                col_m1.metric("Mean PnL", f"${pnls.mean():,.0f}")
                col_m2.metric("Median PnL", f"${pnls.median():,.0f}")
                col_m3.metric("Worst PnL", f"${pnls.min():,.0f}")
                col_m4.metric("Win Rate", f"{(pnls > 0).mean()*100:.1f}%")

                st.divider()

                st.subheader("PnL by Category")
                if "category" in df_robust.columns:
                    cat_stats = df_robust.groupby("category")["target_pnl"].agg(["mean", "min", "max", "count"])
                    cat_stats.columns = ["Mean PnL", "Worst PnL", "Best PnL", "Count"]
                    st.dataframe(cat_stats.style.format("${:,.0f}", subset=["Mean PnL", "Worst PnL", "Best PnL"]))
                
                # --- INTEGRATED CONTINUITY MATRIX ---
                if "category" in df_robust.columns and "target_pnl" in df_robust.columns:
                    real_days = df_robust[df_robust["category"] == "real"]
                    if not real_days.empty:
                        st.subheader("📅 Multi-Day Continuity (Real Data)")
                        cols_to_show = ["name", "target_pnl", "max_drawdown"]
                        if "trade_count" in real_days.columns:
                            cols_to_show.append("trade_count")
                        
                        st.dataframe(
                            real_days[cols_to_show].style.background_gradient(subset=["target_pnl"], cmap="RdYlGn"),
                            use_container_width=True,
                            hide_index=True
                        )

                st.subheader("PnL by Scenario")
                bar_data = df_robust[["name", "target_pnl", "category"]].copy()
                bar_data = bar_data.sort_values("target_pnl")

                bar_chart = alt.Chart(bar_data).mark_bar().encode(
                    x=alt.X("target_pnl:Q", title="PnL ($)"),
                    y=alt.Y("name:N", sort="-x", title=""),
                    color=alt.Color("category:N", scale=alt.Scale(scheme="set2")),
                    tooltip=["name", "target_pnl", "category"],
                ).properties(height=max(300, len(bar_data) * 22), width="container",
                            title="PnL Across All Scenarios")
                st.altair_chart(bar_chart, use_container_width=True)

                st.subheader("PnL Distribution")
                hist_chart = alt.Chart(df_robust).mark_bar(opacity=0.8).encode(
                    x=alt.X("target_pnl:Q", bin=alt.Bin(maxbins=25), title="PnL ($)"),
                    y=alt.Y("count()", title="Scenarios"),
                    color=alt.Color("category:N", scale=alt.Scale(scheme="set2")),
                ).properties(height=300, title="PnL Distribution Histogram")
                st.altair_chart(hist_chart, use_container_width=True)

                if "max_drawdown" in df_robust.columns:
                    st.subheader("Risk: PnL vs Drawdown")
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
                trader_base = os.path.join(os.path.dirname(__file__), "..", "traders")
                for root, _, files in os.walk(trader_base):
                    for f in files:
                        if f.endswith(".py") and not f.startswith("__"):
                            trader_search.append(os.path.relpath(os.path.join(root, f), os.getcwd()))
                
                col_s1, col_s2 = st.columns(2)
                with col_s1:
                    sel_trader = st.selectbox("Target Trader", trader_search, key="stress_trader", index=next((i for i, x in enumerate(trader_search) if "v2d" in x), 0))
                with col_s2:
                    sel_source = st.selectbox("Base Dataset", ["All (Historical Data)", -1, -2, 0, 1], index=0)

                if st.button("☣️ Run Destructive Mutation Suite", type="primary", use_container_width=True):
                    source_key = "All" if sel_source == "All (Historical Data)" else sel_source
                    df_p, _ = load_and_process_data(source_key)
                    if df_p is None:
                        st.error("Base data not found!")
                    else:
                        active_prods = ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]
                        
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
                            - **Dampened**: Tests if the bot reacts to small moves.
                            """)


        else:
            st.warning("No robust results found. Run the robust backtester first:")
            st.code("python ROUND 2/tools/robust_backtester.py ROUND 2/traders/suvin/trader_robust_suvin_v1.py --quick")


    with tab_backtest:
        def on_selection_change():
            run_backtest_simulation(st.session_state.day_radio, st.session_state.round_radio)

        col_round, col_day, col_btn = st.columns([1.2, 2, 1])
        
        with col_round:
            selected_round = st.radio("Select Round:", ["All", "Round 1", "Round 2"],
                                       key="round_radio",
                                       horizontal=True,
                                       on_change=on_selection_change)

        with col_day:
            day_options = ["All", -2, -1, 0, 1]
            selected_day = st.radio("Select Day:", day_options,
                                     key="day_radio",
                                     index=0,
                                     horizontal=True,
                                     on_change=on_selection_change)
        
        with col_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔄 Run Simulation"):
                run_backtest_simulation(selected_day, selected_round)

        if "sim_result" in st.session_state and \
           st.session_state.sim_result["day"] == selected_day and \
           st.session_state.sim_result.get("round") == selected_round:
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                st.metric("Simulated PnL", f"${st.session_state.sim_result['pnl']:,.2f}")
            with col_m2:
                # --- Inventory Pressure Monitor ---
                ticks_df = pd.DataFrame(st.session_state.sim_result["ticks"])
                if not ticks_df.empty and "pos_ASH_COATED_OSMIUM" in ticks_df.columns:
                    # Calculate Correlation between Position and MTM Drawdown
                    ticks_df["peak"] = ticks_df["mtm"].cummax()
                    ticks_df["drawdown"] = ticks_df["peak"] - ticks_df["mtm"]
                    corr_os = ticks_df["pos_ASH_COATED_OSMIUM"].abs().corr(ticks_df["drawdown"])
                    st.metric("Inventory Pressure (Osmium)", f"{corr_os:.2f}", help="Correlation between Position Magnitude and PnL Drawdown. >0.4 indicates your inventory leaning is too weak.")

        st.markdown("---")

        df_prices, df_trades = load_and_process_data(selected_day, selected_round)

        if df_prices is not None:
            st.subheader(f"📊 Market Reconstruction ({selected_round} - Day {selected_day})")

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





    with tab_manual:
        render_manual_optimizer_tab()

if __name__ == "__main__":
    main()
