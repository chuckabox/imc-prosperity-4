import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState

class Trader:
    SYMBOLS = {'PANEL_2X4', 'SNACKPACK_PISTACHIO', 'SNACKPACK_STRAWBERRY', 'SLEEP_POD_NYLON', 'UV_VISOR_AMBER'}
    LIMITS = {'PANEL_2X4': 14, 'SLEEP_POD_NYLON': 14, 'SNACKPACK_PISTACHIO': 14, 'UV_VISOR_AMBER': 14, 'SNACKPACK_STRAWBERRY': 14}
    MM_EDGE = 2
    MM_CLIP = 2
    INV_SKEW = 0.10
    SHOCK_TRIGGER = 14.0
    TAKE_CLIP = 5
    COOLDOWN_TICKS = 3
    MAX_SPREAD = 14

    def _load(self, trader_data: str) -> Dict:
        if not trader_data:
            return {"last_mid": {}, "last_trade_ts": {}, "last_ts": -1}
        try:
            m = json.loads(trader_data)
            m.setdefault("last_mid", {})
            m.setdefault("last_trade_ts", {})
            m.setdefault("last_ts", -1)
            return m
        except Exception:
            return {"last_mid": {}, "last_trade_ts": {}, "last_ts": -1}

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    @staticmethod
    def _best_bid_ask(state: TradingState, symbol: str) -> Tuple[int, int]:
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["last_mid"] = {}
            mem["last_trade_ts"] = {}
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)
        for symbol in self.SYMBOLS:
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
            if buy_cap <= 0 and sell_cap <= 0:
                continue

            fair = mid - self.INV_SKEW * pos
            mm_bid = int(fair - self.MM_EDGE)
            mm_ask = int(fair + self.MM_EDGE)
            if mm_bid >= mm_ask:
                mm_ask = mm_bid + 1
            if buy_cap > 0:
                result[symbol].append(Order(symbol, mm_bid, min(self.MM_CLIP, buy_cap)))
            if sell_cap > 0:
                result[symbol].append(Order(symbol, mm_ask, -min(self.MM_CLIP, sell_cap)))

            last_trade = mem["last_trade_ts"].get(symbol, -10**9)
            if state.timestamp - last_trade >= 100 * self.COOLDOWN_TICKS:
                if d_mid <= -self.SHOCK_TRIGGER and buy_cap > 0:
                    q = min(self.TAKE_CLIP, buy_cap)
                    result[symbol].append(Order(symbol, ask, q))
                    mem["last_trade_ts"][symbol] = state.timestamp
                elif d_mid >= self.SHOCK_TRIGGER and sell_cap > 0:
                    q = min(self.TAKE_CLIP, sell_cap)
                    result[symbol].append(Order(symbol, bid, -q))
                    mem["last_trade_ts"][symbol] = state.timestamp

        return dict(result), 0, self._save(mem)
