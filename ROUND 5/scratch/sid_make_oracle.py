"""Build oracle trader: pick top N most profitable foresight trades on day 4
TRIANGLE, and emit a self-contained trader python file.

If the IMC backtester is honest, total profit ~ sum of these per-trade PnLs.
"""

import csv

CSV = "/Users/siddhant/Desktop/prosperity/imc-prosperity-4/ROUND 5/data_capsule/prices_round_5_day_4.csv"
PRODUCT = "MICROCHIP_TRIANGLE"
LOOKAHEAD = 5
MIN_MOVE = 10
POS_LIMIT = 10
TOP_N = 200          # top trades by profit, embedded in trader
OUT = "/Users/siddhant/Desktop/prosperity/imc-prosperity-4/ROUND 5/traders/sid/sid_oracle.py"

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

trades = []
i = 0
while i < len(rows) - LOOKAHEAD:
    ts, bid, ask, _ = rows[i]
    future = rows[i + 1 : i + 1 + LOOKAHEAD]
    long_idx = max(range(len(future)), key=lambda k: future[k][1])
    short_idx = min(range(len(future)), key=lambda k: future[k][2])
    long_profit = future[long_idx][1] - ask
    short_profit = bid - future[short_idx][2]
    if long_profit >= MIN_MOVE and long_profit >= short_profit:
        trades.append((ts, "BUY", POS_LIMIT, future[long_idx][0], long_profit * POS_LIMIT))
        i += long_idx + 2
    elif short_profit >= MIN_MOVE:
        trades.append((ts, "SELL", POS_LIMIT, future[short_idx][0], short_profit * POS_LIMIT))
        i += short_idx + 2
    else:
        i += 1

# Sort by profit desc, take top N, then re-sort by entry_ts so trader processes in order
trades.sort(key=lambda t: -t[4])
top = trades[:TOP_N]
top.sort(key=lambda t: t[0])

total = sum(t[4] for t in top)
all_total = sum(t[4] for t in trades)
print(f"All {len(trades)} trades: expected profit {all_total:.0f}")
print(f"Top {len(top)} trades: expected profit {total:.0f}")

# Build trades literal
trades_lines = []
for entry_ts, side, qty, exit_ts, _profit in top:
    trades_lines.append(f"    ({entry_ts}, '{side}', {qty}, {exit_ts}),")

content = f'''"""sid/sid_oracle.py — backtester sanity check.

Hard-coded "perfect foresight" trades on MICROCHIP_TRIANGLE for day 4.
Top {TOP_N} most profitable shock-fade trades extracted from
prices_round_5_day_4.csv (lookahead 5 ticks, min move 10).

Expected total profit if backtester is honest: ~{total:.0f}.

If actual backtest profit is dramatically lower, the backtester is doing
something unexpected (slippage model, partial fills, position accounting,
day mismatch). Otherwise our shock-fade strategy just doesn't have signal
on most products and TRIANGLE is one of the few that works.
"""

import json
from collections import defaultdict
from typing import Dict, List

from datamodel import Order, TradingState


PRODUCT = "{PRODUCT}"

# (entry_ts, side, qty, exit_ts) tuples, sorted by entry_ts
ORACLE_TRADES = [
{chr(10).join(trades_lines)}
]


class Trader:
    def _load(self, td: str) -> Dict:
        if not td:
            return {{"trade_idx": 0}}
        try:
            mem = json.loads(td)
            mem.setdefault("trade_idx", 0)
            return mem
        except Exception:
            return {{"trade_idx": 0}}

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        idx = mem["trade_idx"]
        ts = state.timestamp
        pos = state.position.get(PRODUCT, 0)
        result: Dict[str, List[Order]] = defaultdict(list)

        # Skip past stale trades whose exit_ts already passed.
        while idx < len(ORACLE_TRADES) and ts > ORACLE_TRADES[idx][3] and pos == 0:
            idx += 1

        if idx >= len(ORACLE_TRADES):
            mem["trade_idx"] = idx
            return dict(result), 0, self._save(mem)

        d = state.order_depths.get(PRODUCT)
        if not d or not d.buy_orders or not d.sell_orders:
            mem["trade_idx"] = idx
            return dict(result), 0, self._save(mem)
        bid = max(d.buy_orders.keys())
        ask = min(d.sell_orders.keys())

        entry_ts, side, qty, exit_ts = ORACLE_TRADES[idx]

        if pos != 0 and ts >= exit_ts:
            # Close: cross the spread to guarantee fill.
            if pos > 0:
                result[PRODUCT].append(Order(PRODUCT, bid, -pos))
            else:
                result[PRODUCT].append(Order(PRODUCT, ask, -pos))
            idx += 1
        elif pos == 0 and ts >= entry_ts and ts < exit_ts:
            if side == "BUY":
                result[PRODUCT].append(Order(PRODUCT, ask, qty))
            else:
                result[PRODUCT].append(Order(PRODUCT, bid, -qty))

        mem["trade_idx"] = idx
        return dict(result), 0, self._save(mem)
'''

with open(OUT, "w") as f:
    f.write(content)
print(f"Wrote {OUT}")
print(f"File size: {len(content)} bytes")
