"""trader_vev_only_test.py — sanity check that VEV IV/RV alpha is harvestable.

ONLY trades VEV_5200 (and optionally a few others). No HYDROGEL, no hedge.
If this is positive, the long-gamma + IV-underpricing thesis is live and
v4_vev should layer it on top of HYDROGEL. If this is negative, the
'alpha' is illusory at our trading size and we shouldn't add complexity.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

VFE = "VELVETFRUIT_EXTRACT"
TIMESTAMP_UNITS_PER_DAY = 1_000_000


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


class Trader:
    LIMITS = {f"VEV_{k}": 60 for k in (4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500)}
    ACTIVE = ["VEV_5200", "VEV_5300"]
    SIGMA = 0.018           # conservative vs realized 0.0215
    MIN_EDGE = 5.0
    MAX_POS = 40            # below the 60 limit for safety
    SIZE_PER_TICK = 5       # how much to take per tick when underpriced

    def __init__(self):
        self.history: Dict = {}

    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("last_ts", -1)
        self.history.setdefault("day", 0)
        ts = state.timestamp
        last = int(self.history["last_ts"])
        if 0 <= ts < last:
            self.history["day"] = int(self.history["day"]) + 1
        self.history["last_ts"] = ts

    def _tte_days(self, ts: int) -> float:
        day = int(self.history.get("day", 0))
        return max(0.01, (8 - day) - ts / TIMESTAMP_UNITS_PER_DAY)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    @staticmethod
    def _mid(depth: OrderDepth) -> Optional[float]:
        bb, ba = Trader._top(depth)
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        if VFE not in state.order_depths:
            return result, 0, json.dumps(self.history)
        vfe_mid = self._mid(state.order_depths[VFE])
        if vfe_mid is None:
            return result, 0, json.dumps(self.history)

        T = self._tte_days(state.timestamp)
        for sym in self.ACTIVE:
            if sym not in state.order_depths:
                continue
            K = int(sym.split("_")[1])
            depth = state.order_depths[sym]
            bb, ba = self._top(depth)
            if ba is None:
                continue
            fair = bs_call(vfe_mid, K, T, self.SIGMA)
            pos = state.position.get(sym, 0)
            # ONLY BUY (alpha = options underpriced vs realized vol)
            if ba < fair - self.MIN_EDGE and pos < self.MAX_POS:
                ask_size = -depth.sell_orders[ba]
                size = min(self.MAX_POS - pos, ask_size, self.SIZE_PER_TICK)
                if size > 0:
                    result.setdefault(sym, []).append(Order(sym, ba, size))

        return result, 0, json.dumps(self.history)
