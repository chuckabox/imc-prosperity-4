"""Find perfect-foresight trades on day 4 prices.

For MICROCHIP_TRIANGLE: every tick, look ahead N=5 ticks. If next-window has
a price >= 10 ticks higher (after spread cost), buy now and sell at peak.
Symmetric for shorts.

Output: list of (timestamp, action, qty) tuples that should be hard-coded
into an oracle trader. If the backtester runs honestly, profit = sum of
(exit_price - entry_price) * qty across all trades.
"""

import csv
import os

CSV = "/Users/siddhant/Desktop/prosperity/imc-prosperity-4/ROUND 5/data_capsule/prices_round_5_day_4.csv"
PRODUCT = "MICROCHIP_TRIANGLE"
LOOKAHEAD = 5
MIN_MOVE = 10  # only emit trades with >= 10 tick move
POS_LIMIT = 10

rows = []
with open(CSV, "r", encoding="utf-8") as f:
    rdr = csv.reader(f, delimiter=";")
    header = next(rdr)
    idx = {h: i for i, h in enumerate(header)}
    for r in rdr:
        if r[idx["product"]] != PRODUCT:
            continue
        try:
            ts = int(r[idx["timestamp"]])
            bid = float(r[idx["bid_price_1"]])
            ask = float(r[idx["ask_price_1"]])
            mid = float(r[idx["mid_price"]])
            rows.append((ts, bid, ask, mid))
        except Exception:
            continue

rows.sort(key=lambda r: r[0])
print(f"Loaded {len(rows)} rows for {PRODUCT}")
print(f"First ts={rows[0][0]}, last ts={rows[-1][0]}")
print(f"Mid range: {min(r[3] for r in rows):.1f} to {max(r[3] for r in rows):.1f}")

# Strategy: at every tick, peek ahead LOOKAHEAD ticks. If max future ask < current bid -
# MIN_MOVE: short (sell at bid now, buy back at future ask). If future bid > current ask +
# MIN_MOVE: long.
trades = []
i = 0
while i < len(rows) - LOOKAHEAD:
    ts, bid, ask, mid = rows[i]
    future = rows[i + 1 : i + 1 + LOOKAHEAD]
    # For LONG: buy now at ask, sell later at the highest bid available in future
    best_long_exit_idx = max(range(len(future)), key=lambda k: future[k][1])
    long_profit = future[best_long_exit_idx][1] - ask  # sell at future bid - buy at current ask
    # For SHORT: sell now at bid, buy back at lowest ask in future
    best_short_exit_idx = min(range(len(future)), key=lambda k: future[k][2])
    short_profit = bid - future[best_short_exit_idx][2]

    if long_profit >= MIN_MOVE and long_profit >= short_profit:
        exit_ts = future[best_long_exit_idx][0]
        trades.append((ts, "BUY", POS_LIMIT, ask, exit_ts, future[best_long_exit_idx][1]))
        i += best_long_exit_idx + 2  # advance past the exit
    elif short_profit >= MIN_MOVE:
        exit_ts = future[best_short_exit_idx][0]
        trades.append((ts, "SELL", POS_LIMIT, bid, exit_ts, future[best_short_exit_idx][2]))
        i += best_short_exit_idx + 2
    else:
        i += 1

total_profit = 0
for entry_ts, side, qty, entry_px, exit_ts, exit_px in trades:
    if side == "BUY":
        pnl = (exit_px - entry_px) * qty
    else:
        pnl = (entry_px - exit_px) * qty
    total_profit += pnl

print(f"\nFound {len(trades)} oracle trades")
print(f"Total expected profit if backtester honest: {total_profit:.0f}")
print(f"\nFirst 10 trades:")
for t in trades[:10]:
    entry_ts, side, qty, entry_px, exit_ts, exit_px = t
    pnl = (exit_px - entry_px) * qty if side == "BUY" else (entry_px - exit_px) * qty
    print(f"  ts={entry_ts:>6}  {side:4s}  qty={qty}  enter@{entry_px:.0f}  exit_ts={exit_ts:>6}  exit@{exit_px:.0f}  pnl={pnl:+.0f}")

# Write trades as Python tuples for the oracle trader
with open("/Users/siddhant/Desktop/prosperity/imc-prosperity-4/ROUND 5/scratch/oracle_trades.txt", "w") as f:
    f.write(f"# {PRODUCT} oracle trades from day 4 data\n")
    f.write(f"# Total expected profit: {total_profit:.0f}\n")
    f.write(f"# Format: (entry_ts, side, qty, exit_ts)\n")
    f.write("ORACLE_TRADES = [\n")
    for entry_ts, side, qty, entry_px, exit_ts, exit_px in trades:
        f.write(f"    ({entry_ts}, '{side}', {qty}, {exit_ts}),\n")
    f.write("]\n")
print(f"\nWrote {len(trades)} trades to oracle_trades.txt")
