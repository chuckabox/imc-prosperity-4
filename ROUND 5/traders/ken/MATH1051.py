import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


class Trader:
    """
    Round 5 experimental trader:
    - Event-gated shock reversion.
    - Product whitelist bias toward strongest observed opportunities.
    - Short holding horizon with automatic flatten.
    """

    BASE_LIMIT = 0
    PRIORITY_LIMIT = 14
    HIGH_PRIORITY = {"PEBBLES_XL", "MICROCHIP_SQUARE", "PEBBLES_S", "MICROCHIP_OVAL"}
    TRADEABLE = HIGH_PRIORITY

    SHOCK_TRIGGER = 16.0
    BIG_SHOCK = 24.0
    HOLD_TICKS_DEFAULT = 1
    HOLD_TICKS_BIG = 2

    MAX_SPREAD = 12
    MAX_ORDERS_PER_TICK = 3
    COOLDOWN_TICKS = 4

    def _load_state(self, trader_data: str) -> Dict:
        if not trader_data:
            return {"last_mid": {}, "entries": {}, "last_ts": -1, "last_trade_ts": {}}
        try:
            state = json.loads(trader_data)
            state.setdefault("last_mid", {})
            state.setdefault("entries", {})
            state.setdefault("last_ts", -1)
            state.setdefault("last_trade_ts", {})
            return state
        except Exception:
            return {"last_mid": {}, "entries": {}, "last_ts": -1, "last_trade_ts": {}}

    def _save_state(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    @staticmethod
    def _best_bid_ask(state: TradingState, symbol: str) -> Tuple[int, int]:
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def _mid(self, state: TradingState, symbol: str) -> float:
        bid, ask = self._best_bid_ask(state, symbol)
        if bid is None or ask is None:
            return None
        return 0.5 * (bid + ask)

    def _position_limit(self, symbol: str) -> int:
        return self.PRIORITY_LIMIT if symbol in self.HIGH_PRIORITY else self.BASE_LIMIT

    def _entry_size(self, symbol: str, d_mid: float, spread: int) -> int:
        # Larger clip for stronger shocks and priority symbols.
        base = 2 if abs(d_mid) < self.BIG_SHOCK else 4
        if symbol in self.HIGH_PRIORITY:
            base += 2
        if spread <= 10:
            base += 1
        return max(1, min(10, base))

    def run(self, state: TradingState):
        mem = self._load_state(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            # New session/day reset.
            mem["last_mid"] = {}
            mem["entries"] = {}
            mem["last_trade_ts"] = {}
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)
        order_count = 0

        for symbol in state.order_depths.keys():
            if order_count >= self.MAX_ORDERS_PER_TICK:
                break
            if symbol not in self.TRADEABLE:
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
            lim = self._position_limit(symbol)
            buy_cap = max(0, lim - pos)
            sell_cap = max(0, lim + pos)

            # Exit logic for open event trade.
            ent = mem["entries"].get(symbol)
            if ent:
                entry_ts = ent.get("ts", state.timestamp)
                hold_ticks = ent.get("hold", self.HOLD_TICKS_DEFAULT)
                target_ts = entry_ts + 100 * hold_ticks
                if state.timestamp >= target_ts:
                    if pos > 0 and sell_cap > 0:
                        qty = min(pos, sell_cap)
                        result[symbol].append(Order(symbol, bid, -qty))
                        order_count += 1
                    elif pos < 0 and buy_cap > 0:
                        qty = min(-pos, buy_cap)
                        result[symbol].append(Order(symbol, ask, qty))
                        order_count += 1
                    mem["entries"].pop(symbol, None)
                    mem["last_trade_ts"][symbol] = state.timestamp
                    continue

            # Entry logic only when flat on that symbol.
            if pos != 0:
                continue
            last_trade_ts = mem["last_trade_ts"].get(symbol, -10**9)
            if state.timestamp - last_trade_ts < 100 * self.COOLDOWN_TICKS:
                continue
            if abs(d_mid) < self.SHOCK_TRIGGER:
                continue

            qty = self._entry_size(symbol, d_mid, spread)
            hold_ticks = self.HOLD_TICKS_BIG if abs(d_mid) >= self.BIG_SHOCK else self.HOLD_TICKS_DEFAULT

            # Reversion: buy sharp down move, sell sharp up move.
            if d_mid <= -self.SHOCK_TRIGGER and buy_cap > 0:
                q = min(qty, buy_cap)
                result[symbol].append(Order(symbol, ask, q))
                mem["entries"][symbol] = {"ts": state.timestamp, "hold": hold_ticks, "side": "BUY"}
                mem["last_trade_ts"][symbol] = state.timestamp
                order_count += 1
            elif d_mid >= self.SHOCK_TRIGGER and sell_cap > 0:
                q = min(qty, sell_cap)
                result[symbol].append(Order(symbol, bid, -q))
                mem["entries"][symbol] = {"ts": state.timestamp, "hold": hold_ticks, "side": "SELL"}
                mem["last_trade_ts"][symbol] = state.timestamp
                order_count += 1

        return dict(result), 0, self._save_state(mem)
