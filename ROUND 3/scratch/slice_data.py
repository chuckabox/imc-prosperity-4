"""Create 10% slice of day 2 prices, aggressively preserving integer types."""
import pandas as pd
from pathlib import Path
import numpy as np

data_dir = Path(r"ROUND 3/data_capsule")
df = pd.read_csv(data_dir / "prices_round_3_day_2.csv", sep=";")
max_ts = df["timestamp"].max()
slice_df = df[df["timestamp"] <= max_ts * 0.1].copy()

for col in slice_df.columns:
    if col in ["mid_price", "profit_and_loss"]:
        continue
    # Try to convert to int if numeric
    if pd.api.types.is_numeric_dtype(slice_df[col]):
        # fillna(0) to avoid errors, then cast to int
        slice_df[col] = slice_df[col].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)

slice_df.to_csv(data_dir / "prices_round_3_day_2_10pct.csv", sep=";", index=False)

trades_df = pd.read_csv(data_dir / "trades_round_3_day_2.csv", sep=";")
slice_trades = trades_df[trades_df["timestamp"] <= max_ts * 0.1].copy()
for col in slice_trades.columns:
    if pd.api.types.is_numeric_dtype(slice_trades[col]) and col != "timestamp":
        slice_trades[col] = slice_trades[col].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
slice_trades.to_csv(data_dir / "trades_round_3_day_2_10pct.csv", sep=";", index=False)
