from __future__ import annotations

from typing import Dict, List, Tuple

from datamodel import Order, TradingState


LIMITS = {"VELVETFRUIT_EXTRACT": 200, "HYDROGEL_PACK": 200}


def best_bid_ask(od):
    bb = max(od.buy_orders) if od.buy_orders else None
    ba = min(od.sell_orders) if od.sell_orders else None
    return bb, ba


class Trader:
    def __init__(self) -> None:
        self.target = {"VELVETFRUIT_EXTRACT": 0, "HYDROGEL_PACK": 0}
        self.target_expire = {"VELVETFRUIT_EXTRACT": -1, "HYDROGEL_PACK": -1}
        self.prev_ts = -1

    def _set_target(self, sym: str, qty: int, ts: int, hold: int) -> None:
        lim = LIMITS[sym]
        self.target[sym] = max(-lim, min(lim, qty))
        self.target_expire[sym] = ts + hold

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        if self.prev_ts >= 0 and state.timestamp < self.prev_ts:
            self.target = {"VELVETFRUIT_EXTRACT": 0, "HYDROGEL_PACK": 0}
            self.target_expire = {"VELVETFRUIT_EXTRACT": -1, "HYDROGEL_PACK": -1}
        self.prev_ts = state.timestamp

        for sym in ["VELVETFRUIT_EXTRACT", "HYDROGEL_PACK"]:
            trades = state.market_trades.get(sym, []) if hasattr(state, "market_trades") else []
            for tr in trades:
                buyer = getattr(tr, "buyer", "")
                seller = getattr(tr, "seller", "")
                if sym == "VELVETFRUIT_EXTRACT":
                    if buyer in {"Mark 14", "Mark 01", "Mark 49"}:
                        self._set_target(sym, -120, state.timestamp, 12000)
                    elif seller in {"Mark 14", "Mark 49"}:
                        self._set_target(sym, 120, state.timestamp, 12000)
                else:
                    if buyer == "Mark 38":
                        self._set_target(sym, -140, state.timestamp, 16000)
                    elif buyer == "Mark 14":
                        self._set_target(sym, 140, state.timestamp, 16000)

        result: Dict[str, List[Order]] = {}
        for sym in ["VELVETFRUIT_EXTRACT", "HYDROGEL_PACK"]:
            od = state.order_depths.get(sym)
            if not od:
                continue
            bb, ba = best_bid_ask(od)
            if bb is None or ba is None:
                continue

            if state.timestamp >= self.target_expire[sym]:
                self.target[sym] = 0

            pos = int(state.position.get(sym, 0))
            diff = self.target[sym] - pos
            if diff > 0:
                result.setdefault(sym, []).append(Order(sym, int(ba), diff))
            elif diff < 0:
                result.setdefault(sym, []).append(Order(sym, int(bb), diff))

        return result, 0, ""

