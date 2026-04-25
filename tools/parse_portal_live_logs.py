"""Parse Prosperity portal live logs into normalized fills CSV.

Expected log format: JSON with keys:
  - submissionId
  - tradeHistory: [{timestamp,buyer,seller,symbol,currency,price,quantity}, ...]
  - activitiesLog (optional; used to infer day)

By default, own fills are inferred with buyer/seller == "SUBMISSION".
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, List

import pandas as pd


def _iter_log_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    for p in sorted(path.rglob("*.log")):
        yield p


def _infer_day_from_activities(activities: str) -> int | None:
    # activitiesLog is semicolon CSV text; first data row starts with "day;timestamp..."
    lines = activities.splitlines()
    if len(lines) < 2:
        return None
    hdr = lines[0].split(";")
    if not hdr or hdr[0] != "day":
        return None
    first = lines[1].split(";")
    if not first:
        return None
    try:
        return int(first[0])
    except Exception:
        return None


def parse_logs(log_paths: List[Path], own_tag: str = "SUBMISSION") -> pd.DataFrame:
    rows = []
    for p in log_paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue

        submission_id = str(data.get("submissionId", ""))
        day = _infer_day_from_activities(str(data.get("activitiesLog", "")))
        trades = data.get("tradeHistory", [])
        if not isinstance(trades, list):
            continue

        for tr in trades:
            if not isinstance(tr, dict):
                continue
            buyer = str(tr.get("buyer", ""))
            seller = str(tr.get("seller", ""))
            if buyer == own_tag:
                side = "BUY"
            elif seller == own_tag:
                side = "SELL"
            else:
                continue
            try:
                rows.append(
                    {
                        "submission_id": submission_id,
                        "source_file": str(p),
                        "day": day,
                        "timestamp": int(tr.get("timestamp")),
                        "symbol": str(tr.get("symbol", "")).strip(),
                        "price": float(tr.get("price")),
                        "quantity": int(tr.get("quantity")),
                        "side": side,
                    }
                )
            except Exception:
                continue

    if not rows:
        return pd.DataFrame(
            columns=["submission_id", "source_file", "day", "timestamp", "symbol", "price", "quantity", "side"]
        )
    out = pd.DataFrame(rows).sort_values(["submission_id", "timestamp", "symbol"]).reset_index(drop=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract own fills from portal live logs.")
    ap.add_argument("--input", required=True, help="Log file or directory containing .log files")
    ap.add_argument("--output", default="tools/out/portal_fills_from_logs.csv", help="Output CSV path")
    ap.add_argument("--own-tag", default="SUBMISSION", help="Own trader marker in buyer/seller fields")
    args = ap.parse_args()

    in_path = Path(args.input)
    files = list(_iter_log_files(in_path))
    df = parse_logs(files, own_tag=args.own_tag)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)

    print(f"parsed_logs={len(files)}")
    print(f"own_fills={len(df)}")
    if not df.empty:
        print("symbols:", ", ".join(sorted(df['symbol'].dropna().unique())))
        if df["day"].notna().any():
            print("days:", sorted(df["day"].dropna().astype(int).unique().tolist()))
    print(f"saved={out_path}")


if __name__ == "__main__":
    main()

