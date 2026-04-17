"""Quick stress test: run v2 on all scenario CSVs and report PnL + max position."""
import sys, os, glob, math
import pandas as pd
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "traders"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from datamodel import Listing, OrderDepth, TradingState, Observation, Order
import importlib.util

TRADER_FILE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "traders", "peter", "trader_robust_peter_v2.py"
)

spec = importlib.util.spec_from_file_location("TM", TRADER_FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SCENARIO_DIR = os.path.join(os.path.dirname(__file__), "..", "data_capsule", "scenarios")

listings = {
    "ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "SEASHELLS"),
    "INTARIAN_PEPPER_ROOT": Listing("INTARIAN_PEPPER_ROOT", "INTARIAN_PEPPER_ROOT", "SEASHELLS"),
}

def run_scenario(prices_file):
    df = pd.read_csv(prices_file, sep=";")
    trader = mod.Trader()
    cash = 0.0
    positions = {p: 0 for p in listings}
    max_pos = {p: 0 for p in listings}
    hit_floor = False

    for ts, group in df.groupby("timestamp"):
        order_depths = {}
        for _, row in group.iterrows():
            product = row["product"]
            depth = OrderDepth()
            if not pd.isna(row.get("bid_price_1", float("nan"))):
                depth.buy_orders[int(row["bid_price_1"])] = int(row["bid_volume_1"])
            if not pd.isna(row.get("ask_price_1", float("nan"))):
                depth.sell_orders[int(row["ask_price_1"])] = -int(row["ask_volume_1"])
            order_depths[product] = depth

        state = TradingState(
            traderData=json.dumps(trader.history) if trader.history else "",
            timestamp=ts, listings=listings, order_depths=order_depths,
            own_trades={}, market_trades={},
            position=dict(positions), observations=Observation({}, {})
        )
        orders, _, td = trader.run(state)
        trader.history = json.loads(td) if td else {}

        for product, ol in orders.items():
            if product not in order_depths: continue
            d = order_depths[product]
            ca = min(d.sell_orders.keys()) if d.sell_orders else 999999
            cb = max(d.buy_orders.keys()) if d.buy_orders else -999999
            lim = 80
            for o in ol:
                qty, price = o.quantity, o.price
                if qty > 0 and price >= ca:
                    fill = min(qty, -d.sell_orders.get(ca, 0), lim - positions[product])
                    if fill > 0:
                        positions[product] += fill
                        cash -= fill * ca
                elif qty < 0 and price <= cb:
                    fill = min(-qty, d.buy_orders.get(cb, 0), positions[product] + lim)
                    if fill > 0:
                        positions[product] -= fill
                        cash += fill * cb

        for p in positions:
            max_pos[p] = max(max_pos[p], abs(positions[p]))
            if abs(positions[p]) >= 80:
                hit_floor = True

    # Final MTM
    pnl = cash
    for p, pos in positions.items():
        if p in order_depths:
            d = order_depths[p]
            bb = max(d.buy_orders.keys()) if d.buy_orders else 0
            ba = min(d.sell_orders.keys()) if d.sell_orders else 0
            mid = (bb + ba) / 2 if bb and ba else (bb or ba or 0)
            pnl += pos * mid

    return pnl, positions, max_pos, hit_floor

files = sorted(glob.glob(os.path.join(SCENARIO_DIR, "prices_*.csv")))
print(f"{'Scenario':<40} {'PnL':>10} {'MaxOsm':>8} {'MaxPep':>8} {'Floor?':>7}")
print("-" * 80)
total = 0
floors = 0
for f in files:
    name = os.path.basename(f).replace("prices_", "").replace(".csv", "")
    pnl, pos, mp, hf = run_scenario(f)
    total += pnl
    if hf: floors += 1
    flag = "⚠ YES" if hf else "OK"
    print(f"{name:<40} {pnl:>10,.0f} {mp['ASH_COATED_OSMIUM']:>8} {mp['INTARIAN_PEPPER_ROOT']:>8} {flag:>7}")

print("-" * 80)
print(f"{'TOTAL':<40} {total:>10,.0f}   Floor hits: {floors}/{len(files)}")
