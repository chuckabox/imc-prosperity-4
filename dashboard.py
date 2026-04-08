import streamlit as st
import json
import os
import pandas as pd
import altair as alt

CONFIG_FILE = "config.json"
DATA_DIR = "data_capsule"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            try:
                return json.load(f)
            except:
                pass
    return {
        "emerald_active": True,
        "tomato_active": True,
        "emerald_limit": 20,
        "tomato_limit": 20,
        "target_spread": 2,
        "mr_threshold": 2
    }

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def emergency_stop():
    st.session_state.config["emerald_limit"] = 0
    st.session_state.config["tomato_limit"] = 0
    st.session_state.config["emerald_active"] = False
    st.session_state.config["tomato_active"] = False
    save_config(st.session_state.config)

def run_backtest_simulation(day):
    # Dummy simulation
    st.toast(f"Running simulation against Day {day}...")
    # Add a mock metric to state
    st.session_state.sim_result = {"pnl": 1205.50, "day": day}

@st.cache_data
def load_and_process_data(day):
    prices_file = os.path.join(DATA_DIR, f"prices_round_0_day_str.csv".replace("str", str(day)))
    trades_file = os.path.join(DATA_DIR, f"trades_round_0_day_str.csv".replace("str", str(day)))
    
    if not os.path.exists(prices_file):
        return None, None
        
    df_prices = pd.read_csv(prices_file, sep=";")
    df_prices["mid_price"] = (df_prices["bid_price_1"] + df_prices["ask_price_1"]) / 2.0
    
    if "timestamp" in df_prices.columns:
        # Group by 100 intervals (already 100 increments usually, but just in case)
        df_prices["timestamp"] = (df_prices["timestamp"] // 100) * 100
        df_prices = df_prices.groupby(["timestamp", "product"]).mean(numeric_only=True).reset_index()
    
    df_trades = None
    if os.path.exists(trades_file):
        df_trades = pd.read_csv(trades_file, sep=";")
        
    return df_prices, df_trades

def render_chart(df_prices, df_trades, product, color, show_mean=False):
    # Filter by product
    df_p = df_prices[df_prices["product"] == product].copy()
    if df_p.empty:
        st.warning(f"No data for {product}")
        return
        
    # Line chart for mid_price
    line = alt.Chart(df_p).mark_line(color=color).encode(
        x='timestamp:Q',
        y=alt.Y('mid_price:Q', scale=alt.Scale(zero=False), title="Price"),
        tooltip=['timestamp', 'mid_price']
    )
    
    # Area chart for spread
    band = alt.Chart(df_p).mark_area(opacity=0.3, color=color).encode(
        x='timestamp:Q',
        y='bid_price_1:Q',
        y2='ask_price_1:Q'
    )
    
    layers = [band, line]
    
    # Optional Mean line (Fair Value)
    if show_mean:
        mean_val = df_p["mid_price"].mean()
        mean_line = alt.Chart(pd.DataFrame({'y': [mean_val]})).mark_rule(color='#e67e22', strokeDash=[5, 5], strokeWidth=2).encode(
            y='y:Q'
        )
        layers.append(mean_line)
        
    # Optional Scatter overlay for trades
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
    
    st.altair_chart(chart, use_container_width=True)
    return df_p

def main():
    st.set_page_config(page_title="P4 Control Center", layout="wide")
    
    if "config" not in st.session_state:
        st.session_state.config = load_config()
        
    def on_change_callback():
        st.session_state.config["emerald_active"] = st.session_state.emerald_active
        st.session_state.config["tomato_active"] = st.session_state.tomato_active
        st.session_state.config["emerald_limit"] = st.session_state.emerald_limit
        st.session_state.config["tomato_limit"] = st.session_state.tomato_limit
        st.session_state.config["target_spread"] = st.session_state.target_spread
        st.session_state.config["mr_threshold"] = st.session_state.mr_threshold
        save_config(st.session_state.config)

    # --- SIDEBAR CONFIG ---
    with st.sidebar:
        st.header("🎚️ Bot Setup (Config.json)")
        
        st.button("🚨 EMERGENCY STOP 🚨", on_click=emergency_stop, type="primary", use_container_width=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        st.subheader("Strategy Activation")
        st.toggle("🟩 EMERALDS (Mean Reversion)", key="emerald_active", value=st.session_state.config["emerald_active"], on_change=on_change_callback)
        st.toggle("🟥 TOMATOES (Market Making)", key="tomato_active", value=st.session_state.config["tomato_active"], on_change=on_change_callback)
            
        st.divider()
        st.subheader("Inventory Limits")
        st.slider("💎 Emeralds", 0, 20, key="emerald_limit", value=st.session_state.config["emerald_limit"], on_change=on_change_callback)
        st.slider("🍅 Tomatoes", 0, 20, key="tomato_limit", value=st.session_state.config["tomato_limit"], on_change=on_change_callback)
        
        st.divider()
        st.subheader("Pricing Multipliers")
        st.slider("🎯 Target Spread", 1, 10, key="target_spread", value=st.session_state.config["target_spread"], on_change=on_change_callback)
        st.slider("📏 MR Threshold", 1, 20, key="mr_threshold", value=st.session_state.config["mr_threshold"], on_change=on_change_callback)
        
        st.divider()
        st.info("Configuration is synchronized actively to JSON.")
    
    # --- MAIN CONTENT ---
    st.title("📈 Prosperity 4: Tutorial Backtester")
    
    st.success("**Mission Status:** Currently analyzing Tutorial Data. Goal: Maintain Emeralds at ~10,000 and manage Tomato volatility.")
    
    col_day, col_btn = st.columns([1, 1])
    with col_day:
        selected_day = st.radio("Select Historical Data Day:", [-1, -2], horizontal=True)
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button(f"▶️ Backtest Against Selected Day ( {selected_day} )", type="primary"):
            run_backtest_simulation(selected_day)
            
    if "sim_result" in st.session_state and st.session_state.sim_result["day"] == selected_day:
        st.metric("Simulated PnL", f"${st.session_state.sim_result['pnl']:,.2f}", "+12%")

    st.markdown("---")
    
    df_prices, df_trades = load_and_process_data(selected_day)
    
    if df_prices is not None:
        st.subheader(f"📊 Market Reconstruction (Day {selected_day})")
        
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            df_em = render_chart(df_prices, df_trades, "EMERALDS", "#2ecc71", show_mean=True)
            if df_em is not None:
                em_mean = df_em["mid_price"].mean()
                if abs(em_mean - 10000) < 5:
                    st.info(f"**Fair Value Found:** Emerald average is extremely stable at {em_mean:.2f}. Anchoring to 10,000 is optimal.")
                    
        with col_c2:
            render_chart(df_prices, df_trades, "TOMATOES", "#e74c3c", show_mean=False)
            
        st.markdown("### Raw Prices Preview")
        st.dataframe(df_prices.tail(10), use_container_width=True)
        
    else:
        st.warning(f"Could not locate data for Day {selected_day} in data_capsule/.")

if __name__ == "__main__":
    main()
