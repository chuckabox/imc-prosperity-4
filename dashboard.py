import streamlit as st

def render_safety_gauge():
    st.markdown("### 🚦 Position Safety Simulator")
    
    col1, col2 = st.columns(2)
    with col1:
        limit = st.number_input("Position Limit", min_value=1, value=20, step=1)
    with col2:
        current = st.number_input("Current Position", min_value=0, max_value=int(limit), value=10, step=1)
        
    ratio = current / limit
    pct = min(ratio * 100, 100)
    
    if ratio > 0.8:
        color = "#ff4b4b" # red for danger
        status_text = "🚨 CRITICAL: Approaching position limit!"
        st.error(status_text)
    elif ratio > 0.5:
        color = "#ffa421" # orange for warning
        status_text = "⚠️ WARNING: Moderate inventory level."
        st.warning(status_text)
    else:
        color = "#00c04b" # green for safe
        status_text = "✅ SAFE: Healthy inventory level."
        st.success(status_text)
        
    gauge_html = f"""
    <div style="background-color: rgba(255, 255, 255, 0.1); border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 5px; width: 100%; height: 30px; margin-top: 10px;">
      <div style="background-color: {color}; width: {pct}%; height: 100%; border-radius: 4px; text-align: center; color: white; line-height: 30px; font-weight: bold; transition: width 0.3s ease; text-shadow: 1px 1px 2px rgba(0,0,0,0.5);">
        {int(current)} / {int(limit)} ({pct:.1f}%)
      </div>
    </div>
    """
    st.markdown(gauge_html, unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)


def render_hints_tab():
    st.markdown("## Mission Briefing: Tutorial & Round 1")
    st.markdown("---")
    
    st.info("**💎 The Emerald Rule (Mean Reversion)**\n\nEmeralds (TG02) have a fixed 'fair value' of 10,000.\n\n*Explanation:* If the price is 10,002, sell. If it's 9,998, buy. It is a 'stable' asset designed for simple market making.")
    
    st.warning("**🍅 The Tomato Trap (Volatility)**\n\nTomatoes (TG01) are a 'noisy' asset.\n\n*Explanation:* These don't have a fixed center. Use moving averages to find the trend, and don't hold them for too long or you'll get caught in a crash.")
    
    st.error("**⚖️ Inventory Skewing**\n\nDon't quote the same price on both sides if you're 'full'.\n\n*Explanation:* If you have +18/20 Emeralds, stop buying! Lower your buy price significantly and lower your sell price to get rid of your stock.")
    
    st.error("**📉 The 'Empty Book' Warning**\n\nAlways protect your bot from an empty order book.\n\n*Explanation:* If the order book is empty, your bot might crash. Always use `try/except` blocks or check if `order_depth.buy_orders` exists before trading.")
    
    st.markdown("---")
    render_safety_gauge()

def main():
    st.set_page_config(page_title="Algorithmic Trading Dashboard", layout="wide")
    st.title("📈 Trading Performance Dashboard")
    
    # Create tabs for better organization
    tab_main, tab_hints = st.tabs(["📊 Main Dashboard", "💡 Strategy & Important Hints"])
    
    with tab_hints:
        render_hints_tab()
        
    with tab_main:
        st.write("### Main PnL Graphs and Metrics")
        st.write("_Your main profit and loss visualizations, trade logs, and inventory charts will go here..._")
        
        # We can still add some dummy content just to simulate what would be there
        with st.expander("Latest Trades Log", expanded=True):
            st.code("Timestamp  | Symbol   | Side | Price | Quantity\n10:04:23.1 | EMERALDS | BUY  | 9998  | 5\n10:04:24.5 | TOMATOES | SELL | 4502  | 2")

if __name__ == "__main__":
    main()
