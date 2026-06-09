import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os

st.set_page_config(layout="wide", page_title="IMC Prosperity 4 - Round 3 Viewer")
st.title("Round 3 Data & Alpha Comparison Tool")

@st.cache_data
def load_data():
    day0 = pd.read_csv('ROUND 3/data_capsule/prices_round_3_day_0.csv', sep=';')
    day1 = pd.read_csv('ROUND 3/data_capsule/prices_round_3_day_1.csv', sep=';')
    day2 = pd.read_csv('ROUND 3/data_capsule/prices_round_3_day_2.csv', sep=';')
    return day0, day1, day2

day0, day1, day2 = load_data()

days = {"Day 0": day0, "Day 1": day1, "Day 2": day2}

# Sidebar Selectors
selected_day = st.sidebar.selectbox("Select Day", list(days.keys()))
df = days[selected_day]

products = df['product'].unique()
st.sidebar.markdown("---")
st.sidebar.subheader("Select Products to Compare")
selected_products = st.sidebar.multiselect("Products:", products, default=["VELVETFRUIT_EXTRACT", "HYDROGEL_PACK"])

st.sidebar.markdown("---")
st.sidebar.subheader("Time Range Filter")
min_ts, max_ts = int(df['timestamp'].min()), int(df['timestamp'].max())
time_range = st.sidebar.slider("Timestamp Range", min_value=min_ts, max_value=max_ts, value=(min_ts, max_ts), step=100)

filtered_df = df[(df['timestamp'] >= time_range[0]) & (df['timestamp'] <= time_range[1])]

# 1. Main Price Plot
st.header("Price Comparison")
if selected_products:
    fig = go.Figure()
    for prod in selected_products:
        prod_data = filtered_df[filtered_df['product'] == prod]
        fig.add_trace(go.Scatter(x=prod_data['timestamp'], y=prod_data['mid_price'], mode='lines', name=prod))
    fig.update_layout(height=500, hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

# 2. True Alpha: Extra Premium (Time Value) Calculator
st.header("Option 'Extra Premium' Calculator")
st.markdown("Use this to visualize the deviation of Market Option Prices from Intrinsic Value.")

vfe_data = filtered_df[filtered_df['product'] == 'VELVETFRUIT_EXTRACT'].set_index('timestamp')

option_strikes = [5000, 5100, 5200, 5300, 5400, 5500]
selected_options = st.multiselect("Select Option Chains to calculate Extra Premium:", option_strikes, default=[5200, 5300])

if selected_options:
    fig2 = go.Figure()
    for strike in selected_options:
        opt_str = f"VEV_{strike}"
        opt_data = filtered_df[filtered_df['product'] == opt_str].set_index('timestamp')
        
        # Merge to ensure timestamps align
        merged = pd.DataFrame({'VFE': vfe_data['mid_price'], 'OPT': opt_data['mid_price']}).dropna()
        
        # Calculate Intrinsic and Extra Premium
        intrinsic = (merged['VFE'] - strike).clip(lower=0)
        premium = merged['OPT'] - intrinsic
        
        fig2.add_trace(go.Scatter(x=merged.index, y=premium, mode='lines', name=f'{opt_str} Premium'))
    
    fig2.update_layout(height=400, hovermode="x unified", title="Extrinsic Value (Market Price - Intrinsic Value)")
    st.plotly_chart(fig2, use_container_width=True)

# 3. Market Depth Viewer
st.header("Order Book Snapshots")
snap_ts = st.selectbox("Select Timestamp for Depth Snapshot", filtered_df['timestamp'].unique())
snap_df = filtered_df[filtered_df['timestamp'] == snap_ts]

st.dataframe(snap_df[['product', 'bid_volume_3', 'bid_price_3', 'bid_volume_2', 'bid_price_2', 'bid_volume_1', 'bid_price_1',
                     'ask_price_1', 'ask_volume_1', 'ask_price_2', 'ask_volume_2', 'ask_price_3', 'ask_volume_3', 'mid_price']])
