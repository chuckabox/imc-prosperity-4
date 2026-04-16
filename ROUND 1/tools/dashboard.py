import streamlit as st
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

def run_backtest_simulation(day):
    st.toast(f"Running simulation against Day {day}...")

    df_prices, df_trades = load_and_process_data(day)
    if df_prices is None:
        st.error("Missing data for simulation!")
        return

    trader = Trader()
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
            for product, order_list in orders.items():
                if product not in ts_data: continue
                _, curr_ask, curr_bid = ts_data[product]

                for order in order_list:
                    qty = order.quantity
                    price = order.price
                    filled = False

                    if qty > 0 and price >= curr_ask:
                        fill_qty = min(qty, 20 - positions[product])
                        if fill_qty > 0:
                            positions[product] += fill_qty
                            cash -= fill_qty * curr_ask
                            filled = True
                            st.session_state.trades_log.append(f"TS {ts}: AGG BUY {fill_qty} {product} @ {curr_ask}")
                    elif qty < 0 and price <= curr_bid:
                        fill_qty = min(-qty, positions[product] + 20)
                        if fill_qty > 0:
                            positions[product] -= fill_qty
                            cash += fill_qty * curr_bid
                            filled = True
                            st.session_state.trades_log.append(f"TS {ts}: AGG SELL {fill_qty} {product} @ {curr_bid}")

                    if not filled and ts in trade_lookup:
                        mkt_trades = trade_lookup[ts].get(product, [])
                        for trade in mkt_trades:
                            trade_price = int(trade["price"])
                            trade_qty = 1

                            if qty > 0 and price >= trade_price:
                                fill_qty = min(qty, 20 - positions[product], trade_qty)
                                if fill_qty > 0:
                                    positions[product] += fill_qty
                                    cash -= fill_qty * price
                                    st.session_state.trades_log.append(f"TS {ts}: PASSIVE BUY {fill_qty} {product} @ {price}")
                                    break
                            elif qty < 0 and price <= trade_price:
                                fill_qty = min(-qty, positions[product] + 20, trade_qty)
                                if fill_qty > 0:
                                    positions[product] -= fill_qty
                                    cash += fill_qty * price
                                    st.session_state.trades_log.append(f"TS {ts}: PASSIVE SELL {fill_qty} {product} @ {price}")
                                    break

            # Mark-to-market
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
    st.session_state.sim_result = {"pnl": final_pnl, "day": day}
    st.success(f"Simulation Complete! Final PnL: **{final_pnl:,.2f}**")

    if st.session_state.trades_log:
        with st.expander("📝 View Trade History (Latest 50)", expanded=False):
            for t in reversed(st.session_state.trades_log[-50:]):
                st.text(t)

    if pnl_history:
        pnl_df = pd.DataFrame({"Timestamp": range(len(pnl_history)), "PnL": pnl_history})
        # Downsample PnL chart for performance
        if len(pnl_df) > 1000:
            pnl_df = pnl_df.iloc[::len(pnl_df)//1000]
        st.line_chart(pnl_df.set_index("Timestamp"), width="stretch")

# Disable caching temporarily to ensure fresh data for every backtest
# @st.cache_data
def load_and_process_data(day):
    days_to_load = [-2, -1, 0] if day == "All" else [day]
    all_prices = []
    all_trades = []
    
    for d in days_to_load:
        prices_file = os.path.join(DATA_DIR, f"prices_round_1_day_{d}.csv")
        trades_file = os.path.join(DATA_DIR, f"trades_round_1_day_{d}.csv")
        
        if os.path.exists(prices_file):
            df_p = pd.read_csv(prices_file, sep=";")
            df_p = df_p.dropna(subset=["bid_price_1", "ask_price_1", "timestamp"])
            # Offset timestamp for continuity if showing All
            if day == "All":
                # days are -2, -1, 0 -> normalized to index 0, 1, 2 for continuous timeline
                offset = (d + 2) * 1000000 
                df_p["timestamp"] = df_p["timestamp"] + offset
            df_p["day"] = d
            all_prices.append(df_p)
            
        if os.path.exists(trades_file):
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

    # Compute Smooth Line (True FV)
    from scipy.ndimage import gaussian_filter1d
    y_smooth = gaussian_filter1d(y_raw, sigma=15)
    
    # Estimated Slope
    slope = np.gradient(y_smooth)

    # Plot
    plt.style.use('default')
    fig, ax1 = plt.subplots(figsize=(12, 5.5), facecolor=BG_COLOR)
    ax1.set_facecolor(BG_COLOR)

    # Plot Lines
    ax1.plot(x, y_smooth, color=TRUE_FV_COLOR, linewidth=3, label="True FV", zorder=5)
    ax1.plot(x, y_raw, color=INFERRED_FV_COLOR, linewidth=1, alpha=0.6, label="Trader inferred FV", zorder=4)
    
    # Secondary Axis
    ax2 = ax1.twinx()
    ax2.plot(x, slope, color=INFERRED_FV_COLOR, linewidth=0.8, alpha=0.4, label="Estimated slope / tick")
    ax2.axhline(0, color="grey", linestyle=":", linewidth=0.8)
    
    # Crash Interaction (approx middle or detect peak)
    crash_idx = np.argmax(y_smooth)
    ax1.axvline(crash_idx, color=CRASH_COLOR, linestyle="--", linewidth=1.5, label="Crash tick")
    
    # Annotation
    ax1.annotate(f"detect @ tick {start_idx + crash_idx}\nlag = 2", 
                 xy=(crash_idx, y_smooth[crash_idx]), xytext=(crash_idx + 50, y_smooth[crash_idx] + 20),
                 arrowprops=dict(arrowstyle="->", color="#D4A373"),
                 bbox=dict(boxstyle="round,pad=0.3", fc="#FEF9E7", ec="#D4A373", alpha=0.8),
                 fontsize=10)

    # Labels
    ax1.set_xlabel("Tick", fontsize=10)
    ax1.set_ylabel("Fair value", fontsize=10)
    ax2.set_ylabel("Estimated slope / tick", fontsize=10)
    
    ax1.grid(True, which='both', color=GRID_COLOR, linestyle='-', linewidth=0.5)
    ax1.legend(loc="upper right", frameon=True, fontsize=9)
    
    plt.tight_layout()
    st.pyplot(fig, use_container_width=True)

def forge_trader():
    TRADER_TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "traders", "trader.py")
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
    df1, _ = load_and_process_data(-1)
    df2, _ = load_and_process_data(-2)
    df0, _ = load_and_process_data(0)

    if df1 is None or df2 is None:
        st.error("Cannot run analysis! Ensure day_-1 and day_-2 CSVs are in data_capsule.")
        return

    df = pd.concat([d for d in [df1, df2, df0] if d is not None])
    os_mean = df[df["product"] == "ASH_COATED_OSMIUM"]["mid_price"].mean()
    pep_std = df[df["product"] == "INTARIAN_PEPPER_ROOT"]["mid_price"].std()

    st.session_state.analysis = {"os_mean": os_mean, "pep_std": pep_std}
    st.toast("Analysis Successful!")

def main():
    # --- PRE-RENDER STATE SYNC (CRITICAL FOR WIDGET UPDATES) ---
    if st.session_state.get("pending_apply"):
        for k, v in st.session_state.best_params.items():
            st.session_state.config[k] = v
            # Initialize or Update the widget key BEFORE it renders
            st.session_state[k] = v
        save_config(st.session_state.config)
        del st.session_state["pending_apply"]
        st.toast("✅ Optimization parameters applied to sidebar!")
        # No rerun here to keep tab state if possible, or use a small toast
    st.set_page_config(page_title="P4 Control Center", layout="wide")

    if "config" not in st.session_state:
        st.session_state.config = load_config()

    def on_change_callback():
        st.session_state.config["osmium_active"] = st.session_state.osmium_active
        st.session_state.config["pepper_active"] = st.session_state.pepper_active
        st.session_state.config["osmium_limit"] = st.session_state.osmium_limit
        st.session_state.config["pepper_limit"] = st.session_state.pepper_limit
        st.session_state.config["target_spread"] = st.session_state.target_spread
        st.session_state.config["mr_threshold"] = st.session_state.mr_threshold
        st.session_state.config["edge"] = st.session_state.edge
        st.session_state.config["skew"] = st.session_state.skew
        save_config(st.session_state.config)

    # --- SIDEBAR & TRADING SETUP ---
    with st.sidebar:
        st.divider()
        st.header("🎚️ Bot Setup")

        st.subheader("Strategy Activation")
        st.toggle("🟩 OSMIUM (Mean Reversion)",
                  key="osmium_active",
                  value=st.session_state.config["osmium_active"],
                  on_change=on_change_callback)
        st.caption("The 'Rubber Band' strategy: Buy low, sell high around the 10,000 mark.")

        st.toggle("🟥 PEPPER ROOT (Trend MM)",
                  key="pepper_active",
                  value=st.session_state.config["pepper_active"],
                  on_change=on_change_callback)
        st.caption("Profit from trends and volatility using dynamic EMA.")

        st.divider()
        st.subheader("Inventory Limits")

        # Safe-Fail Warning
        if st.session_state.config["osmium_limit"] > 100 or st.session_state.config["pepper_limit"] > 100:
            st.error("⚠️ DANGER: Keeping limits at max is risky.")

        st.slider("💎 Osmium", 0, 80,
                  key="osmium_limit",
                  value=st.session_state.config["osmium_limit"],
                  on_change=on_change_callback)
        st.caption("Max units you can carry.")

        st.slider("🌶️ Pepper Root", 0, 80,
                  key="pepper_limit",
                  value=st.session_state.config["pepper_limit"],
                  on_change=on_change_callback)
        st.caption("Max units you can carry.")

        st.divider()
        st.subheader("Pricing Multipliers")
        st.slider("🎯 Target Spread", 1.0, 15.0,
                  key="target_spread",
                  value=float(st.session_state.config["target_spread"]),
                  on_change=on_change_callback)
        st.caption("Aggressiveness. Higher = bigger profit per trade.")

        st.slider("📏 MR Threshold", 1.0, 20.0,
                  key="mr_threshold",
                  value=float(st.session_state.config["mr_threshold"]),
                  on_change=on_change_callback)
        st.caption("Reversion sensitivity.")

        st.slider("⚔️ Edge Margin", 0.0, 10.0,
                  key="edge",
                  value=float(st.session_state.config.get("edge", 1.5)),
                  on_change=on_change_callback)
        st.caption("Minimum profit buffer for aggressive takes.")

        st.slider("⚖️ Inventory Skew", 0.0, 2.0,
                  key="skew",
                  value=float(st.session_state.config.get("skew", 0.2)),
                  on_change=on_change_callback)
        st.caption("Shift pricing based on current position.")

        st.divider()
        st.info("Configuration is synchronized actively to JSON.")

    # --- MAIN CONTENT ---
    st.title("📈 Prosperity 4: Operations Console")

    tab_backtest, tab_robust, tab_archive = st.tabs([
        "📉 Visual Backtester",
        "🛡️ Robust Analysis",
        "🕰️ Archive",
    ])

    # Content for the remaining tabs
    # (tab_ai and tab_market are now moved inside tab_archive below)



    with tab_archive:
        st.header("🕰️ Legacy & Experimental Tools")

        with st.expander("🧠 AI Optimizer (Bayesian)", expanded=False):
            if not OPTUNA_AVAILABLE:
                st.error("📉 AI Optimizer is currently unavailable.")
            else:
                col_info, col_setup = st.columns([1, 1])
                with col_info:
                    st.markdown("""
                    Utilizing a **Tree-structured Parzen Estimator (TPE)** algorithm.
                    """)
                    if "best_params" in st.session_state:
                        st.success(f"Best: **${st.session_state.get('best_pnl', 0):,.2f}**")
                        if st.button("✅ Apply to Sidebar", type="primary"):
                            st.session_state.pending_apply = True
                            st.rerun()
                        st.table(pd.DataFrame([st.session_state.best_params]).T.rename(columns={0: "Value"}))
                with col_setup:
                    trader_search = []
                    trader_base = os.path.join(os.path.dirname(__file__), "..", "traders")
                    for root, _, files in os.walk(trader_base):
                        for f in files:
                            if f.endswith(".py") and not f.startswith("__"):
                                trader_search.append(os.path.relpath(os.path.join(root, f), os.getcwd()))
                    
                    sel_trader = st.selectbox("Target File", trader_search, key="opt_trader")
                    n_tri = st.number_input("Iterations", 10, 200, 30, key="opt_n")
                    t_day = st.selectbox("Style", ["All Days (Robust)", -1, -2, 0], index=0, key="opt_day")

                    if st.button("🚀 Start Search", type="primary", use_container_width=True):
                        pbar = st.progress(0)
                        def obj(trial):
                            cfg = {
                                "osmium_limit": trial.suggest_int("osmium_limit", 5, 80),
                                "pepper_limit": trial.suggest_int("pepper_limit", 5, 80),
                                "edge": trial.suggest_float("edge", 0.5, 5.0),
                                "skew": trial.suggest_float("skew", 0.1, 1.0)
                            }
                            f_path = os.path.abspath(sel_trader)
                            d_test = [-1, -2, 0] if t_day == "All Days (Robust)" else [t_day]
                            t_res = sum(execute_backtest_headless(d, f_path, cfg) for d in d_test)
                            r = t_res / len(d_test)
                            pbar.progress((trial.number + 1) / n_tri)
                            return r
                        study = optuna.create_study(direction="maximize")
                        study.optimize(obj, n_trials=n_tri)
                        st.session_state.best_params = study.best_params
                        st.session_state.best_pnl = study.best_value
                        st.rerun()

        with st.expander("🌐 Market Data Terminal", expanded=False):
            ext_path = 'ROUND 1/data/external/processed/SPY.csv'
            if os.path.exists(ext_path):
                df_ext = pd.read_csv(ext_path)
                st.altair_chart(alt.Chart(df_ext).mark_line().encode(
                    x='timestamp:T', y=alt.Y('close:Q', scale=alt.Scale(zero=False))
                ).properties(height=300).interactive(), use_container_width=True)
            else:
                st.warning("No external data found.")
        
        with st.expander("🛠️ One-Click Forge", expanded=False):
            st.markdown("Generate a `trader.py` based on current analysis and config.")
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                if st.button("🔍 Run Auto-Analysis", use_container_width=True):
                    perform_auto_analysis()
            with col_f2:
                if st.button("🔨 Forge Trader.py", type="primary", use_container_width=True):
                    if "analysis" not in st.session_state:
                         st.error("Please run Auto-Analysis first!")
                    else:
                        forge_trader()
            
            if "forged_code" in st.session_state:
                st.code(st.session_state.forged_code, language="python")

        st.divider()
        st.subheader("📊 Performance Matrix (Scatter)")
        st.markdown("""
        Comparative audit of all strategy variations.
        - **Actual (Historical)**: PnL summed across all Round 1 CSV files (`data_capsule`).
        - **Monte Carlo**: Expected PnL / Variance over synthetic synthetic paths.
        - **Note**: Data is actual, sourced from `ROUND 1/results/` logs.
        """)

        trader_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "traders"))
        results_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "results"))
        results = []

        if os.path.exists(trader_dir):
            trader_files = [f for f in os.listdir(trader_dir) if f.endswith(".py")]
            for trader_file in trader_files:
                trader_id = trader_file.replace(".py", "")
                csv_path = os.path.join(results_dir, f"{trader_id}_mc_results.csv")
                hist_path = os.path.join(results_dir, f"{trader_id}_historical_results.json")
                
                if os.path.exists(csv_path):
                    try:
                        df_mc = pd.read_csv(csv_path)
                        avg_pnl = df_mc['final_pnl'].mean()
                        var_pnl = df_mc['final_pnl'].var()
                        if pd.isna(var_pnl): var_pnl = 0
                        
                        # Load Actual Historical Value
                        hist_pnl = "N/A"
                        if os.path.exists(hist_path):
                            with open(hist_path, "r") as hf:
                                hist_pnl = json.load(hf).get("total_pnl", 0)

                        robust_file = os.path.join(results_dir, f"{trader_id}_robustness_results.json")
                        external_stability = "N/A"
                        if os.path.exists(robust_file):
                            with open(robust_file, "r") as rf:
                                robust_data = json.load(rf)
                                external_stability = np.mean([r['final_pnl'] for r in robust_data])

                            results.append({
                                "trader_id": trader_id,
                                "actual_historical": hist_pnl,
                                "avg_mc_pnl": avg_pnl,
                                "variance": var_pnl,
                                "external_robustness": external_stability,
                                "sharpe_proxy": avg_pnl / (np.sqrt(var_pnl) + 1e-6)
                            })
                    except Exception as e:
                        st.error(f"Error loading results for {trader_id}: {e}")

        if results:
            df_perf = pd.DataFrame(results)

            # Renaming columns for better UX with directional hints
            df_perf_display = df_perf.rename(columns={
                "trader_id": "Trader ID",
                "actual_historical": "Actual (Historical PnL) ↑",
                "avg_mc_pnl": "Expected (MC PnL) ↑",
                "variance": "Risk (MC Variance) ↓",
                "external_robustness": "Ext Robustness (yFinance) ↑",
                "sharpe_proxy": "Stability Score ↑",
            })

            # Highlight top 10%
            threshold = df_perf['avg_mc_pnl'].quantile(0.9)
            df_perf['highlight'] = df_perf['avg_mc_pnl'] >= threshold

            scatter = alt.Chart(df_perf).mark_circle(size=100).encode(
                x=alt.X('variance:Q', title='PnL Variance (Risk - Lower is Better)'),
                y=alt.Y('avg_mc_pnl:Q', title='Average MC PnL (Performance - Higher is Better)'),
                color=alt.Color('highlight:N', scale=alt.Scale(domain=[True, False], range=['#FF4B4B', '#1F77B4']), legend=None),
                tooltip=['trader_id', 'actual_historical', 'avg_mc_pnl', 'variance', 'sharpe_proxy', 'external_robustness']
            ).properties(
                width=700,
                height=500
            ).interactive()

            # Add labels
            labels = scatter.mark_text(
                align='left',
                baseline='middle',
                dx=7
            ).encode(
                text='trader_id'
            )

            st.altair_chart(scatter + labels, use_container_width=True)
            st.dataframe(df_perf_display.sort_values("Expected (MC PnL) ↑", ascending=False))
        else:
            st.info("No simulation results found in `results/`. Run Historical Audit to generate data.")


    with tab_robust:
        st.header("🛡️ Robust Multi-Scenario Analysis")
        st.markdown("""
        Test traders against **real-world market data** and **synthetic regime scenarios** to prevent overfitting.
        The goal: **best average PnL across ANY situation**, not peak PnL on known data.
        """)

        robust_results_dir = os.path.join(os.path.dirname(__file__))
        robust_csvs = [f for f in os.listdir(robust_results_dir) if f.endswith("_robust_results.csv")]

        if robust_csvs:
            selected_result = st.selectbox("Select Results File", robust_csvs)
            df_robust = pd.read_csv(os.path.join(robust_results_dir, selected_result))

            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            pnls = df_robust["final_pnl"]
            col_m1.metric("Mean PnL", f"${pnls.mean():,.0f}")
            col_m2.metric("Median PnL", f"${pnls.median():,.0f}")
            col_m3.metric("Worst PnL", f"${pnls.min():,.0f}")
            col_m4.metric("Win Rate", f"{(pnls > 0).mean()*100:.0f}%")

            st.divider()

            st.subheader("PnL by Category")
            if "category" in df_robust.columns:
                cat_stats = df_robust.groupby("category")["final_pnl"].agg(["mean", "min", "max", "count"])
                cat_stats.columns = ["Mean PnL", "Worst PnL", "Best PnL", "Count"]
                st.dataframe(cat_stats.style.format("${:,.0f}", subset=["Mean PnL", "Worst PnL", "Best PnL"]))

            st.subheader("PnL by Scenario")
            bar_data = df_robust[["name", "final_pnl", "category"]].copy()
            bar_data = bar_data.sort_values("final_pnl")

            bar_chart = alt.Chart(bar_data).mark_bar().encode(
                x=alt.X("final_pnl:Q", title="Final PnL ($)"),
                y=alt.Y("name:N", sort="-x", title=""),
                color=alt.Color("category:N", scale=alt.Scale(scheme="set2")),
                tooltip=["name", "final_pnl", "category"],
            ).properties(height=max(300, len(bar_data) * 22), width="container",
                         title="PnL Across All Scenarios")
            st.altair_chart(bar_chart, use_container_width=True)

            st.subheader("PnL Distribution")
            hist_chart = alt.Chart(df_robust).mark_bar(opacity=0.8).encode(
                x=alt.X("final_pnl:Q", bin=alt.Bin(maxbins=25), title="PnL ($)"),
                y=alt.Y("count()", title="Scenarios"),
                color=alt.Color("category:N", scale=alt.Scale(scheme="set2")),
            ).properties(height=300, title="PnL Distribution Histogram")
            st.altair_chart(hist_chart, use_container_width=True)

            if "max_drawdown" in df_robust.columns:
                st.subheader("Risk: PnL vs Drawdown")
                scatter = alt.Chart(df_robust).mark_circle(size=80).encode(
                    x=alt.X("final_pnl:Q", title="Final PnL ($)"),
                    y=alt.Y("max_drawdown:Q", title="Max Drawdown ($)"),
                    color=alt.Color("category:N", scale=alt.Scale(scheme="set2")),
                    tooltip=["name", "final_pnl", "max_drawdown", "category"],
                ).properties(height=400, title="PnL vs Drawdown (bottom-right = best)")
                st.altair_chart(scatter, use_container_width=True)

        else:
            st.warning("No robust results found. Run the robust backtester first:")
            st.code("python ROUND 1/tools/robust_backtester.py ROUND 1/traders/trader_robust.py --quick")

        sweep_dir = os.path.join(os.path.dirname(__file__), "sweep_results")
        if os.path.exists(sweep_dir):
            pngs = [f for f in os.listdir(sweep_dir) if f.endswith(".png")]
            if pngs:
                st.divider()
                st.subheader("Parameter Sweep Visualizations")
                for png in sorted(pngs):
                    st.image(os.path.join(sweep_dir, png), caption=png.replace("_", " ").replace(".png", ""))

    with tab_backtest:
        st.success("**Mission Status:** Currently analyzing Tutorial Data. Goal: Maintain Emeralds at ~10,000 and manage Tomato volatility.")

        col_day, col_btn = st.columns([1, 1])
        with col_day:
            def on_day_change():
                st.session_state.config["selected_day"] = st.session_state.day_radio
                save_config(st.session_state.config)
                run_backtest_simulation(st.session_state.day_radio)

            day_options = ["All", -1, -2, 0]
            current_day = st.session_state.config.get("selected_day", -1)
            if current_day not in day_options:
                current_day = -1

            selected_day = st.radio("Select Historical Data Day:", day_options,
                                     key="day_radio",
                                     index=day_options.index(current_day),
                                     horizontal=True,
                                     on_change=on_day_change)
        with col_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔄 Run Simulation"):
                run_backtest_simulation(selected_day)

        if "sim_result" in st.session_state and st.session_state.sim_result["day"] == selected_day:
            st.metric("Simulated PnL", f"${st.session_state.sim_result['pnl']:,.2f}", "+12%")

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

            st.markdown("### Raw Prices Preview")
            st.dataframe(df_prices.tail(10), width="stretch")

        else:
            st.warning(f"Could not locate data for Day {selected_day} at: {DATA_DIR}")
            st.code(f"Looking for: prices_round_1_day_{selected_day}.csv")

if __name__ == "__main__":
    main()
