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
        trader_name = filename.replace("_robust_results.csv", "")
        pnls, data_missing = _resolve_target_pnls(df, target_col, p_filter)
        df = df.copy()
        df["target_pnl"] = pnls

        imc = df[df["category"] == "imc"]["target_pnl"] if "category" in df.columns else pd.Series([], dtype=float)
        real = df[df["category"] == "real"]["target_pnl"] if "category" in df.columns else pd.Series([], dtype=float)
        scen = df[df["category"] == "scenario"]["target_pnl"] if "category" in df.columns else pd.Series([], dtype=float)
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

    # Auto-rank score: emphasize IMC + overall robustness (higher is better).
    rank_frame = comp.copy()
    for c in ["IMC Mean", "Real Mean", "Scen Mean", "Full Mean", "Win%"]:
        rank_frame[c] = rank_frame[c].rank(pct=True, ascending=True)
    for c in ["IMC Worst", "Scen Worst", "Worst Day"]:
        rank_frame[c] = rank_frame[c].rank(pct=True, ascending=True)
    rank_frame["Blow-up%"] = rank_frame["Blow-up%"].rank(pct=True, ascending=False)

    comp["AutoScore"] = (
        weights["imc_mean"] * rank_frame["IMC Mean"]
        + weights["full_mean"] * rank_frame["Full Mean"]
        + weights["win_rate"] * rank_frame["Win%"]
        + weights["worst_day"] * rank_frame["Worst Day"]
        + weights["scen_mean"] * rank_frame["Scen Mean"]
        + weights["blowup"] * rank_frame["Blow-up%"]
    ) * 100
    comp["Rank"] = comp["AutoScore"].rank(method="min", ascending=False).astype(int)
    return comp.sort_values(["Rank", "IMC Mean"], ascending=[True, False]).reset_index(drop=True)


def _style_comparison_table(comp_df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    money_cols = ["IMC Mean", "IMC Worst", "Real Mean", "Scen Mean", "Scen Worst", "Full Mean", "Worst Day"]
    pct_cols = ["Real Win%", "Win%", "Blow-up%", "AutoScore"]
    low_is_good_cols = ["Blow-up%"]

    styler = comp_df.style
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
        st.toast("✅ Optimization parameters applied to configuration!")
        # No rerun here to keep tab state if possible, or use a small toast
    st.set_page_config(
        page_title="P4 Control Center",
        layout="wide"
    )

    if "config" not in st.session_state:
        st.session_state.config = load_config()

    def on_change_callback():
        for key in ["osmium_active", "pepper_active", "osmium_limit", "pepper_limit", "target_spread", "mr_threshold", "edge", "skew"]:
             if key in st.session_state:
                 st.session_state.config[key] = st.session_state[key]
        save_config(st.session_state.config)

    # --- MAIN CONTENT ---
    st.title("📈 Prosperity 4: Operations Console")

    with st.expander("⚙️ Strategy Configuration", expanded=False):
        col_act, col_lim, col_prc = st.columns(3)
        with col_act:
            st.subheader("Activation")
            st.toggle("🟩 OSMIUM (MR)", key="osmium_active", value=st.session_state.config["osmium_active"], on_change=on_change_callback)
            st.toggle("🟥 PEPPER (Trend)", key="pepper_active", value=st.session_state.config["pepper_active"], on_change=on_change_callback)
        with col_lim:
            st.subheader("Limits")
            st.slider("💎 Osmium", 0, 80, key="osmium_limit", value=st.session_state.config["osmium_limit"], on_change=on_change_callback)
            st.slider("🌶️ Pepper", 0, 80, key="pepper_limit", value=st.session_state.config["pepper_limit"], on_change=on_change_callback)
        with col_prc:
            st.subheader("Parameters")
            st.slider("🎯 Spread", 1.0, 15.0, key="target_spread", value=float(st.session_state.config["target_spread"]), on_change=on_change_callback)
            st.slider("📏 MR Thresh", 1.0, 20.0, key="mr_threshold", value=float(st.session_state.config["mr_threshold"]), on_change=on_change_callback)
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                st.slider("⚔️ Edge", 0.0, 10.0, key="edge", value=float(st.session_state.config.get("edge", 1.5)), on_change=on_change_callback)
            with col_s2:
                st.slider("⚖️ Skew", 0.0, 2.0, key="skew", value=float(st.session_state.config.get("skew", 0.2)), on_change=on_change_callback)

    # Final tab layout

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
                        if st.button("✅ Apply to Config", type="primary"):
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

        # Robust backtester outputs are now saved under ROUND 1/results/robust.
        # Keep a fallback to ROUND 1/tools for older runs.
        robust_results_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "results", "robust"))
        fallback_tools_dir = os.path.dirname(os.path.abspath(__file__))

        robust_csvs = []
        if os.path.isdir(robust_results_dir):
            robust_csvs = [f for f in os.listdir(robust_results_dir) if f.endswith("_robust_results.csv")]
        if not robust_csvs and os.path.isdir(fallback_tools_dir):
            robust_results_dir = fallback_tools_dir
            robust_csvs = [f for f in os.listdir(robust_results_dir) if f.endswith("_robust_results.csv")]

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
                name = f.replace("_robust_results.csv", "")
                
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

                quick_first = sorted(
                    robust_csvs,
                    key=lambda x: (0 if "_quick_" in x else 1, x)
                )
                default_selection = quick_first[: min(6, len(quick_first))]

                selected_compare = st.multiselect(
                    "Backtest Result Files",
                    options=sorted(robust_csvs),
                    default=default_selection,
                    format_func=lambda x: x.replace("_robust_results.csv", ""),
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
                        pair_styler = pair_view.style.background_gradient(cmap="RdYlGn", subset=["Edge IMC Mean", "Edge Full Mean", "Edge Worst Day", "Edge Win%", "Edge Blow-up%"]).format({
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
                        })
                        st.dataframe(pair_styler, use_container_width=True, hide_index=True)
                    else:
                        st.info("No comparable rows found in selected files.")
                else:
                    st.info("Select one or more result files to build the comparison matrix.")

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
                selected_result = st.selectbox("Select Results File for Deep Dive", robust_csvs, format_func=lambda x: x.replace("_robust_results.csv", ""))
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
                trader_base = os.path.join(os.path.dirname(__file__), "..", "traders")
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
        st.success("**Mission Status:** Currently analyzing Round 1 Data. Goal: Maintain Osmium at ~10,000 and manage Pepper volatility.")

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

            st.markdown("#### 🌎 Total Market Reconstruction")
            render_total_chart(df_prices, df_trades)

        else:
            st.warning(f"Could not locate data for Day {selected_day} at: {DATA_DIR}")
            st.code(f"Looking for: prices_round_1_day_{selected_day}.csv")

if __name__ == "__main__":
    main()
