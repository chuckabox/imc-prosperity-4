from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st


st.set_page_config(layout="wide", page_title="Round 3 All Items Viewer")
st.title("Round 3: Per-Item Visualization Across All Days")


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data_capsule"
DAY_FILES = {
    0: DATA_DIR / "prices_round_3_day_0.csv",
    1: DATA_DIR / "prices_round_3_day_1.csv",
    2: DATA_DIR / "prices_round_3_day_2.csv",
}


@st.cache_data
def load_day(day: int) -> pd.DataFrame:
    df = pd.read_csv(DAY_FILES[day], sep=";")
    # Handle missing depth levels in a stable way for plotting.
    for col in (
        "bid_price_1",
        "ask_price_1",
        "bid_volume_1",
        "ask_volume_1",
        "mid_price",
    ):
        if col not in df.columns:
            df[col] = pd.NA
    df["spread_1"] = df["ask_price_1"] - df["bid_price_1"]
    return df


@st.cache_data
def load_all() -> Dict[int, pd.DataFrame]:
    return {day: load_day(day) for day in DAY_FILES}


def list_products(datasets: Dict[int, pd.DataFrame]) -> List[str]:
    products = set()
    for df in datasets.values():
        products.update(df["product"].unique().tolist())
    return sorted(products)


def product_summary_table(datasets: Dict[int, pd.DataFrame], product: str) -> pd.DataFrame:
    rows = []
    for day, df in datasets.items():
        sub = df[df["product"] == product]
        if sub.empty:
            continue
        rows.append(
            {
                "day": day,
                "rows": len(sub),
                "mid_mean": float(sub["mid_price"].mean()),
                "mid_std": float(sub["mid_price"].std(ddof=0)),
                "spread_mean": float(sub["spread_1"].mean()),
                "spread_p95": float(sub["spread_1"].quantile(0.95)),
                "top_bid_vol_mean": float(sub["bid_volume_1"].fillna(0).mean()),
                "top_ask_vol_mean": float(sub["ask_volume_1"].fillna(0).mean()),
            }
        )
    return pd.DataFrame(rows)


def render_product_all_days(
    datasets: Dict[int, pd.DataFrame],
    product: str,
    ts_min: int,
    ts_max: int,
    max_points_per_day: int,
) -> None:
    for day in sorted(datasets.keys()):
        sub = datasets[day]
        sub = sub[
            (sub["product"] == product)
            & (sub["timestamp"] >= ts_min)
            & (sub["timestamp"] <= ts_max)
        ]
        if sub.empty:
            continue
        if len(sub) > max_points_per_day:
            step = max(1, len(sub) // max_points_per_day)
            sub = sub.iloc[::step].copy()

        st.markdown(f"**Day {day}**")
        price_df = sub[["timestamp", "mid_price", "bid_price_1", "ask_price_1"]].set_index(
            "timestamp"
        )
        spread_df = sub[["timestamp", "spread_1"]].set_index("timestamp")

        c1, c2 = st.columns([3, 2])
        with c1:
            st.line_chart(price_df, use_container_width=True)
        with c2:
            st.line_chart(spread_df, use_container_width=True)


datasets = load_all()
products = list_products(datasets)

if not products:
    st.error("No products found in Round 3 data capsule.")
    st.stop()

all_timestamps = pd.concat([df["timestamp"] for df in datasets.values()])
ts_min_all = int(all_timestamps.min())
ts_max_all = int(all_timestamps.max())

st.sidebar.header("Controls")
default_product = "VELVETFRUIT_EXTRACT" if "VELVETFRUIT_EXTRACT" in products else products[0]
view_mode = st.sidebar.radio("View mode", options=["Single product", "Multiple products"], index=0)
if view_mode == "Single product":
    selected_single = st.sidebar.selectbox("Product", options=products, index=products.index(default_product))
    selected_products = [selected_single]
else:
    selected_products = st.sidebar.multiselect(
        "Products",
        options=products,
        default=[default_product],
    )
ts_min, ts_max = st.sidebar.slider(
    "Timestamp range",
    min_value=ts_min_all,
    max_value=ts_max_all,
    value=(ts_min_all, ts_max_all),
    step=100,
)
max_points_per_day = st.sidebar.select_slider(
    "Max points/day (performance)",
    options=[500, 1000, 2000, 4000, 8000],
    value=2000,
)
expand_all = st.sidebar.checkbox("Expand all items", value=(view_mode == "Single product"))

st.caption("Each panel shows mid/bid1/ask1 and top-of-book spread for day 0/1/2.")

for product in selected_products:
    with st.expander(product, expanded=expand_all):
        summary = product_summary_table(datasets, product)
        st.dataframe(summary, use_container_width=True, hide_index=True)
        render_product_all_days(
            datasets=datasets,
            product=product,
            ts_min=ts_min,
            ts_max=ts_max,
            max_points_per_day=max_points_per_day,
        )

