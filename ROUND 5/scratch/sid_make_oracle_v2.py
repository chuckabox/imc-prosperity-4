"""Build oracle v2: foresight trades for ALL 50 products on day 4.

Per product:
  - Compute median spread.
  - MIN_MOVE = max(8, ceil(median_spread * 1.5))  # need at least 1.5x spread to profit
  - Find foresight trades via lookahead 5 ticks.
  - Cap at TOP_N_PER_PRODUCT highest-profit trades.

Trader: per-tick scan all products, advance per-product trade idx.
"""

import csv
import math
from collections import defaultdict
from statistics import median

CSV = "/Users/siddhant/Desktop/prosperity/imc-prosperity-4/ROUND 5/data_capsule/prices_round_5_day_4.csv"
LOOKAHEAD = 5
POS_LIMIT = 10
TOP_N_PER_PRODUCT = 80
OUT = "/Users/siddhant/Desktop/prosperity/imc-prosperity-4/ROUND 5/traders/sid/sid_oracle_v2.py"

# Group rows by product
prod_rows = defaultdict(list)
with open(CSV, "r", encoding="utf-8") as f:
    rdr = csv.reader(f, delimiter=";")
    header = next(rdr)
    idx = {h: i for i, h in enumerate(header)}
    for r in rdr:
        try:
            p = r[idx["product"]]
            ts = int(r[idx["timestamp"]])
            bid = float(r[idx["bid_price_1"]])
            ask = float(r[idx["ask_price_1"]])
            prod_rows[p].append((ts, bid, ask))
        except Exception:
            continue

print(f"Products in day 4: {len(prod_rows)}")

per_product_trades = {}
total_expected = 0.0

for prod, rows in sorted(prod_rows.items()):
    rows.sort(key=lambda r: r[0])
    spreads = [r[2] - r[1] for r in rows if r[2] > r[1]]
    if not spreads:
        continue
    spread_med = median(spreads)
    MIN_MOVE = max(8, math.ceil(spread_med * 1.5))

    trades = []
    i = 0
    while i < len(rows) - LOOKAHEAD:
        ts, bid, ask = rows[i]
        future = rows[i + 1 : i + 1 + LOOKAHEAD]
        long_idx = max(range(len(future)), key=lambda k: future[k][1])
        short_idx = min(range(len(future)), key=lambda k: future[k][2])
        long_profit = future[long_idx][1] - ask
        short_profit = bid - future[short_idx][2]
        if long_profit >= MIN_MOVE and long_profit >= short_profit:
            trades.append((ts, "BUY", future[long_idx][0], long_profit * POS_LIMIT))
            i += long_idx + 2
        elif short_profit >= MIN_MOVE:
            trades.append((ts, "SELL", future[short_idx][0], short_profit * POS_LIMIT))
            i += short_idx + 2
        else:
            i += 1

    trades.sort(key=lambda t: -t[3])
    top = trades[:TOP_N_PER_PRODUCT]
    top.sort(key=lambda t: t[0])
    expected = sum(t[3] for t in top)
    if top:
        per_product_trades[prod] = top
        total_expected += expected
        print(f"  {prod:34s}  spread_med={spread_med:>4.0f}  trades={len(trades):>4}  top={len(top):>3}  exp={expected:>10.0f}")

print(f"\nTotal products with trades: {len(per_product_trades)}")
print(f"Total expected profit (top {TOP_N_PER_PRODUCT}/prod): {total_expected:.0f}")

# Build trader file
preamble = '''"""sid/sid_oracle_v2.py — backtester sanity check across all 50 products.

Hard-coded foresight trades. Top {TOP_N} highest-profit trades per product
(lookahead 5 ticks, min_move = max(8, 1.5x median spread)).

Expected total profit if backtester is honest: ~{TOTAL:.0f}.

Position limit 10 per product. Per-product state tracks trade index.
"""

import json
from collections import defaultdict
from typing import Dict, List

from datamodel import Order, TradingState


POS_LIMIT = 10

# product -> [(entry_ts, side, exit_ts), ...]
ORACLE_TRADES = {{
'''.format(TOP_N=TOP_N_PER_PRODUCT, TOTAL=total_expected)

trade_lines = []
for prod, trades in per_product_trades.items():
    trade_lines.append(f'    "{prod}": [')
    for entry_ts, side, exit_ts, _ in trades:
        trade_lines.append(f"        ({entry_ts}, '{side}', {exit_ts}),")
    trade_lines.append("    ],")

postamble = '''}


class Trader:
    def _load(self, td: str) -> Dict:
        if not td:
            return {"idx": {}}
        try:
            mem = json.loads(td)
            mem.setdefault("idx", {})
            return mem
        except Exception:
            return {"idx": {}}

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        ts = state.timestamp
        result: Dict[str, List[Order]] = defaultdict(list)

        for prod, trades in ORACLE_TRADES.items():
            i = mem["idx"].get(prod, 0)
            pos = state.position.get(prod, 0)
            d = state.order_depths.get(prod)
            if not d or not d.buy_orders or not d.sell_orders:
                continue
            bid = max(d.buy_orders.keys())
            ask = min(d.sell_orders.keys())

            # Skip stale trades whose exit_ts already passed (only if flat)
            while i < len(trades) and ts > trades[i][2] and pos == 0:
                i += 1
            if i >= len(trades):
                mem["idx"][prod] = i
                continue

            entry_ts, side, exit_ts = trades[i]

            if pos != 0 and ts >= exit_ts:
                # Close
                if pos > 0:
                    result[prod].append(Order(prod, bid, -pos))
                else:
                    result[prod].append(Order(prod, ask, -pos))
                i += 1
            elif pos == 0 and ts >= entry_ts and ts < exit_ts:
                if side == "BUY":
                    result[prod].append(Order(prod, ask, POS_LIMIT))
                else:
                    result[prod].append(Order(prod, bid, -POS_LIMIT))

            mem["idx"][prod] = i

        return dict(result), 0, self._save(mem)
'''

with open(OUT, "w") as f:
    f.write(preamble)
    f.write("\n".join(trade_lines))
    f.write("\n")
    f.write(postamble)

print(f"\nWrote {OUT}")
import os
print(f"File size: {os.path.getsize(OUT)} bytes")
