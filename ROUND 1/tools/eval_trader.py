import argparse
import importlib.util
import json
import os
import sys
from typing import Dict, List, Tuple

import pandas as pd


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT_DIR, "config")
DATA_DIR = os.path.join(ROOT_DIR, "data", "data_capsule")

if CONFIG_DIR not in sys.path:
    sys.path.append(CONFIG_DIR)

from datamodel import Listing, OrderDepth, TradingState, Observation  # noqa: E402


def load_trader_class(trader_path: str):
    spec = importlib.util.spec_from_file_location("TraderModule", trader_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load trader from path: {trader_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "Trader"):
        raise RuntimeError(f"No Trader class found in: {trader_path}")
    return module.Trader


def simulate_day(trader_cls, day: int) -> float:
    prices_file = os.path.join(DATA_DIR, f"prices_round_1_day_{day}.csv")
    trades_file = os.path.join(DATA_DIR, f"trades_round_1_day_{day}.csv")

    if not os.path.exists(prices_file):
        raise FileNotFoundError(f"Missing prices file: {prices_file}")

    df_prices = pd.read_csv(prices_file, sep=";")
    df_trades = pd.read_csv(trades_file, sep=";") if os.path.exists(trades_file) else None

    trades_dict: Dict[Tuple[int, str], List[dict]] = {}
    if df_trades is not None:
        for (ts, symbol), group in df_trades.groupby(["timestamp", "symbol"]):
            trades_dict[(int(ts), symbol)] = group.to_dict("records")

    trader = trader_cls()
    positions = {"ASH_COATED_OSMIUM": 0, "INTARIAN_PEPPER_ROOT": 0}
    cash = 0.0

    listings = {
        "ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "SEASHELLS"),
        "INTARIAN_PEPPER_ROOT": Listing("INTARIAN_PEPPER_ROOT", "INTARIAN_PEPPER_ROOT", "SEASHELLS"),
    }

    grouped = df_prices.groupby("timestamp")
    last_depths: Dict[str, OrderDepth] = {}

    for ts, group in grouped:
        order_depths: Dict[str, OrderDepth] = {}
        for _, row in group.iterrows():
            product = row["product"]
            depth = OrderDepth()
            if not pd.isna(row["bid_price_1"]):
                depth.buy_orders[int(row["bid_price_1"])] = int(row["bid_volume_1"])
            if not pd.isna(row["ask_price_1"]):
                depth.sell_orders[int(row["ask_price_1"])] = -int(row["ask_volume_1"])
            order_depths[product] = depth
        last_depths = order_depths

        trader_data = json.dumps(getattr(trader, "history", {})) if getattr(trader, "history", {}) else ""
        state = TradingState(
            traderData=trader_data,
            timestamp=int(ts),
            listings=listings,
            order_depths=order_depths,
            own_trades={},
            market_trades={},
            position=positions,
            observations=Observation({}, {}),
        )

        orders, _, returned_data = trader.run(state)
        if hasattr(trader, "traderData"):
            trader.traderData = returned_data

        for product, product_orders in orders.items():
            if product not in order_depths:
                continue

            depth = order_depths[product]
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10**9
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else -(10**9)
            limit = getattr(trader, "limits", {}).get(product, 20)

            for order in product_orders:
                qty = int(order.quantity)
                price = int(order.price)
                if qty == 0:
                    continue

                # Taker fills
                if qty > 0 and price >= best_ask:
                    fill = min(qty, -depth.sell_orders[best_ask], limit - positions[product])
                    if fill > 0:
                        positions[product] += fill
                        cash -= fill * best_ask
                        qty -= fill
                elif qty < 0 and price <= best_bid:
                    fill = min(-qty, depth.buy_orders[best_bid], positions[product] + limit)
                    if fill > 0:
                        positions[product] -= fill
                        cash += fill * best_bid
                        qty += fill

                # Passive fills
                if qty != 0:
                    for trade in trades_dict.get((int(ts), product), []):
                        trade_price = int(trade["price"])
                        trade_volume = int(trade["quantity"])
                        if qty > 0 and price >= trade_price:
                            fill = min(qty, int(trade_volume * 0.5) + 1, limit - positions[product])
                            if fill > 0:
                                positions[product] += fill
                                cash -= fill * price
                                qty -= fill
                        elif qty < 0 and price <= trade_price:
                            fill = min(-qty, int(trade_volume * 0.5) + 1, positions[product] + limit)
                            if fill > 0:
                                positions[product] -= fill
                                cash += fill * price
                                qty += fill

    mtm = cash
    for product, pos in positions.items():
        if product in last_depths:
            depth = last_depths[product]
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 0
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 0
            if best_bid and best_ask:
                mid = (best_bid + best_ask) / 2.0
            else:
                mid = best_bid or best_ask or 0
            mtm += pos * mid

    return mtm


def main():
    parser = argparse.ArgumentParser(description="Evaluate a Round 1 trader locally.")
    parser.add_argument("trader_path", help="Path to trader file, e.g. ROUND 1/traders/trader_ken_v2.py")
    args = parser.parse_args()

    trader_path = args.trader_path
    if not os.path.isabs(trader_path):
        trader_path = os.path.abspath(trader_path)

    trader_cls = load_trader_class(trader_path)
    days = [-2, -1, 0]
    day_pnls = [simulate_day(trader_cls, d) for d in days]
    total = sum(day_pnls)

    print(f"Trader: {trader_path}")
    for day, pnl in zip(days, day_pnls):
        print(f"Day {day}: {pnl:.2f}")
    print(f"Total: {total:.2f}")


if __name__ == "__main__":
    main()
