from __future__ import annotations

import math
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


LIMITS = {"HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200}


def best_bid_ask(od):
    bb = max(od.buy_orders) if od.buy_orders else None
    ba = min(od.sell_orders) if od.sell_orders else None
    return bb, ba


class Trader:
    def __init__(self) -> None:
        self.ema = {"HYDROGEL_PACK": 9990.0, "VELVETFRUIT_EXTRACT": 5250.0}
        self.alpha = {"HYDROGEL_PACK": 0.015, "VELVETFRUIT_EXTRACT": 0.02}

    def _pos(self, state, sym):
        return int(state.position.get(sym, 0))

    def _fair(self, sym, od):
        bb, ba = best_bid_ask(od)
        if bb is not None and ba is not None:
            mid = (bb + ba) / 2.0
            self.ema[sym] = (1 - self.alpha[sym]) * self.ema[sym] + self.alpha[sym] * mid
        return self.ema[sym]

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result: Dict[str, List[Order]] = {}

        for sym in ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"]:
            od = state.order_depths.get(sym)
            if not od:
                continue
            bb, ba = best_bid_ask(od)
            if bb is None or ba is None:
                continue

            fair = self._fair(sym, od)
            pos = self._pos(state, sym)
            lim = LIMITS[sym]
            base_size = 20 if sym == "VELVETFRUIT_EXTRACT" else 25
            make_edge = 2 if sym == "VELVETFRUIT_EXTRACT" else 4
            take_edge = 3 if sym == "VELVETFRUIT_EXTRACT" else 5

            orders: List[Order] = []

            # Aggressive take only when clearly cheap/rich
            if ba <= fair - take_edge and pos < lim:
                qty = min(base_size, lim - pos)
                if qty > 0:
                    orders.append(Order(sym, int(ba), qty))
            if bb >= fair + take_edge and pos > -lim:
                qty = min(base_size, pos + lim)
                if qty > 0:
                    orders.append(Order(sym, int(bb), -qty))

            # Passive inside spread, skewed by inventory
            skew = pos / lim
            bid_px = min(ba - 1, int(math.floor(fair - make_edge - 2 * skew)))
            ask_px = max(bb + 1, int(math.ceil(fair + make_edge - 2 * skew)))
            bid_qty = min(base_size, lim - pos)
            ask_qty = min(base_size, pos + lim)

            if bid_qty > 0 and bid_px > 0 and bid_px < ba:
                orders.append(Order(sym, bid_px, bid_qty))
            if ask_qty > 0 and ask_px > bb:
                orders.append(Order(sym, ask_px, -ask_qty))

            if orders:
                result[sym] = orders

        return result, 0, ""

