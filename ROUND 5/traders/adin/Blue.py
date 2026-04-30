import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


class Trader:
    """
    Blue: shock-reversion trader for the pebbles and microchip families.

    Per-symbol configs come from a sweep over round-5 day 2-4 historical data
    measuring the post-shock K-tick mid drift versus the round-trip spread cost.
    Only configs with positive empirical EV per trade survive the table below.

    Notes:
    - PEBBLES_XL and MICROCHIP_RECTANGLE show momentum, not reversion, and are
      excluded.
    - MICROCHIP_OVAL after a +40 jump is the cleanest signal in the data
      (~8 ticks of expected mid revert against an 8-tick spread, 37 events
      across the 3 days). Sell side only — the buy side after a -40 dip is
      a downtrend, not a revert.
    - Other products (SQUARE, TRIANGLE, PEBBLES_M) show small positive EV at
      large thresholds. They run with smaller size and tighter cooldown.
    - Exits cross the spread to guarantee unwind within the hold window.
    """

    LIMIT = 10

    # symbol -> (shock_thresh, hold_ticks, allow_buy, allow_sell, size, max_spread)
    CFG: Dict[str, Tuple[int, int, bool, bool, int, int]] = {
        "MICROCHIP_OVAL": (17, 1, False, True, 10, 10),
    }

    SHOCK_COOLDOWN = 2
    MAX_ORDERS_PER_TICK = 4

    def _load(self, td: str) -> Dict:
        if not td:
            return {"last_mid": {}, "entries": {}, "last_trade_ts": {}, "last_ts": -1}
        try:
            m = json.loads(td)
            for k, v in (("last_mid", {}), ("entries", {}), ("last_trade_ts", {}), ("last_ts", -1)):
                m.setdefault(k, v)
            return m
        except Exception:
            return {"last_mid": {}, "entries": {}, "last_trade_ts": {}, "last_ts": -1}

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    @staticmethod
    def _best_bid_ask(state: TradingState, symbol: str):
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["last_mid"] = {}
            mem["entries"] = {}
            mem["last_trade_ts"] = {}
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)
        n_orders = 0

        for sym, (thresh, hold, allow_buy, allow_sell, size, max_sp) in self.CFG.items():
            if n_orders >= self.MAX_ORDERS_PER_TICK:
                break
            if sym not in state.order_depths:
                continue
            bid, ask = self._best_bid_ask(state, sym)
            if bid is None:
                continue
            spread = ask - bid
            if spread <= 0 or spread > max_sp:
                continue

            mid = 0.5 * (bid + ask)
            last_mid = mem["last_mid"].get(sym, mid)
            d_mid = mid - last_mid
            mem["last_mid"][sym] = mid

            pos = state.position.get(sym, 0)
            buy_cap = max(0, self.LIMIT - pos)
            sell_cap = max(0, self.LIMIT + pos)

            ent = mem["entries"].get(sym)
            if ent:
                target_ts = ent["ts"] + 100 * ent["hold"]
                if state.timestamp >= target_ts:
                    if pos > 0 and sell_cap > 0:
                        q = min(pos, sell_cap)
                        result[sym].append(Order(sym, bid, -q))
                        n_orders += 1
                    elif pos < 0 and buy_cap > 0:
                        q = min(-pos, buy_cap)
                        result[sym].append(Order(sym, ask, q))
                        n_orders += 1
                    mem["entries"].pop(sym, None)
                    mem["last_trade_ts"][sym] = state.timestamp
                continue

            if pos != 0:
                continue
            last_trade = mem["last_trade_ts"].get(sym, -10**9)
            if state.timestamp - last_trade < 100 * self.SHOCK_COOLDOWN:
                continue
            if abs(d_mid) < thresh:
                continue

            if d_mid <= -thresh and allow_buy and buy_cap > 0:
                q = min(size, buy_cap)
                result[sym].append(Order(sym, ask, q))
                mem["entries"][sym] = {"ts": state.timestamp, "hold": hold, "side": "BUY"}
                mem["last_trade_ts"][sym] = state.timestamp
                n_orders += 1
            elif d_mid >= thresh and allow_sell and sell_cap > 0:
                q = min(size, sell_cap)
                result[sym].append(Order(sym, bid, -q))
                mem["entries"][sym] = {"ts": state.timestamp, "hold": hold, "side": "SELL"}
                mem["last_trade_ts"][sym] = state.timestamp
                n_orders += 1

        return dict(result), 0, self._save(mem)
