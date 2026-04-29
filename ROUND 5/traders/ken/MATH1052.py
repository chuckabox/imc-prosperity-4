import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


class Trader:
    """
    MATH1052: profit-first conservative variant.
    Focus only on symbols that remained strongest in prior run and avoid day-4 regime.
    """

    TRADEABLE = {"PEBBLES_XL", "MICROCHIP_OVAL"}
    LIMITS = {"PEBBLES_XL": 16, "MICROCHIP_OVAL": 16}

    SHOCK_TRIGGER = 14.0
    BIG_SHOCK = 24.0
    HOLD_DEFAULT = 1
    HOLD_BIG = 2
    COOLDOWN_TICKS = 4

    MAX_SPREAD = 12
    MAX_ORDERS_PER_TICK = 2

    def _load(self, trader_data: str) -> Dict:
        if not trader_data:
            return {"last_mid": {}, "entries": {}, "last_trade_ts": {}, "last_ts": -1, "day_idx": 0}
        try:
            m = json.loads(trader_data)
            m.setdefault("last_mid", {})
            m.setdefault("entries", {})
            m.setdefault("last_trade_ts", {})
            m.setdefault("last_ts", -1)
            m.setdefault("day_idx", 0)
            return m
        except Exception:
            return {"last_mid": {}, "entries": {}, "last_trade_ts": {}, "last_ts": -1, "day_idx": 0}

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    @staticmethod
    def _best_bid_ask(state: TradingState, symbol: str) -> Tuple[int, int]:
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def _entry_size(self, d_mid: float, spread: int) -> int:
        size = 2 if abs(d_mid) < self.BIG_SHOCK else 4
        if spread <= 8:
            size += 1
        return min(8, max(1, size))

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

        # Hard regime gate: preserve gains by skipping day 4-like session.
        if mem["day_idx"] >= 2:
            return {}, 0, self._save(mem)

        for symbol in self.TRADEABLE:
            if orders_this_tick >= self.MAX_ORDERS_PER_TICK:
                break
            if symbol not in state.order_depths:
                continue

            bid, ask = self._best_bid_ask(state, symbol)
            if bid is None or ask is None:
                continue
            spread = ask - bid
            if spread <= 0 or spread > self.MAX_SPREAD:
                continue

            mid = 0.5 * (bid + ask)
            last_mid = mem["last_mid"].get(symbol, mid)
            d_mid = mid - last_mid
            mem["last_mid"][symbol] = mid

            pos = state.position.get(symbol, 0)
            lim = self.LIMITS.get(symbol, 10)
            buy_cap = max(0, lim - pos)
            sell_cap = max(0, lim + pos)

            ent = mem["entries"].get(symbol)
            if ent:
                target_ts = ent["ts"] + 100 * ent["hold"]
                if state.timestamp >= target_ts:
                    if pos > 0 and sell_cap > 0:
                        q = min(pos, sell_cap)
                        result[symbol].append(Order(symbol, bid, -q))
                        orders_this_tick += 1
                    elif pos < 0 and buy_cap > 0:
                        q = min(-pos, buy_cap)
                        result[symbol].append(Order(symbol, ask, q))
                        orders_this_tick += 1
                    mem["entries"].pop(symbol, None)
                    mem["last_trade_ts"][symbol] = state.timestamp
                continue

            if pos != 0:
                continue
            last_trade = mem["last_trade_ts"].get(symbol, -10**9)
            if state.timestamp - last_trade < 100 * self.COOLDOWN_TICKS:
                continue
            if abs(d_mid) < self.SHOCK_TRIGGER:
                continue

            hold = self.HOLD_BIG if abs(d_mid) >= self.BIG_SHOCK else self.HOLD_DEFAULT
            qty = min(self._entry_size(d_mid, spread), buy_cap if d_mid < 0 else sell_cap)
            if qty <= 0:
                continue

            if d_mid <= -self.SHOCK_TRIGGER and buy_cap > 0:
                result[symbol].append(Order(symbol, ask, qty))
                mem["entries"][symbol] = {"ts": state.timestamp, "hold": hold, "side": "BUY"}
                mem["last_trade_ts"][symbol] = state.timestamp
                orders_this_tick += 1
            elif d_mid >= self.SHOCK_TRIGGER and sell_cap > 0:
                result[symbol].append(Order(symbol, bid, -qty))
                mem["entries"][symbol] = {"ts": state.timestamp, "hold": hold, "side": "SELL"}
                mem["last_trade_ts"][symbol] = state.timestamp
                orders_this_tick += 1

        return dict(result), 0, self._save(mem)
