#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Summarize e_t signal quality across generated CSV series.")
    p.add_argument(
        "--series-glob",
        default="ROUND 5/docs/*_et_signal_series_generated.csv",
        help="Glob for e_t series CSV files.",
    )
    p.add_argument(
        "--out-csv",
        default="ROUND 5/docs/et_signal_quality_summary.csv",
        help="Output ranked CSV.",
    )
    p.add_argument(
        "--top-n",
        type=int,
        default=25,
        help="Top rows to print.",
    )
    return p.parse_args()


def autocorr_lag1(x: pd.Series) -> float:
    s = x.dropna()
    if len(s) < 10:
        return np.nan
    a = s.iloc[:-1].to_numpy()
    b = s.iloc[1:].to_numpy()
    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def reversion_corr(x: pd.Series) -> float:
    """
    corr(e_t, next_delta_e_t). For mean reversion this tends to be negative.
    """
    s = x.dropna()
    if len(s) < 12:
        return np.nan
    a = s.iloc[:-1].to_numpy()
    d = (s.iloc[1:].to_numpy() - s.iloc[:-1].to_numpy())
    if np.std(a) < 1e-9 or np.std(d) < 1e-9:
        return np.nan
    return float(np.corrcoef(a, d)[0, 1])


def main() -> None:
    args = parse_args()
    paths = sorted(Path(".").glob(args.series_glob))
    if not paths:
        raise ValueError(f"No files matched: {args.series_glob}")

    rows = []
    for p in paths:
        family = p.name.replace("_et_signal_series_generated.csv", "").upper()
        df = pd.read_csv(p)
        if "symbol" not in df.columns or "e_t" not in df.columns:
            continue
        for symbol, g in df.groupby("symbol", sort=True):
            s = g["e_t"].replace([np.inf, -np.inf], np.nan).dropna()
            if s.empty:
                continue
            abs_mean = float(s.abs().mean())
            std = float(s.std())
            q95 = float(np.nanpercentile(s.abs(), 95))
            tail_3 = float((s.abs() >= 3.0).mean())
            ar1 = autocorr_lag1(s)
            rev_c = reversion_corr(s)
            # More negative AR1 is better for mean reversion.
            mr_score = (
                1.8 * max(0.0, -rev_c if not np.isnan(rev_c) else 0.0)
                + 0.7 * tail_3
                + 0.3 * min(q95 / 5.0, 2.0)
            )
            rows.append(
                {
                    "family": family,
                    "symbol": symbol,
                    "samples": int(len(s)),
                    "abs_mean_et": abs_mean,
                    "std_et": std,
                    "q95_abs_et": q95,
                    "tail_rate_abs_ge_3": tail_3,
                    "ar1_et": ar1,
                    "rev_corr_et_next_de": rev_c,
                    "mean_reversion_score": mr_score,
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        raise ValueError("No valid symbol rows computed from input CSV files.")
    out = out.sort_values("mean_reversion_score", ascending=False).reset_index(drop=True)
    out_path = Path(args.out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)

    fam = (
        out.groupby("family", as_index=False)
        .agg(
            family_score=("mean_reversion_score", "mean"),
            best_symbol_score=("mean_reversion_score", "max"),
            avg_tail_rate=("tail_rate_abs_ge_3", "mean"),
        )
        .sort_values("family_score", ascending=False)
        .reset_index(drop=True)
    )
    fam_out = out_path.with_name("et_signal_family_summary.csv")
    fam.to_csv(fam_out, index=False)

    print(f"Wrote symbol summary: {out_path}")
    print(f"Wrote family summary: {fam_out}")
    print("\nTop symbols:")
    print(
        out.head(args.top_n)[
            [
                "symbol",
                "family",
                "mean_reversion_score",
                "rev_corr_et_next_de",
                "ar1_et",
                "q95_abs_et",
                "tail_rate_abs_ge_3",
            ]
        ].to_string(index=False)
    )
    print("\nTop families:")
    print(
        fam.head(10)[["family", "family_score", "best_symbol_score", "avg_tail_rate"]].to_string(index=False)
    )


if __name__ == "__main__":
    main()
