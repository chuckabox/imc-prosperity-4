from __future__ import annotations

import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from datamodel import OrderDepth, TradingState


ROOT = Path(__file__).resolve().parents[1] / "data_capsule"
TRADER_PATH = Path(__file__).resolve().parents[1] / "traders" / "ken" / "pot.py"


def load_trader():
    spec = importlib.util.spec_from_file_location("round5_ken_pot", TRADER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Trader()


def load_day(day: int) -> pd.DataFrame:
    df = pd.read_csv(ROOT / f"prices_round_5_day_{day}.csv", sep=";")
    cols = [
        "timestamp",
        "product",
        "bid_price_1",
        "bid_volume_1",
        "ask_price_1",
        "ask_volume_1",
        "mid_price",
    ]
    return df[cols].copy()


def run_day(trader, day: int, max_ts: int | None = None) -> dict:
    df = load_day(day)
    if max_ts is not None:
        df = df[df["timestamp"] <= max_ts].copy()
    ts_values = sorted(df["timestamp"].unique())

    trader_data = ""
    position = defaultdict(int)
    cash = 0.0
    pnl_series = []

    by_ts = {ts: g for ts, g in df.groupby("timestamp", sort=True)}

    for ts in ts_values:
        group = by_ts[ts]
        order_depths = {}
        mids = {}
        top = {}
        for _, row in group.iterrows():
            symbol = row["product"]
            bid = int(row["bid_price_1"])
            ask = int(row["ask_price_1"])
            bid_v = int(row["bid_volume_1"])
            ask_v = int(row["ask_volume_1"])

            od = OrderDepth()
            od.buy_orders = {bid: bid_v}
            od.sell_orders = {ask: -abs(ask_v)}
            order_depths[symbol] = od
            mids[symbol] = float(row["mid_price"])
            top[symbol] = (bid, bid_v, ask, ask_v)

        state = TradingState(
            traderData=trader_data,
            timestamp=int(ts),
            listings={},
            order_depths=order_depths,
            own_trades={},
            market_trades={},
            position=dict(position),
            observations={},
        )

        orders, _, trader_data = trader.run(state)
        for symbol, ords in orders.items():
            if symbol not in top:
                continue
            bid, bid_v, ask, ask_v = top[symbol]
            for order in ords:
                qty = int(order.quantity)
                if qty > 0 and order.price >= ask:
                    fill = min(qty, ask_v)
                    if fill > 0:
                        position[symbol] += fill
                        cash -= fill * ask
                elif qty < 0 and order.price <= bid:
                    fill = min(-qty, bid_v)
                    if fill > 0:
                        position[symbol] -= fill
                        cash += fill * bid

        mtm = sum(position[s] * mids.get(s, 0.0) for s in position.keys())
        pnl_series.append((int(ts), cash + mtm))

    final_pnl = pnl_series[-1][1] if pnl_series else 0.0
    max_abs_pos = max((abs(v) for v in position.values()), default=0)
    return {
        "day": day,
        "ticks": len(ts_values),
        "final_pnl": final_pnl,
        "max_abs_position": int(max_abs_pos),
        "open_positions": {k: v for k, v in position.items() if v != 0},
        "pnl_series_tail": pnl_series[-5:],
    }


def main():
    trader = load_trader()
    out = {
        "day2": run_day(trader, 2),
        "day3_first10pct": run_day(trader, 3, max_ts=99_900),
        "day3_full": run_day(trader, 3),
        "day4": run_day(trader, 4),
    }
    out["total_3days_full"] = out["day2"]["final_pnl"] + out["day3_full"]["final_pnl"] + out["day4"]["final_pnl"]
    out["total_day2_day3first10_day4"] = (
        out["day2"]["final_pnl"] + out["day3_first10pct"]["final_pnl"] + out["day4"]["final_pnl"]
    )
    p = Path(__file__).resolve().parent / "sim_round5_results.json"
    p.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {p}")
    print(json.dumps({k: out[k]["final_pnl"] for k in ["day2", "day3_first10pct", "day3_full", "day4"]}, indent=2))
    print("total_3days_full", out["total_3days_full"])


if __name__ == "__main__":
    main()
