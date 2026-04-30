"""sid/sid_v2.py — same skeleton as v1, retuned from v1 backtest log.

v1 results (day 4 backtest, total +150.92):
  MICROCHIP_TRIANGLE   +306.52  (525W / 471L, +0.31/event)
  MICROCHIP_RECTANGLE  -155.60  (461W / 487L, -0.16/event)

Diagnosis: RECTANGLE trigger=12 fires too close to its avg move (10.4) so it
catches noise rather than mean-reverting shocks. TRIANGLE works because its
13 trigger vs 11.5 avg has more cushion against the 9-spread cost.

v2 changes:
  - MICROCHIP_RECTANGLE trigger 12 -> 16  (only real shocks)
  - MICROCHIP_RECTANGLE max_spread 11 -> 9  (require liquid book)
  - MICROCHIP_TRIANGLE unchanged (already profitable)
  - COOLDOWN_TICKS 4 -> 3 (more fade entries post-shock)
"""

import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


class Trader:
    PARAMS = {
        "MICROCHIP_RECTANGLE": {
            "trigger": 16.0,    # was 12. Only fire when |dmid| > shock threshold.
            "big_shock": 24.0,  # was 20.
            "max_spread": 9,    # was 11. Require liquid book.
        },
        "MICROCHIP_TRIANGLE": {
            "trigger": 13.0,    # unchanged.
            "big_shock": 22.0,  # unchanged.
            "max_spread": 12,   # unchanged.
        },
    }

    POS_LIMIT = 10
    HOLD_DEFAULT = 1
    HOLD_BIG = 2
    COOLDOWN_TICKS = 3          # was 4
    MAX_ORDERS_PER_TICK = 2
    ENTRY_SIZE_DEFAULT = 3
    ENTRY_SIZE_BIG = 5

    def _load(self, td: str) -> Dict:
        if not td:
            return {"last_mid": {}, "entries": {}, "last_trade_ts": {}, "last_ts": -1, "day_idx": 0}
        try:
            mem = json.loads(td)
            mem.setdefault("last_mid", {})
            mem.setdefault("entries", {})
            mem.setdefault("last_trade_ts", {})
            mem.setdefault("last_ts", -1)
            mem.setdefault("day_idx", 0)
            return mem
        except Exception:
            return {"last_mid": {}, "entries": {}, "last_trade_ts": {}, "last_ts": -1, "day_idx": 0}

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    @staticmethod
    def _best_bid_ask(state: TradingState, sym: str) -> Tuple:
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders:
            return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def _entry_size(self, d_mid: float, big_shock: float, spread: int) -> int:
        size = self.ENTRY_SIZE_DEFAULT if abs(d_mid) < big_shock else self.ENTRY_SIZE_BIG
        if spread <= 6:
            size += 1
        return min(self.POS_LIMIT // 2 + 1, max(1, size))

    def run(self, state: TradingState):
        mem = self._load(state.traderData)

        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["day_idx"] += 1
            mem["last_mid"] = {}
            mem["entries"] = {}
            mem["last_trade_ts"] = {}
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)
        orders_this_tick = 0

        for sym, cfg in self.PARAMS.items():
            if orders_this_tick >= self.MAX_ORDERS_PER_TICK:
                break
            if sym not in state.order_depths:
                continue
            bid, ask = self._best_bid_ask(state, sym)
            if bid is None or ask is None:
                continue
            spread = ask - bid
            if spread <= 0 or spread > cfg["max_spread"]:
                continue

            mid = 0.5 * (bid + ask)
            last_mid = mem["last_mid"].get(sym, mid)
            d_mid = mid - last_mid
            mem["last_mid"][sym] = mid

            pos = state.position.get(sym, 0)
            buy_cap = max(0, self.POS_LIMIT - pos)
            sell_cap = max(0, self.POS_LIMIT + pos)

            ent = mem["entries"].get(sym)
            if ent:
                target_ts = ent["ts"] + 100 * ent["hold"]
                if state.timestamp >= target_ts:
                    if pos > 0 and sell_cap > 0:
                        q = min(pos, sell_cap)
                        result[sym].append(Order(sym, bid, -q))
                        orders_this_tick += 1
                    elif pos < 0 and buy_cap > 0:
                        q = min(-pos, buy_cap)
                        result[sym].append(Order(sym, ask, q))
                        orders_this_tick += 1
                    mem["entries"].pop(sym, None)
                    mem["last_trade_ts"][sym] = state.timestamp
                continue

            if pos != 0:
                continue
            last_trade = mem["last_trade_ts"].get(sym, -10**9)
            if state.timestamp - last_trade < 100 * self.COOLDOWN_TICKS:
                continue
            if abs(d_mid) < cfg["trigger"]:
                continue

            big = abs(d_mid) >= cfg["big_shock"]
            hold = self.HOLD_BIG if big else self.HOLD_DEFAULT
            qty_max = self._entry_size(d_mid, cfg["big_shock"], spread)

            if d_mid <= -cfg["trigger"]:
                qty = min(qty_max, buy_cap)
                if qty > 0:
                    result[sym].append(Order(sym, ask, qty))
                    mem["entries"][sym] = {"ts": state.timestamp, "hold": hold, "side": "BUY"}
                    mem["last_trade_ts"][sym] = state.timestamp
                    orders_this_tick += 1
            elif d_mid >= cfg["trigger"]:
                qty = min(qty_max, sell_cap)
                if qty > 0:
                    result[sym].append(Order(sym, bid, -qty))
                    mem["entries"][sym] = {"ts": state.timestamp, "hold": hold, "side": "SELL"}
                    mem["last_trade_ts"][sym] = state.timestamp
                    orders_this_tick += 1

        return dict(result), 0, self._save(mem)
