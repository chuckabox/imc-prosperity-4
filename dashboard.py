import streamlit as st

def render_hints():
    with st.sidebar.expander("🚀 DEEP SPACE MISSION HINTS", expanded=True):
        st.markdown("### Mission Briefing & Strategy Hints")
        
        st.info("**💡 R1 STRATEGY: Market Making (MM)**\n\nFocus on the 'Fixed-Fair-Value' asset (like Emeralds in P3). Its price is stable; focus on capturing the spread. It's the most consistent way to make money early.")
        
        st.warning("**📉 NOISY ASSETS (Mean Reversion & Skew)**\n\nRound 1 usually has a volatile asset (like Squid Ink). Keep positions small (max **25%** of limit) to avoid liquidation. If the spread is too wide, just walk away.\n\n* **Mean Reversion**: If a space-themed commodity spikes 10% without news, it's likely 'overbought'. Sell the peak.\n* **Inventory Skew**: Adjust prices based on inventory. If you hold +18 (limit 20), lower your Buy/Sell prices to encourage buying and rebalance risk.")
        
        st.success("**🕵️ THE 'INSIDER' ALPHA**\n\nIn Round 5, specific Trader IDs are insiders seeded by IMC. Identifying a bot that consistently trades right before a price move is the secret to a top-100 finish. If we find them, we mimic their trades at max position.")
        
        st.error("**⚠️ POSITION LIMITS & SAFETY CHECK**\n\nAlways verify `position_limit` before placing an order. Never trade at 100% capacity. Leave a 2-unit buffer.")
        
        st.markdown("---")
        st.markdown("**🎓 Pro-Tip for UQ Students:**\n\nKeep an eye on the UQ Fintech Society or UQCS Discord! Usually, someone creates a shared visualizer for the logs that is way better than the default one.")

def main():
    st.set_page_config(page_title="Algorithmic Trading Dashboard", layout="wide")
    st.title("📈 Trading Performance Dashboard")
    
    # Render the mission hints in the sidebar
    render_hints()
    
    # Placeholder for main dashboard content
    st.write("### Main PnL Graphs and Metrics")
    st.write("_Your main profit and loss visualizations, trade logs, and inventory charts will go here..._")

if __name__ == "__main__":
    main()
