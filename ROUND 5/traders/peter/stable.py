"""peter/stable.py

Stop innovating. Copy the one strategy known to be positive in this
environment: ken/pot.py (single-symbol shock fade, hold 1 tick).

Changes vs ken/pot.py - all conservative, none structural:

  1. Hard pos limit 10/symbol per algo.md (ken's pot used per-family
     limits up to 45; many busted the algo.md cap).
  2. TAKE_CLIP=5 instead of 10. Smaller per-fill -> lower variance.
     Halving clip across 50 products still gives plenty of throughput.
  3. Forced-exit fallback: if pos != 0 but entry_ts state is missing,
     flatten on the next tick anyway. Covers state corruption / restart.
  4. No whitelist. Trade all 50 products, just like pot.py. The shock
     primitive works on every name; restricting hurts coverage.

That is it. Three layers / pair convergence / z-gamble / lag-ratio /
ITM leverage / market making - all removed. They lost money on top of
a positive primitive in our previous traders.
"""

import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


SYM_LIMIT = 10           # algo.md hard cap, applied to every product
TAKE_CLIP = 5            # half of pot.py's clip - lower variance
TRIGGER_MOVE = 8.0       # ken's robust value (alpha sweep winner)
SPREAD_MULT = 1.2        # ken's exact value


class Trader:
    def _load(self, td: str) -> Dict:
        if not td:
            return {"last_mid": {}, "last_ts": -1, "day_idx": 0, "entry_ts": {}}
        try:
            mem = json.loads(td)
            mem.setdefault("last_mid", {})
            mem.setdefault("last_ts", -1)
            mem.setdefault("day_idx", 0)
            mem.setdefault("entry_ts", {})
            return mem
        except Exception:
            return {"last_mid": {}, "last_ts": -1, "day_idx": 0, "entry_ts": {}}

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, symbol: str) -> Tuple[int, int]:
        d = state.order_depths.get(symbol)
        if not d or not d.buy_orders or not d.sell_orders:
            return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def run(self, state: TradingState):
        mem = self._load(state.traderData)

        # Day rollover reset.
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["day_idx"] += 1
            mem["last_mid"] = {}
            mem["entry_ts"] = {}
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        for symbol in state.order_depths.keys():
            bid, ask = self._bba(state, symbol)
            if bid is None or ask is None:
                continue
            spread = max(1, ask - bid)
            mid = 0.5 * (bid + ask)

            last_mid = mem["last_mid"].get(symbol, mid)
            d_mid = mid - last_mid
            mem["last_mid"][symbol] = mid

            pos = state.position.get(symbol, 0)
            buy_cap = max(0, SYM_LIMIT - pos)
            sell_cap = max(0, SYM_LIMIT + pos)
            entry_ts = mem["entry_ts"].get(symbol, -1)

            # ---- Exit: 1-tick hold (ken/pot.py) ----
            # Also forced exit if pos != 0 but no entry_ts (recovery from
            # state loss / restart - never let a position hang).
            if pos != 0 and (entry_ts < 0 or state.timestamp > entry_ts):
                if pos > 0 and sell_cap > 0:
                    result[symbol].append(Order(symbol, bid, -min(pos, sell_cap)))
                elif pos < 0 and buy_cap > 0:
                    result[symbol].append(Order(symbol, ask, min(-pos, buy_cap)))
                mem["entry_ts"][symbol] = -1
                continue

            # ---- Entry: large one-tick shock, fade it ----
            if pos != 0:
                continue
            move_trigger = max(TRIGGER_MOVE, SPREAD_MULT * spread)
            if abs(d_mid) < move_trigger:
                continue

            qty_cap = min(TAKE_CLIP, max(2, int(abs(d_mid) * 0.9)))
            if d_mid <= -move_trigger and buy_cap > 0:
                q = min(qty_cap, buy_cap)
                if q > 0:
                    result[symbol].append(Order(symbol, ask, q))
                    mem["entry_ts"][symbol] = state.timestamp
            elif d_mid >= move_trigger and sell_cap > 0:
                q = min(qty_cap, sell_cap)
                if q > 0:
                    result[symbol].append(Order(symbol, bid, -q))
                    mem["entry_ts"][symbol] = state.timestamp

        return dict(result), 0, self._save(mem)
