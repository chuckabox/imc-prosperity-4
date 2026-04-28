from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "ROUND 4" / "data_capsule"


def _read_prices(day: int) -> pd.DataFrame:
    path = DATASET / f"prices_round_4_day_{day}.csv"
    df = pd.read_csv(path, sep=";")
    df["timestamp"] = df["timestamp"].astype(int)
    return df


def _product_summary(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for product, g in df.groupby("product", sort=True):
        g = g.sort_values("timestamp")
        bid = g["bid_price_1"].astype(float)
        ask = g["ask_price_1"].astype(float)
        mid = g["mid_price"].astype(float)
        spread = (ask - bid).replace([np.inf, -np.inf], np.nan)
        ret = mid.diff()

        out.append(
            {
                "product": product,
                "ticks": int(len(g)),
                "mid_mean": float(mid.mean()),
                "mid_std": float(mid.std(ddof=0)),
                "spread_mean": float(spread.mean()),
                "spread_p50": float(spread.quantile(0.5)),
                "spread_p90": float(spread.quantile(0.9)),
                "abs_ret_mean": float(ret.abs().mean()),
                "ret_autocorr_1": float(ret.autocorr(lag=1)) if len(ret.dropna()) > 10 else float("nan"),
            }
        )
    return pd.DataFrame(out).sort_values(["spread_mean", "mid_std"], ascending=[False, False])


def _vev_mispricing(df: pd.DataFrame) -> pd.DataFrame:
    # crude "intrinsic" proxy: VEV_K ~ max(VFE_mid - K, 0)
    vfe = df[df["product"] == "VELVETFRUIT_EXTRACT"][["timestamp", "mid_price"]].rename(
        columns={"mid_price": "vfe_mid"}
    )
    vev = df[df["product"].str.startswith("VEV_")].copy()
    vev["strike"] = vev["product"].str.replace("VEV_", "", regex=False).astype(int)
    vev = vev.merge(vfe, on="timestamp", how="inner")
    vev["intrinsic"] = (vev["vfe_mid"] - vev["strike"]).clip(lower=0.0)
    vev["mid"] = vev["mid_price"].astype(float)
    vev["mispricing"] = vev["mid"] - vev["intrinsic"]
    vev["spread"] = vev["ask_price_1"].astype(float) - vev["bid_price_1"].astype(float)
    return vev


def _vev_mispricing_summary(vev: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for product, g in vev.groupby("product", sort=True):
        m = g["mispricing"].astype(float)
        rows.append(
            {
                "product": product,
                "strike": int(g["strike"].iloc[0]),
                "ticks": int(len(g)),
                "mispricing_mean": float(m.mean()),
                "mispricing_std": float(m.std(ddof=0)),
                "mispricing_p05": float(m.quantile(0.05)),
                "mispricing_p50": float(m.quantile(0.50)),
                "mispricing_p95": float(m.quantile(0.95)),
                "spread_mean": float(g["spread"].mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("mispricing_std", ascending=False)


def main() -> None:
    for day in [1, 2, 3]:
        df = _read_prices(day)
        print(f"\n=== DAY {day} product microstructure summary (sorted by spread_mean desc) ===")
        summ = _product_summary(df)
        print(summ.to_string(index=False, max_rows=50))

        vev = _vev_mispricing(df)
        vev_summ = _vev_mispricing_summary(vev)
        print(f"\n=== DAY {day} VEV mispricing vs max(VFE_mid - strike, 0) ===")
        print(vev_summ.to_string(index=False, max_rows=50))

        # show biggest absolute mispricings overall (for manual inspection)
        vev["abs_mis"] = vev["mispricing"].abs()
        top = vev.sort_values("abs_mis", ascending=False).head(25)[
            ["timestamp", "product", "strike", "vfe_mid", "mid", "intrinsic", "mispricing", "spread"]
        ]
        print(f"\n=== DAY {day} top 25 absolute mispricings (by |mid-intrinsic|) ===")
        print(top.to_string(index=False))


if __name__ == "__main__":
    main()

