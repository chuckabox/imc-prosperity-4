import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


class Trader:
    FAMILY_PREFIXES = [
        "PEBBLES",
        "SNACKPACK",
        "UV_VISOR",
        "GALAXY_SOUNDS",
        "MICROCHIP",
        "TRANSLATOR",
        "SLEEP_POD",
        "OXYGEN_SHAKE",
        "PANEL",
        "ROBOT",
    ]

    FAMILY_LIMITS = {
        "PEBBLES": 45,
        "MICROCHIP": 40,
        "ROBOT": 35,
        "OXYGEN_SHAKE": 30,
        "PANEL": 30,
        "GALAXY_SOUNDS": 25,
        "TRANSLATOR": 25,
        "SLEEP_POD": 25,
        "UV_VISOR": 25,
        "SNACKPACK": 20,
    }

    DEFAULT_LIMIT = 20
    TAKE_CLIP = 10
    TRIGGER_MOVE = 8.0

    def _load(self, trader_data: str) -> Dict:
        if not trader_data:
            return {"last_mid": {}, "last_ts": -1, "day_idx": 0, "entry_ts": {}}
        try:
            out = json.loads(trader_data)
            out.setdefault("last_mid", {})
            out.setdefault("last_ts", -1)
            out.setdefault("day_idx", 0)
            out.setdefault("entry_ts", {})
            return out
        except Exception:
            return {"last_mid": {}, "last_ts": -1, "day_idx": 0, "entry_ts": {}}

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _family(self, symbol: str) -> str:
        for prefix in self.FAMILY_PREFIXES:
            if symbol.startswith(prefix + "_"):
                return prefix
        return symbol.split("_", 1)[0]

    def _best_bid_ask(self, state: TradingState, symbol: str) -> Tuple[int, int]:
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def _mid(self, state: TradingState, symbol: str) -> float:
        bid, ask = self._best_bid_ask(state, symbol)
        if bid is None or ask is None:
            return None
        return 0.5 * (bid + ask)

    def _caps(self, symbol: str, position: Dict[str, int]) -> Tuple[int, int, int]:
        fam = self._family(symbol)
        lim = self.FAMILY_LIMITS.get(fam, self.DEFAULT_LIMIT)
        pos = position.get(symbol, 0)
        buy_cap = max(0, lim - pos)
        sell_cap = max(0, lim + pos)
        return lim, buy_cap, sell_cap

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["day_idx"] += 1
            mem["last_mid"] = {}
            mem["entry_ts"] = {}
        mem["last_ts"] = state.timestamp

        mids: Dict[str, float] = {}
        family_to_symbols: Dict[str, List[str]] = defaultdict(list)
        for symbol in state.order_depths.keys():
            m = self._mid(state, symbol)
            if m is None:
                continue
            mids[symbol] = m
            family_to_symbols[self._family(symbol)].append(symbol)

        result: Dict[str, List[Order]] = defaultdict(list)

        for symbol, mid in mids.items():
            bid, ask = self._best_bid_ask(state, symbol)
            if bid is None or ask is None:
                continue
            spread = max(1, ask - bid)
            lim, buy_cap, sell_cap = self._caps(symbol, state.position)
            pos = state.position.get(symbol, 0)

            last_mid = mem["last_mid"].get(symbol, mid)
            d_mid = mid - last_mid
            mem["last_mid"][symbol] = mid

            entry_ts = mem["entry_ts"].get(symbol, -1)

            # Exit leg: close one-tick reversion trade on the next timestamp.
            if pos != 0 and entry_ts >= 0 and state.timestamp > entry_ts:
                if pos > 0 and sell_cap > 0:
                    result[symbol].append(Order(symbol, bid, -min(abs(pos), sell_cap)))
                elif pos < 0 and buy_cap > 0:
                    result[symbol].append(Order(symbol, ask, min(abs(pos), buy_cap)))
                mem["entry_ts"][symbol] = -1
                continue

            # Entry leg: only trade large one-tick shocks.
            if pos == 0:
                move_trigger = max(self.TRIGGER_MOVE, 1.2 * spread)
                if d_mid <= -move_trigger and buy_cap > 0:
                    qty = min(self.TAKE_CLIP, buy_cap, max(2, int(abs(d_mid) * 0.9)))
                    result[symbol].append(Order(symbol, ask, qty))
                    mem["entry_ts"][symbol] = state.timestamp
                elif d_mid >= move_trigger and sell_cap > 0:
                    qty = min(self.TAKE_CLIP, sell_cap, max(2, int(abs(d_mid) * 0.9)))
                    result[symbol].append(Order(symbol, bid, -qty))
                    mem["entry_ts"][symbol] = state.timestamp

        return dict(result), 0, self._save(mem)