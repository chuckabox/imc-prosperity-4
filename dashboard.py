import streamlit as st
import json
import os

CONFIG_FILE = "config.json"

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

def main():
    st.set_page_config(page_title="P4 Control Center", layout="wide")
    st.title("🎛️ P4 Interactive Control Center")
    
    if "config" not in st.session_state:
        st.session_state.config = load_config()
        
    def on_change_callback():
        # Update config dictionary from session state
        st.session_state.config["emerald_active"] = st.session_state.emerald_active
        st.session_state.config["tomato_active"] = st.session_state.tomato_active
        st.session_state.config["emerald_limit"] = st.session_state.emerald_limit
        st.session_state.config["tomato_limit"] = st.session_state.tomato_limit
        st.session_state.config["target_spread"] = st.session_state.target_spread
        st.session_state.config["mr_threshold"] = st.session_state.mr_threshold
        save_config(st.session_state.config)

    col_left, col_right = st.columns([1.2, 1.0], gap="large")
    
    with col_left:
        st.header("🎚️ Bot Parameters & Strategy Toggles")
        
        # Emergency Stop
        st.button("🚨 EMERGENCY STOP (KILL ALL TRADING) 🚨", on_click=emergency_stop, type="primary", use_container_width=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Strategy Toggles
        st.subheader("Strategy Activation")
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.toggle("🟩 Trade EMERALDS (Mean Reversion)", key="emerald_active", value=st.session_state.config["emerald_active"], on_change=on_change_callback)
        with col_t2:
            st.toggle("🟥 Trade TOMATOES (Market Making)", key="tomato_active", value=st.session_state.config["tomato_active"], on_change=on_change_callback)
            
        st.divider()
        
        st.subheader("Parameter Sliders")
        # Limits
        st.slider("💎 Emeralds Inventory Limit", min_value=0, max_value=20, key="emerald_limit", value=st.session_state.config["emerald_limit"], on_change=on_change_callback)
        st.slider("🍅 Tomatoes Inventory Limit", min_value=0, max_value=20, key="tomato_limit", value=st.session_state.config["tomato_limit"], on_change=on_change_callback)
        
        st.divider()
        # Strategy specifics
        st.slider("🎯 Target Spread (Ticks between Buy/Sell)", min_value=1, max_value=10, key="target_spread", value=st.session_state.config["target_spread"], on_change=on_change_callback)
        st.slider("📏 Mean Reversion Threshold (Price offset to Buy/Sell)", min_value=1, max_value=20, key="mr_threshold", value=st.session_state.config["mr_threshold"], on_change=on_change_callback)

    with col_right:
        st.header("📋 Mission Briefing: Tutorial & Round 1")
        
        st.info("**💎 The Emerald Rule (Mean Reversion)**\n\nEmeralds (TG02) have a fixed 'fair value' of 10,000.\n\n*Explanation:* If the price is 10,002, sell. If it's 9,998, buy. It is a 'stable' asset designed for simple market making.")
        
        st.warning("**🍅 The Tomato Trap (Volatility)**\n\nTomatoes (TG01) are a 'noisy' asset.\n\n*Explanation:* These don't have a fixed center. Use moving averages to find the trend, and don't hold them for too long or you'll get caught in a crash.")
        
        st.error("**⚖️ Inventory Skewing**\n\nDon't quote the same price on both sides if you're 'full'.\n\n*Explanation:* If you have +18/20 Emeralds, stop buying! Lower your buy price significantly and lower your sell price to get rid of your stock.")
        
        st.error("**📉 The 'Empty Book' Warning**\n\nAlways protect your bot from an empty order book.\n\n*Explanation:* If the order book is empty, your bot might crash. Always use `try/except` blocks or check if `order_depth.buy_orders` exists before trading.")
        
        st.markdown("---")
        st.code("Current Saved Config:\n" + json.dumps(st.session_state.config, indent=2))

if __name__ == "__main__":
    main()
