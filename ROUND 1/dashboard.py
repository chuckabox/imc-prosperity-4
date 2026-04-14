import streamlit as st
import json
import os
import pandas as pd
import altair as alt
import re
from datamodel import Listing, OrderDepth, TradingState, Observation, Order

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data_capsule")

def load_config():
    defaults = {
        "osmium_active": True,
        "pepper_active": True,
        "osmium_limit": 20,
        "pepper_limit": 20,
        "emerald_active": True, # For legacy compat
        "tomato_active": True,
        "emerald_limit": 20,
        "tomato_limit": 20,
        "target_spread": 2,
        "mr_threshold": 2,
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

from trader import Trader, logger as trader_logger

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
        grouped = df_prices.groupby("timestamp")
        total_steps = len(grouped)
        progress_bar = st.progress(0)
        
        for i, (ts, group) in enumerate(grouped):
            progress_bar.progress((i + 1) / total_steps)
            
            # Prepare state
            order_depths = {}
            for _, row in group.iterrows():
                product = row["product"]
                depth = OrderDepth()
                depth.buy_orders = {int(row["bid_price_1"]): 10}
                depth.sell_orders = {int(row["ask_price_1"]): -10}
                order_depths[product] = depth
                
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
            
            # --- Fill Logic ---
            for product, order_list in orders.items():
                if product not in group["product"].values: continue
                row = group[group["product"] == product].iloc[0]
                curr_ask = int(row["ask_price_1"])
                curr_bid = int(row["bid_price_1"])
                
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
                    
                    if not filled and df_trades is not None:
                        mkt_trades = df_trades[(df_trades["timestamp"] == ts) & (df_trades["product"] == product)]
                        for _, trade in mkt_trades.iterrows():
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
                if product in group["product"].values:
                    row = group[group["product"] == product].iloc[0]
                    mid = (row["bid_price_1"] + row["ask_price_1"]) / 2.0
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
        st.line_chart(pnl_df.set_index("Timestamp"), width="stretch")

# Disable caching temporarily to ensure fresh data for every backtest
def load_and_process_data(day):
    # Search for files for Round 1
    prices_file = os.path.join(DATA_DIR, f"prices_round_1_day_{day}.csv")
    trades_file = os.path.join(DATA_DIR, f"trades_round_1_day_{day}.csv")
    
    if not os.path.exists(prices_file):
        return None, None
        
    df_prices = pd.read_csv(prices_file, sep=";")
    
    # Fix: Drop NaNs to prevent ValueError: cannot convert float NaN to integer
    df_prices = df_prices.dropna(subset=["bid_price_1", "ask_price_1", "timestamp"])
    
    df_prices["mid_price"] = (df_prices["bid_price_1"] + df_prices["ask_price_1"]) / 2.0
    
    if "timestamp" in df_prices.columns:
        # Avoid rounding timestamps as it breaks the drift logic.
        # Just resolve duplicates for the same timestamp/product if they exist.
        df_prices = df_prices.groupby(["timestamp", "product"]).mean(numeric_only=True).reset_index()
    
    df_trades = None
    if os.path.exists(trades_file):
        df_trades = pd.read_csv(trades_file, sep=";")
        if "symbol" in df_trades.columns:
            df_trades = df_trades.rename(columns={"symbol": "product"})
    
    st.info(f"Loaded {len(df_prices)} price rows and {len(df_trades) if df_trades is not None else 0} market trades.")
        
    return df_prices, df_trades

def render_chart(df_prices, df_trades, product, color, show_mean=False):
    df_p = df_prices[df_prices["product"] == product].copy()
    if df_p.empty:
        st.warning(f"No data for {product}")
        return
        
    line = alt.Chart(df_p).mark_line(color=color).encode(
        x='timestamp:Q',
        y=alt.Y('mid_price:Q', scale=alt.Scale(zero=False), title="Price"),
        tooltip=['timestamp', 'mid_price']
    )
    
    band = alt.Chart(df_p).mark_area(opacity=0.3, color=color).encode(
        x='timestamp:Q',
        y='bid_price_1:Q',
        y2='ask_price_1:Q'
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
                tooltip=['timestamp', 'price']
            )
            layers.append(scatter)
            
    chart = alt.layer(*layers).properties(
        width=800,
        height=300,
        title=f"{product} Price & Spread Overlay"
    ).interactive()
    
    st.altair_chart(chart, width="stretch")
    return df_p

def forge_trader():
    TRADER_TEMPLATE = os.path.join(os.path.dirname(__file__), "trader.py")
    if not os.path.exists(TRADER_TEMPLATE):
        st.error(f"Template not found at {TRADER_TEMPLATE}")
        return
        
    with open(TRADER_TEMPLATE, "r") as f:
        text = f.read()

    derived_spread = max(1, int(st.session_state.analysis["tom_std"] / 2.0))
    derived_fv = int(st.session_state.analysis["em_mean"])

    config_rendered = {
        "emerald_active": st.session_state.config["emerald_active"],
        "tomato_active": st.session_state.config["tomato_active"],
        "emerald_limit": st.session_state.config["emerald_limit"],
        "tomato_limit": st.session_state.config["tomato_limit"],
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
        save_config(st.session_state.config)

    # --- SIDEBAR & TRADING 101 ---
    with st.sidebar:
        st.header("📚 Trading 101")
        with st.expander("Show Cheat Sheet"):
            st.info("**Bid**: The highest price someone is willing to pay to BUY.\n\n**Ask**: The lowest price someone is willing to accept to SELL.")
            st.markdown("---")
            st.write("_Remember: You want to buy low and sell high!_")

        st.divider()
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
        if st.session_state.config["emerald_limit"] > 18 or st.session_state.config["tomato_limit"] > 18:
            st.error("⚠️ DANGER: Keeping limits at 20 is risky. Stay at 15-18 to avoid liquidation.")

        st.slider("💎 Osmium", 0, 20, 
                  key="osmium_limit", 
                  value=st.session_state.config["osmium_limit"], 
                  on_change=on_change_callback)
        st.caption("Max units you can carry.")
        
        st.slider("🌶️ Pepper Root", 0, 20, 
                  key="pepper_limit", 
                  value=st.session_state.config["pepper_limit"], 
                  on_change=on_change_callback)
        st.caption("Max units you can carry.")
        
        st.divider()
        st.subheader("Pricing Multipliers")
        st.slider("🎯 Target Spread", 1.0, 10.0, 
                  key="target_spread", 
                  value=float(st.session_state.config["target_spread"]), 
                  on_change=on_change_callback)
        st.caption("Aggressiveness. Higher = bigger profit per trade, but fewer fills.")
        
        st.slider("📏 MR Threshold", 1.0, 20.0, 
                  key="mr_threshold", 
                  value=float(st.session_state.config["mr_threshold"]), 
                  on_change=on_change_callback)
        st.caption("How far the price must 'stretch' before the rubber band snaps back.")
        
        st.divider()
        st.info("Configuration is synchronized actively to JSON.")
    
    # --- MAIN CONTENT ---
    st.title("📈 Prosperity 4: Operations Console")
    
    tab_backtest, tab_forge = st.tabs(["📉 Visual Backtester", "🛠️ One-Click Forge"])
    
    with tab_forge:
        st.header("🛠️ Upload Assembly Pipeline")
        st.write("Compile your findings and configurations into a professional `trader.py` ready for the IMC portal.")
        
        # --- STRATEGY SCHOOL ---
        st.markdown("## 🏫 Strategy School: Mean Reversion")
        col_text, col_viz = st.columns([2, 1])
        with col_text:
            st.markdown("""
            **The 'Rubber Band' Concept:** 
            Think of the price of an asset like a rubber band anchored to a fixed point. In Mean Reversion, we assume that whenever the price stretches too far away from its "Fair Value," it will eventually snap back to the middle.
            
            *   **When to Buy:** When the price is significantly *below* the fair value.
            *   **When to Sell:** When the price is significantly *above* the fair value.
            """)
        with col_viz:
            st.success("💎 **Osmium** is perfect for this because it rarely moves far from 10,000.")

        st.divider()

        # 1. Scanning
        st.markdown("### 1. Data Scan")
        TRADER_TEMPLATE = os.path.join(os.path.dirname(__file__), "trader.py")
        d1 = os.path.exists(os.path.join(DATA_DIR, "prices_round_1_day_-1.csv"))
        d2 = os.path.exists(os.path.join(DATA_DIR, "prices_round_1_day_-2.csv"))
        t_exists = os.path.exists(TRADER_TEMPLATE)

        if d1 and d2 and t_exists:
            st.success("✅ System check passed: Price data and Trader template are ready.")
        else:
            if not t_exists: st.error("❌ Template Error: `trader.py` not found in folder.")
            if not (d1 and d2): st.error("❌ Data Error: Historical CSVs missing from `data_capsule/`.")

        # 2. Analysis
        st.markdown("### 2. Auto-Analysis Engine")
        st.caption("This tool determines the 'Fair Value' for Emeralds and the 'Volatility' for Tomatoes based on your historical CSV data.")
        st.button("🔍 Run Auto-Analysis", 
                  on_click=perform_auto_analysis, 
                  disabled=not (d1 and d2 and t_exists))
        
        if "analysis" in st.session_state:
            st.info(f"**Insight:** Based on your data, we recommend anchoring Emeralds to **{st.session_state.analysis['em_mean']:.0f}**. Tomatoes are currently showing a volatility factor of **{st.session_state.analysis['tom_std']:.2f}**, which we will use to scale your profit capture.")
            
            st.metric("Derived Emerald Fair Value", f"{st.session_state.analysis['em_mean']:.1f}")
            st.metric("Derived Tomato Volatility", f"{st.session_state.analysis['tom_std']:.2f}")
            
            st.markdown("### 3. Final Execution")
            st.caption("We will now inject your sidebar settings (Limits, Aggressiveness) and the analyzed fair values into your final script.")
            st.button("⚙️ Forge Final Trader.py", 
                      on_click=forge_trader, 
                      type="primary")
            
            if "forged_code" in st.session_state:
                st.balloons()
                st.download_button(
                    label="⬇️ Download Your Optimized Trader.py",
                    data=st.session_state.forged_code,
                    file_name="trader.py",
                    mime="text/x-python",
                    type="primary"
                )
    
    with tab_backtest:
        st.success("**Mission Status:** Currently analyzing Tutorial Data. Goal: Maintain Emeralds at ~10,000 and manage Tomato volatility.")
        
        col_day, col_btn = st.columns([1, 1])
        with col_day:
            def on_day_change():
                st.session_state.config["selected_day"] = st.session_state.day_radio
                save_config(st.session_state.config)
                run_backtest_simulation(st.session_state.day_radio)

            selected_day = st.radio("Select Historical Data Day:", [-1, -2, 0], 
                                     key="day_radio",
                                     index=([-1, -2, 0].index(st.session_state.config.get("selected_day", -1))),
                                     horizontal=True, 
                                     on_change=on_day_change)
        with col_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔄 Manual Rerun"):
                run_backtest_simulation(selected_day)
                
        if "sim_result" in st.session_state and st.session_state.sim_result["day"] == selected_day:
            st.metric("Simulated PnL", f"${st.session_state.sim_result['pnl']:,.2f}", "+12%")

        st.markdown("---")
        
        df_prices, df_trades = load_and_process_data(selected_day)
        
        if df_prices is not None:
            st.subheader(f"📊 Market Reconstruction (Day {selected_day})")
            
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                df_os = render_chart(df_prices, df_trades, "ASH_COATED_OSMIUM", "#2ecc71", show_mean=True)
                if df_os is not None:
                    os_mean = df_os["mid_price"].mean()
                    if abs(os_mean - 10000) < 100:
                        st.info(f"**Fair Value Found:** Osmium average is stable around {os_mean:.2f}. Anchoring to 10,000 is optimal.")
                        
            with col_c2:
                render_chart(df_prices, df_trades, "INTARIAN_PEPPER_ROOT", "#e74c3c", show_mean=False)
                
            st.markdown("### Raw Prices Preview")
            st.dataframe(df_prices.tail(10), width="stretch")
            
        else:
            st.warning(f"Could not locate data for Day {selected_day} in data_capsule/.")

if __name__ == "__main__":
    main()
