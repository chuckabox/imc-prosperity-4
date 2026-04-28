#!/usr/bin/env python3
from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
PRICE_FILES = [
    REPO_ROOT / "ROUND 5" / "data_capsule" / "prices_round_5_day_2.csv",
    REPO_ROOT / "ROUND 5" / "data_capsule" / "prices_round_5_day_3.csv",
    REPO_ROOT / "ROUND 5" / "data_capsule" / "prices_round_5_day_4.csv",
]
ITEM_DIR = REPO_ROOT / "ROUND 5" / "docs" / "item_over_time"
PAIR_DIR = REPO_ROOT / "ROUND 5" / "docs" / "pair_dashboards"

SPREAD_THRESHOLD = 12
FORWARD_LAG = 20


FAMILIES = [
    "PEBBLES",
    "SNACKPACK",
    "UV_VISOR",
    "GALAXY_SOUNDS",
    "MICROCHIP",
    "TRANSLATOR",
    "SLEEP_POD",
    "OXYGEN_SHAKE",
    "PANEL",
    "ROBOT",
]


def load_round5() -> pd.DataFrame:
    frames = []
    for i, p in enumerate(PRICE_FILES):
        d = pd.read_csv(p, sep=";")[["timestamp", "product", "bid_price_1", "ask_price_1", "mid_price"]].copy()
        d["day_idx"] = i
        d["day_num"] = 2 + i
        d["spread"] = d["ask_price_1"] - d["bid_price_1"]
        frames.append(d)
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["product", "day_idx", "timestamp"]).reset_index(drop=True)


def corr_safe(a: pd.Series, b: pd.Series) -> float:
    z = pd.concat([a, b], axis=1).dropna()
    if len(z) < 10:
        return np.nan
    x = z.iloc[:, 0].to_numpy()
    y = z.iloc[:, 1].to_numpy()
    if np.std(x) < 1e-9 or np.std(y) < 1e-9:
        return np.nan
    return float(np.corrcoef(x, y)[0, 1])


def symbol_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sym, g in df.groupby("product", sort=True):
        g = g.sort_values(["day_idx", "timestamp"]).copy()
        # Rolling z-score-like residual on mid for signal quality.
        raw = g["mid_price"] - g.groupby("day_idx")["mid_price"].transform(
            lambda s: s.rolling(200, min_periods=30).mean()
        )
        std = raw.groupby(g["day_idx"]).transform(lambda s: s.rolling(200, min_periods=30).std()).replace(0, np.nan)
        e_t = (raw - raw.groupby(g["day_idx"]).transform(lambda s: s.rolling(200, min_periods=30).mean())) / std
        e_t = e_t.replace([np.inf, -np.inf], np.nan)

        next_de = e_t.groupby(g["day_idx"]).shift(-1) - e_t
        rev_corr = corr_safe(e_t, next_de)
        tail_rate = float((e_t.abs() >= 3).mean(skipna=True))
        q95 = float(np.nanpercentile(e_t.abs().dropna(), 95)) if e_t.notna().any() else np.nan
        spread_med = float(g["spread"].median())
        score = (
            1.8 * max(0.0, -rev_corr if not np.isnan(rev_corr) else 0.0)
            + 0.7 * tail_rate
            + 0.3 * min((q95 / 5.0) if not np.isnan(q95) else 0.0, 2.0)
            - 0.02 * spread_med
        )
        rows.append(
            {
                "symbol": sym,
                "samples": int(g.shape[0]),
                "median_spread": spread_med,
                "rev_corr_et_next_de": rev_corr,
                "tail_rate_abs_et_ge_3": tail_rate,
                "q95_abs_et": q95,
                "signal_quality_score": score,
            }
        )
    out = pd.DataFrame(rows).sort_values("signal_quality_score", ascending=False).reset_index(drop=True)
    return out


def family_of(symbol: str) -> str:
    for fam in FAMILIES:
        if symbol.startswith(fam + "_"):
            return fam
    return symbol.split("_", 1)[0]


def pair_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    symbols = sorted(df["product"].unique().tolist())
    fam_to_symbols = {fam: [s for s in symbols if s.startswith(fam + "_")] for fam in FAMILIES}

    for fam, syms in fam_to_symbols.items():
        for a, b in itertools.combinations(syms, 2):
            sa = df[df["product"] == a][["day_idx", "timestamp", "mid_price", "spread"]].rename(
                columns={"mid_price": "mid_a", "spread": "spread_a"}
            )
            sb = df[df["product"] == b][["day_idx", "timestamp", "mid_price", "spread"]].rename(
                columns={"mid_price": "mid_b", "spread": "spread_b"}
            )
            m = sa.merge(sb, on=["day_idx", "timestamp"], how="inner")
            if m.empty:
                continue

            m["tight"] = (m["spread_a"] <= SPREAD_THRESHOLD) & (m["spread_b"] <= SPREAD_THRESHOLD)
            m["fwd_ret"] = m.groupby("day_idx")["mid_a"].shift(-FORWARD_LAG) - m["mid_a"]
            rel = m["mid_a"] - m["mid_b"]
            rel_mu = rel.groupby(m["day_idx"]).transform(lambda s: s.rolling(200, min_periods=50).mean())
            signal = np.where(m["tight"], np.sign(rel_mu - rel), 0.0)
            m["signal_ret"] = signal * m["fwd_ret"].fillna(0.0)

            valid = m["tight"].sum()
            mean_sr = float(m.loc[m["tight"], "signal_ret"].mean()) if valid > 0 else np.nan
            total_sr = float(m["signal_ret"].sum())
            tight_rate = float(m["tight"].mean())
            score = (
                (mean_sr if not np.isnan(mean_sr) else 0.0) * np.sqrt(max(1.0, valid))
                + 0.2 * total_sr
                + 10.0 * tight_rate
            )
            rows.append(
                {
                    "pair": f"{a}__{b}",
                    "family": fam,
                    "tight_rate": tight_rate,
                    "tight_count": int(valid),
                    "mean_signal_ret_tight": mean_sr,
                    "total_signal_ret": total_sr,
                    "pair_quality_score": score,
                }
            )

    out = pd.DataFrame(rows).sort_values("pair_quality_score", ascending=False).reset_index(drop=True)
    return out


def main() -> None:
    ITEM_DIR.mkdir(parents=True, exist_ok=True)
    PAIR_DIR.mkdir(parents=True, exist_ok=True)
    df = load_round5()

    sym = symbol_summary(df)
    sym_path = ITEM_DIR / "top_symbols_by_signal_quality.csv"
    sym.to_csv(sym_path, index=False)

    pair = pair_summary(df)
    pair_path = PAIR_DIR / "top_pairs_by_signal_quality.csv"
    pair.to_csv(pair_path, index=False)

    print(f"Wrote {sym_path}")
    print(f"Wrote {pair_path}")
    print("Top symbols:")
    print(sym.head(10).to_string(index=False))
    print("Top pairs:")
    print(pair.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
