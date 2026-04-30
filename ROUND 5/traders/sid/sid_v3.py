"""sid/sid_v3.py — drops RECTANGLE, adds PEBBLES_M.

v1 (+150.92): TRIANGLE +306, RECTANGLE -155
v2 (-1344.08): TRIANGLE +306, RECTANGLE -1650 (raised trigger backfired hard)

Diagnosis: MICROCHIP_RECTANGLE has ac1 ~ 0 in raw data. Raising trigger doesn't
catch more reversion — it filters TO momentum-driven moves which DON'T revert.
Per-trade loss went from -0.16 to -2.61 with higher trigger. No threshold
saves this product; drop it.

v3 changes:
  - REMOVE MICROCHIP_RECTANGLE (no reliable reversion alpha)
  - KEEP MICROCHIP_TRIANGLE (proven winner, no parameter changes)
  - ADD PEBBLES_M (different family; ac1 -0.005; 1.5x-avg trigger to avoid
    same momentum trap that killed RECTANGLE at high triggers)
  - REVERT COOLDOWN_TICKS to 4 (the 3 didn't help)

Per algo.md, position limit = 10 per product. Two products at 10 each = 20
total exposure — same as v1 footprint, but with the loss-maker swapped for
a diversifying winner candidate.
"""

import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


class Trader:
    PARAMS = {
        "MICROCHIP_TRIANGLE": {
            "trigger": 13.0,    # unchanged from v1/v2 — proven profitable
            "big_shock": 22.0,
            "max_spread": 12,
        },
        "PEBBLES_M": {
            # New. avg_dmid 12.08, spread_med 13, mid_std 688, shock_14 = 10,988.
            # Trigger 18 ≈ 1.5x avg; conservative because trigger=16 on RECTANGLE
            # exposed momentum, not reversion. Bigger trigger = less of either.
            # If PEBBLES_M is reversion-positive, this should fire less but win
            # more per trade.
            "trigger": 18.0,
            "big_shock": 28.0,
            "max_spread": 14,
        },
    }

    POS_LIMIT = 10
    HOLD_DEFAULT = 1
    HOLD_BIG = 2
    COOLDOWN_TICKS = 4          # reverted from v2's 3
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
