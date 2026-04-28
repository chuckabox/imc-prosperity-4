import glob
import json
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
runs_dir = REPO_ROOT / "external" / "prosperity_rust_backtester" / "runs"
backtest_data = {}

log_folders = glob.glob(os.path.join(str(runs_dir), "*"))

for folder in log_folders:
    log_path = os.path.join(folder, "submission.log")
    metrics_path = os.path.join(folder, "metrics.json")
    if not os.path.exists(metrics_path):
        continue

    run_id = os.path.basename(folder)

    with open(metrics_path, "r", encoding="utf-8") as f:
        try:
            metrics = json.load(f)
        except Exception:
            continue

    trader_path = metrics.get("trader_path", "unknown/unknown.py")
    trader_name = trader_path.replace("\\", "/").split("/")[-1].replace(".py", "")
    day = metrics.get("day", -1)
    dataset = metrics.get("dataset_id", "unknown")

    round_num = 3
    parts = dataset.split("_")
    if "round" in parts:
        idx = parts.index("round")
        if idx + 1 < len(parts):
            try:
                round_num = int(parts[idx + 1])
            except ValueError:
                pass

    history = []
    market_prices = {}
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception:
                data = {}

        activities_csv = data.get("activitiesLog", "")
        if activities_csv:
            lines = activities_csv.strip().split("\n")
            header = lines[0].split(";")
            try:
                ts_idx = header.index("timestamp")
                prod_idx = header.index("product")
                mid_idx = header.index("mid_price")
                pnl_idx = header.index("profit_and_loss")
            except ValueError:
                lines = []

            row_counts = {}
            for line in lines[1:]:
                cols = line.split(";")
                if len(cols) < 10:
                    continue
                sym = cols[prod_idx]
                row_counts[sym] = row_counts.get(sym, 0) + 1
                if row_counts[sym] % 200 != 0:
                    continue

                ts = int(cols[ts_idx])
                mid = float(cols[mid_idx])
                pnl = float(cols[pnl_idx])

                if sym not in market_prices:
                    market_prices[sym] = []
                market_prices[sym].append({"ts": ts, "mid": mid})
                history.append({"ts": ts, "symbol": sym, "pnl": pnl})

    final_pnl_by_product = metrics.get("final_pnl_by_product", {})

    backtest_data[run_id] = {
        "label": f"{trader_name} | Day {day} ({dataset})",
        "trader": trader_name,
        "day": day,
        "round": round_num,
        "dataset": dataset,
        "final_pnl": metrics.get("final_pnl_total", 0),
        "final_pnl_by_product": final_pnl_by_product,
        "tick_count": metrics.get("tick_count", 0),
        "history": history,
        "market_prices": market_prices,
    }

output_path = REPO_ROOT / "backtest_comparison.js"
with open(output_path, "w", encoding="utf-8") as f:
    f.write("const BACKTEST_DATA = " + json.dumps(backtest_data) + ";\n")

rounds = sorted(set(v["round"] for v in backtest_data.values()))
days = sorted(set(v["day"] for v in backtest_data.values()))
print(f"Parsed {len(backtest_data)} runs. Rounds: {rounds}, Days: {days}")
