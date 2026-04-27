from __future__ import annotations

from typing import Dict, List, Tuple

from datamodel import Order, TradingState


SYMS = [
    ("VELVETFRUIT_EXTRACT", 200),
    ("VEV_5000", 100),
    ("VEV_5200", 100),
    ("VEV_5300", 100),
    ("VEV_5400", 100),
]


def best_bid_ask(od):
    bb = max(od.buy_orders) if od.buy_orders else None
    ba = min(od.sell_orders) if od.sell_orders else None
    return bb, ba


def mid(od):
    bb, ba = best_bid_ask(od)
    if bb is None or ba is None:
        return None
    return (bb + ba) / 2.0


class Trader:
    def __init__(self) -> None:
        self.prev_ts = -1
        self.open_mid: dict[str, float] = {}
        self.low_mid: dict[str, float] = {}

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        if self.prev_ts >= 0 and state.timestamp < self.prev_ts:
            self.open_mid = {}
            self.low_mid = {}
        self.prev_ts = state.timestamp

        result: Dict[str, List[Order]] = {}

        for sym, lim in SYMS:
            od = state.order_depths.get(sym)
            if not od:
                continue
            bb, ba = best_bid_ask(od)
            m = mid(od)
            if bb is None or ba is None or m is None:
                continue

            if sym not in self.open_mid:
                self.open_mid[sym] = m
                self.low_mid[sym] = m
            self.low_mid[sym] = min(self.low_mid[sym], m)
            pos = int(state.position.get(sym, 0))

            target = pos
            if state.timestamp <= 10000:
                if m >= self.open_mid[sym] - 4:
                    target = -lim
            elif state.timestamp <= 50000:
                if pos < 0:
                    # keep short until decent selloff happened
                    drop = self.open_mid[sym] - m
                    if drop < 0.6 * (self.open_mid[sym] - self.low_mid[sym] + 1):
                        target = -lim
                    else:
                        target = 0
                else:
                    target = 0
            else:
                target = 0

            diff = target - pos
            if diff > 0:
                result.setdefault(sym, []).append(Order(sym, int(ba), diff))
            elif diff < 0:
                result.setdefault(sym, []).append(Order(sym, int(bb), diff))

        return result, 0, ""

