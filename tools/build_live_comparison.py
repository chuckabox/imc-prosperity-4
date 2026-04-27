"""Build visualizer live dataset from ROUND */live_logs directories.

Outputs a JS file containing:
    const LIVE_LOG_DATA = {...};
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


def iter_live_logs(repo_root: Path) -> Iterable[Path]:
    # Prefer JSON records; include .log files only when JSON sibling is absent.
    json_files = sorted(repo_root.glob("ROUND */live_logs/**/*.json"))
    seen_keys = set()
    for p in json_files:
        key = (p.parent.as_posix().lower(), p.stem.lower())
        seen_keys.add(key)
        yield p

    for p in sorted(repo_root.glob("ROUND */live_logs/**/*.log")):
        key = (p.parent.as_posix().lower(), p.stem.lower())
        if key in seen_keys:
            continue
        yield p


def infer_round(path: Path, payload: Dict) -> Optional[int]:
    raw = payload.get("round")
    try:
        if raw is not None:
            return int(str(raw))
    except Exception:
        pass
    for part in path.parts:
        if part.startswith("ROUND "):
            try:
                return int(part.split(" ", 1)[1])
            except Exception:
                return None
    return None


def parse_activities(activities: str) -> Tuple[Optional[int], Dict[int, Dict[str, float]], List[Dict[str, float]]]:
    lines = [ln for ln in activities.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None, {}, []

    header = lines[0].split(";")
    idx = {k: i for i, k in enumerate(header)}
    required = ["day", "timestamp", "product", "profit_and_loss"]
    if any(k not in idx for k in required):
        return None, {}, []

    rows: List[Tuple[int, int, str, float]] = []
    max_idx = max(idx.values())
    for line in lines[1:]:
        parts = line.split(";")
        if len(parts) <= max_idx:
            continue
        try:
            day = int(float(parts[idx["day"]]))
            ts = int(float(parts[idx["timestamp"]]))
            symbol = parts[idx["product"]].strip()
            pnl = float(parts[idx["profit_and_loss"]] or 0)
        except Exception:
            continue
        rows.append((day, ts, symbol, pnl))

    if not rows:
        return None, {}, []

    day = rows[0][0]
    by_ts_symbol: Dict[int, Dict[str, float]] = {}
    for _, ts, symbol, pnl in rows:
        by_ts_symbol.setdefault(ts, {})[symbol] = pnl

    history: List[Dict[str, float]] = []
    for ts in sorted(by_ts_symbol):
        for symbol, pnl in by_ts_symbol[ts].items():
            history.append({"ts": ts, "symbol": symbol, "pnl": pnl})

    return day, by_ts_symbol, history


def parse_live_file(repo_root: Path, path: Path) -> Optional[Tuple[str, Dict]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    activities = str(payload.get("activitiesLog", ""))
    day, by_ts_symbol, history = parse_activities(activities)
    if day is None or not by_ts_symbol:
        return None

    round_no = infer_round(path, payload)
    if round_no is None:
        return None

    final_ts = max(by_ts_symbol.keys())
    final_by_product = by_ts_symbol.get(final_ts, {})
    fallback_final = sum(final_by_product.values())
    final_pnl = float(payload.get("profit", fallback_final))

    rel = path.relative_to(repo_root).as_posix()
    trader = path.parent.name
    run_id = f"live-r{round_no}-{trader}-{path.stem}"
    record = {
        "label": f"{trader} - Live Day {day} ({path.stem})",
        "trader": trader,
        "day": day,
        "round": round_no,
        "dataset": f"live_log_{path.stem}",
        "source": "live",
        "submission_id": payload.get("submissionId", ""),
        "status": payload.get("status", ""),
        "final_pnl": final_pnl,
        "final_pnl_by_product": final_by_product,
        "tick_count": len(by_ts_symbol),
        "history": history,
        "log_file": rel,
    }
    return run_id, record


def build_live_data(repo_root: Path) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    for path in iter_live_logs(repo_root):
        parsed = parse_live_file(repo_root, path)
        if not parsed:
            continue
        run_id, record = parsed
        out[run_id] = record
    return out


def write_live_data_js(repo_root: Path, output: str = "live_comparison.js") -> Dict[str, object]:
    out_path = (repo_root / output).resolve()
    data = build_live_data(repo_root)
    js = "const LIVE_LOG_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n"
    out_path.write_text(js, encoding="utf-8")
    rounds = sorted({v["round"] for v in data.values()})
    days = sorted({(v["round"], v["day"]) for v in data.values()})
    return {"runs": len(data), "rounds": rounds, "round_day_pairs": days, "saved": str(out_path)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Build visualizer live-log dataset JS.")
    ap.add_argument("--repo-root", default=".", help="Repository root path")
    ap.add_argument("--output", default="live_comparison.js", help="Output JS file path")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    stats = write_live_data_js(repo_root, args.output)
    print(f"runs={stats['runs']}")
    print(f"rounds={stats['rounds']}")
    print(f"round_day_pairs={stats['round_day_pairs'][:12]}")
    print(f"saved={stats['saved']}")


if __name__ == "__main__":
    main()
