"""Check correlation between HYDROGEL and VFE."""
import pandas as pd
from pathlib import Path

data_dir = Path(r"ROUND 3/data_capsule")
df = pd.read_csv(data_dir / "prices_round_3_day_2.csv", sep=";")
hp = df[df["product"] == "HYDROGEL_PACK"].set_index("timestamp")["mid_price"]
vfe = df[df["product"] == "VELVETFRUIT_EXTRACT"].set_index("timestamp")["mid_price"]

common = hp.index.intersection(vfe.index)
corr = hp.loc[common].corr(vfe.loc[common])
print(f"Correlation HP-VFE: {corr:.4f}")
