"""Round 3 alpha mining helper.

Usage:
    python tools/alpha_mining_round3.py
"""
from __future__ import annotations

import os
from typing import Dict, List

import numpy as np
import pandas as pd


def _load_prices(base_dir: str, days: List[int]) -> pd.DataFrame:
    frames = []
    for d in days:
        f = os.path.join(base_dir, f"prices_round_3_day_{d}.csv")
        if not os.path.exists(f):
            continue
        x = pd.read_csv(f, sep=";")
        x["src_day"] = d
        frames.append(x)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["bid_price_1", "ask_price_1"]).copy()
    out["mid"] = (out["bid_price_1"] + out["ask_price_1"]) / 2.0
    out["spread"] = out["ask_price_1"] - out["bid_price_1"]
    return out


def _signal_stats(series: pd.Series, span: int, horizon: int, z_thr: float) -> Dict[str, float]:
    x = series.reset_index(drop=True)
    ema = x.ewm(span=span, adjust=False).mean()
    dev = x - ema
    fwd = x.shift(-horizon) - x
    vol = dev.rolling(500, min_periods=250).std().replace(0, np.nan)
    z = dev / vol
    d = pd.DataFrame({"dev": dev, "fwd": fwd, "z": z}).dropna()
    if d.empty:
        return {"n": 0, "hit": np.nan, "edge": np.nan, "corr": np.nan}
    ext = d[d["z"].abs() >= z_thr]
    if ext.empty:
        return {"n": 0, "hit": np.nan, "edge": np.nan, "corr": float(d["dev"].corr(d["fwd"]))}
    hit = (((ext["dev"] > 0) & (ext["fwd"] < 0)) | ((ext["dev"] < 0) & (ext["fwd"] > 0))).mean()
    return {
        "n": int(len(ext)),
        "hit": float(hit),
        "edge": float(ext["fwd"].abs().mean()),
        "corr": float(d["dev"].corr(d["fwd"])),
    }


def mine_round3(data_dir: str, days: List[int]) -> Dict[str, pd.DataFrame]:
    df = _load_prices(data_dir, days)
    if df.empty:
        return {"underlyings": pd.DataFrame(), "vev": pd.DataFrame(), "leadlag": pd.DataFrame()}

    under_rows = []
    for p in ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"]:
        s = df[df["product"] == p].sort_values(["src_day", "timestamp"]).copy()
        if s.empty:
            continue
        x = s["mid"]
        stats = _signal_stats(x, span=220, horizon=50, z_thr=1.5)
        under_rows.append(
            {
                "product": p,
                "ret_lag1_ac": float(x.diff().dropna().autocorr(lag=1)),
                "signal_corr_dev_fwd": stats["corr"],
                "extreme_hit_rate": stats["hit"],
                "extreme_count": stats["n"],
                "avg_abs_fwd_move": stats["edge"],
                "mean_spread": float(s["spread"].mean()),
                "edge_to_spread": float(stats["edge"] / s["spread"].mean()) if stats["edge"] and s["spread"].mean() > 0 else np.nan,
            }
        )
    under_df = pd.DataFrame(under_rows)

    vev_rows = []
    pv = df.pivot_table(index=["src_day", "timestamp"], columns="product", values="mid").sort_index()
    if "VELVETFRUIT_EXTRACT" in pv.columns:
        s = pv["VELVETFRUIT_EXTRACT"]
        for c in [c for c in pv.columns if str(c).startswith("VEV_")]:
            try:
                k = int(str(c).split("_")[1])
            except Exception:
                continue
            prem = (pv[c] - np.maximum(s - k, 0.0)).dropna()
            if len(prem) < 1200:
                continue
            stats = _signal_stats(prem, span=120, horizon=50, z_thr=1.5)
            spread_mean = float(df[df["product"] == c]["spread"].mean())
            vev_rows.append(
                {
                    "strike": k,
                    "corr_dev_fwd_prem": stats["corr"],
                    "extreme_hit_rate": stats["hit"],
                    "extreme_count": stats["n"],
                    "avg_abs_fwd_prem_move": stats["edge"],
                    "mean_spread": spread_mean,
                    "edge_to_spread": float(stats["edge"] / spread_mean) if stats["edge"] and spread_mean > 0 else np.nan,
                }
            )
    vev_df = pd.DataFrame(vev_rows).sort_values("edge_to_spread", ascending=False) if vev_rows else pd.DataFrame()

    lead_rows = []
    if "HYDROGEL_PACK" in pv.columns and "VELVETFRUIT_EXTRACT" in pv.columns:
        h = pv["HYDROGEL_PACK"].reset_index(drop=True).diff()
        v = pv["VELVETFRUIT_EXTRACT"].reset_index(drop=True).diff()
        for lag in [1, 2, 3, 5, 8, 13, 21]:
            d = pd.DataFrame({"h": h, "v": v.shift(-lag)}).dropna()
            if len(d) < 1000:
                continue
            lead_rows.append(
                {"signal": "hydro_ret_t -> vfe_ret_t+lag", "lag": lag, "corr": float(d["h"].corr(d["v"]))}
            )
        for lag in [1, 2, 3, 5, 8, 13, 21]:
            d = pd.DataFrame({"v": v, "h": h.shift(-lag)}).dropna()
            if len(d) < 1000:
                continue
            lead_rows.append(
                {"signal": "vfe_ret_t -> hydro_ret_t+lag", "lag": lag, "corr": float(d["v"].corr(d["h"]))}
            )
    leadlag_df = pd.DataFrame(lead_rows)
    if not leadlag_df.empty:
        leadlag_df["abs_corr"] = leadlag_df["corr"].abs()
        leadlag_df = leadlag_df.sort_values("abs_corr", ascending=False)

    return {"underlyings": under_df, "vev": vev_df, "leadlag": leadlag_df}


if __name__ == "__main__":
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out = mine_round3(os.path.join(root, "ROUND 3", "data_capsule"), [0, 1, 2])
    print("\n[UNDERLYINGS]")
    print(out["underlyings"].to_string(index=False) if not out["underlyings"].empty else "none")
    print("\n[VEV]")
    print(out["vev"].to_string(index=False) if not out["vev"].empty else "none")
    print("\n[LEAD/LAG]")
    print(out["leadlag"].head(12).to_string(index=False) if not out["leadlag"].empty else "none")

