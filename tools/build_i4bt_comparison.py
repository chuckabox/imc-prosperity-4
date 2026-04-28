#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
I4BT_ROOT = REPO_ROOT / "external" / "imc-prosperity-4-backtester"
BACKTESTS_DIR = I4BT_ROOT / "backtests"


def _safe_load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_round_day_from_token(token: str) -> tuple[int | None, int | None]:
    token = str(token).strip()
    # Supports "5-2", "5", "round5_day2"
    m = re.match(r"^(\d+)-(-?\d+)$", token)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"round[_\s-]?(\d+).*day[_\s-]?(-?\d+)", token, flags=re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^(\d+)$", token)
    if m:
        return int(m.group(1)), None
    return None, None


def _extract_activity_history(activities_log: str, sample_every: int = 200) -> tuple[list[dict], dict[str, list[dict]], dict[str, float], int | None]:
    history: list[dict] = []
    market_prices: dict[str, list[dict]] = {}
    final_by_product: dict[str, float] = {}
    parsed_day: int | None = None
    row_counts: dict[str, int] = {}
    if not activities_log:
        return history, market_prices, final_by_product, parsed_day

    lines = activities_log.strip().split("\n")
    if not lines:
        return history, market_prices, final_by_product, parsed_day
    header = lines[0].split(";")
    try:
        day_idx = header.index("day")
        ts_idx = header.index("timestamp")
        prod_idx = header.index("product")
        mid_idx = header.index("mid_price")
        pnl_idx = header.index("profit_and_loss")
    except ValueError:
        return history, market_prices, final_by_product, parsed_day

    for line in lines[1:]:
        cols = line.split(";")
        if len(cols) <= max(day_idx, ts_idx, prod_idx, mid_idx, pnl_idx):
            continue
        try:
            day = int(float(cols[day_idx]))
            ts = int(float(cols[ts_idx]))
            symbol = cols[prod_idx]
            mid = float(cols[mid_idx])
            pnl = float(cols[pnl_idx])
        except Exception:
            continue

        if parsed_day is None:
            parsed_day = day
        row_counts[symbol] = row_counts.get(symbol, 0) + 1
        if sample_every > 1 and (row_counts[symbol] % sample_every != 0):
            continue
        history.append({"ts": ts, "symbol": symbol, "pnl": pnl})
        market_prices.setdefault(symbol, []).append({"ts": ts, "mid": mid})
        final_by_product[symbol] = pnl

    return history, market_prices, final_by_product, parsed_day


def _infer_round_from_symbols(symbols: set[str]) -> int | None:
    s = {str(x).upper() for x in symbols}
    round5_markers = ("MICROCHIP_", "PEBBLES_", "SNACKPACK_", "UV_VISOR_", "GALAXY_SOUNDS_")
    if any(any(sym.startswith(prefix) for prefix in round5_markers) for sym in s):
        return 5
    return None


def build_i4bt_data() -> dict:
    data: dict[str, dict] = {}
    if not BACKTESTS_DIR.exists():
        return data

    for log_path in sorted(BACKTESTS_DIR.glob("*.log")):
        payload = _safe_load_json(log_path)
        if not isinstance(payload, dict):
            continue

        run_id = f"i4bt::{log_path.stem}"
        meta_path = log_path.with_suffix(".meta.json")
        meta = _safe_load_json(meta_path) if meta_path.exists() else {}
        if not isinstance(meta, dict):
            meta = {}

        trader_path = str(meta.get("trader_path", "unknown/unknown.py"))
        trader_name = Path(trader_path).stem if trader_path else "unknown"
        day_args = meta.get("rounds_or_days") or []
        if isinstance(day_args, str):
            day_args = [day_args]
        if not isinstance(day_args, list):
            day_args = []

        round_num = None
        day_num = None
        for tok in day_args:
            r, d = _parse_round_day_from_token(str(tok))
            if round_num is None and r is not None:
                round_num = r
            if day_num is None and d is not None:
                day_num = d

        # Fallback parse from filename convention "<trader>__<dayargs>__<timestamp>.log"
        if round_num is None or day_num is None:
            parts = log_path.stem.split("__")
            if len(parts) >= 2:
                tokens = parts[1].split("+")
                for tok in tokens:
                    r, d = _parse_round_day_from_token(tok)
                    if round_num is None and r is not None:
                        round_num = r
                    if day_num is None and d is not None:
                        day_num = d

        activities_log = payload.get("activitiesLog", "")
        history, market_prices, final_by_product, parsed_day = _extract_activity_history(activities_log)
        if day_num is None and parsed_day is not None:
            day_num = parsed_day
        if round_num is None:
            round_num = _infer_round_from_symbols(set(final_by_product.keys()))
        if round_num is None:
            round_num = -1
        if day_num is None:
            day_num = -1

        final_pnl_total = sum(final_by_product.values()) if final_by_product else 0.0
        dataset = f"i4bt_round_{round_num}_day_{day_num}"
        data[run_id] = {
            "label": f"{trader_name} | Day {day_num} ({dataset})",
            "trader": trader_name,
            "day": day_num,
            "round": round_num,
            "dataset": dataset,
            "final_pnl": final_pnl_total,
            "final_pnl_by_product": final_by_product,
            "tick_count": len(history),
            "history": history,
            "market_prices": market_prices,
            "source_file": str(log_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        }
    return data


def write_i4bt_data_js(output_file: str = "i4bt_comparison.js") -> dict:
    data = build_i4bt_data()
    out_path = REPO_ROOT / output_file
    out_path.write_text("const I4BT_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n", encoding="utf-8")
    rounds = sorted({v.get("round") for v in data.values() if isinstance(v.get("round"), int) and v.get("round") >= 0})
    days = sorted({v.get("day") for v in data.values() if isinstance(v.get("day"), int) and v.get("day") >= 0})
    stats = {"saved": str(out_path), "runs": len(data), "rounds": rounds, "days": days}
    print(f"Wrote {len(data)} i4bt runs to {out_path.name}. Rounds: {rounds}, Days: {days}")
    return stats


if __name__ == "__main__":
    write_i4bt_data_js()
