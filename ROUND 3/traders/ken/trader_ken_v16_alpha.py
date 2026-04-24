"""trader_ken_v16_alpha.py — alpha-first voucher inefficiency trader.

Key idea:
- Ignore noisy broad market-making.
- Trade only when vouchers deviate from empirical fair value:
    fair = intrinsic(VFE, K) + premium_ema(K)
- Add stale-order taker trigger to capture lagging books.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
ACTIVE_STRIKES = [5000, 5100, 5200, 5300, 5400]
ACTIVE_SYMBOLS = [f"VEV_{k}" for k in ACTIVE_STRIKES]


class Trader:
    ENABLE_HYDROGEL = True
    ENABLE_VFE_MM = True
    ENABLE_VEV_ALPHA = True

    LIMITS: Dict[str, int] = {
        HYDROGEL: 80,
        VFE: 80,
        **{s: 60 for s in ACTIVE_SYMBOLS},
    }

    HP_ANCHOR = 9993.0
    HP_SIZE = 18
    HP_EDGE = 2

    VFE_ALPHA = 0.2
    VFE_EDGE = 2
    VFE_SIZE = 12

    PREM_ALPHA = 0.05
    TAKE_UNDER = 1.2
    TAKE_OVER = 1.2
    MAKER_EDGE = 2.0
    MAKER_SIZE = 6
    STALE_TICKS = 4
    STALE_BONUS = 0.8

    STRIKE_CAP: Dict[int, int] = {
        5000: 32,
        5100: 44,
        5200: 48,
        5300: 44,
        5400: 36,
    }

    PREM_INIT: Dict[int, float] = {
        5000: 6.0,
        5100: 19.0,
        5200: 49.0,
        5300: 48.0,
        5400: 17.0,
    }

    PREM_BOUNDS: Dict[int, Tuple[float, float]] = {
        5000: (2.0, 14.0),
        5100: (10.0, 30.0),
        5200: (30.0, 72.0),
        5300: (30.0, 72.0),
        5400: (8.0, 30.0),
    }

    def __init__(self):
        self.history: Dict = {}

    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("prem", {})
        self.history.setdefault("last_book", {})
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("vfe_ewma", None)
        for k in ACTIVE_STRIKES:
            self.history["prem"].setdefault(str(k), self.PREM_INIT[k])
            self.history["last_book"].setdefault(
                str(k), {"bb": None, "ba": None, "stale": 0}
            )

    def _save_state(self) -> str:
        return json.dumps(self.history)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int], int, int]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        bv = depth.buy_orders[bb] if bb is not None else 0
        av = -depth.sell_orders[ba] if ba is not None else 0
        return bb, ba, bv, av

    def _hydrogel_logic(self, state: TradingState) -> List[Order]:
        d = state.order_depths.get(HYDROGEL)
        if d is None:
            return []
        bb, ba, _, _ = self._top(d)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0
        prev = self.history.get("hp_ewma")
        ewma = mid if prev is None else 0.9 * prev + 0.1 * mid
        self.history["hp_ewma"] = ewma
        fair = 0.6 * ewma + 0.4 * self.HP_ANCHOR

        pos = state.position.get(HYDROGEL, 0)
        lim = self.LIMITS[HYDROGEL]
        out: List[Order] = []
        if ba <= fair - self.HP_EDGE and pos < lim:
            sz = min(self.HP_SIZE, lim - pos, -d.sell_orders[ba])
            if sz > 0:
                out.append(Order(HYDROGEL, ba, sz))
        if bb >= fair + self.HP_EDGE and pos > -lim:
            sz = min(self.HP_SIZE, lim + pos, d.buy_orders[bb])
            if sz > 0:
                out.append(Order(HYDROGEL, bb, -sz))
        return out

    def _vev_alpha_logic(self, state: TradingState) -> List[Order]:
        vfe_depth = state.order_depths.get(VFE)
        if vfe_depth is None:
            return []
        vbb, vba, _, _ = self._top(vfe_depth)
        if vbb is None or vba is None:
            return []
        s = (vbb + vba) / 2.0
        out: List[Order] = []

        for k in ACTIVE_STRIKES:
            sym = f"VEV_{k}"
            d = state.order_depths.get(sym)
            if d is None:
                continue
            bb, ba, _, _ = self._top(d)
            if bb is None or ba is None:
                continue
            mid = (bb + ba) / 2.0

            intrinsic = max(s - k, 0.0)
            obs_prem = mid - intrinsic
            prem_key = str(k)
            prev_prem = float(self.history["prem"][prem_key])
            prem = (1.0 - self.PREM_ALPHA) * prev_prem + self.PREM_ALPHA * obs_prem
            lo, hi = self.PREM_BOUNDS[k]
            prem = max(lo, min(hi, prem))
            self.history["prem"][prem_key] = prem
            fair = intrinsic + prem

            # stale quote detector
            book = self.history["last_book"][prem_key]
            if book["bb"] == bb and book["ba"] == ba:
                book["stale"] += 1
            else:
                book["stale"] = 0
                book["bb"] = bb
                book["ba"] = ba
            stale = int(book["stale"])
            stale_edge = self.STALE_BONUS if stale >= self.STALE_TICKS else 0.0

            pos = state.position.get(sym, 0)
            lim = min(self.LIMITS[sym], self.STRIKE_CAP[k])

            under_gap = fair - ba
            over_gap = bb - fair

            # aggressive taker alpha
            if under_gap >= self.TAKE_UNDER - stale_edge and pos < lim:
                sz = min(lim - pos, -d.sell_orders[ba], 12)
                if sz > 0:
                    out.append(Order(sym, ba, sz))
                    pos += sz

            if over_gap >= self.TAKE_OVER - stale_edge and pos > -lim:
                sz = min(lim + pos, d.buy_orders[bb], 12)
                if sz > 0:
                    out.append(Order(sym, bb, -sz))
                    pos -= sz

            # small maker around fair to monetize spread without huge inventory
            qbid = int(round(fair - self.MAKER_EDGE))
            qask = int(round(fair + self.MAKER_EDGE))
            if qbid >= qask:
                qbid = qask - 1
            room_long = max(0, lim - pos)
            room_short = max(0, lim + pos)
            if room_long > 0:
                out.append(Order(sym, qbid, min(self.MAKER_SIZE, room_long)))
            if room_short > 0:
                out.append(Order(sym, qask, -min(self.MAKER_SIZE, room_short)))

        return out

    def _vfe_mm_logic(self, state: TradingState) -> List[Order]:
        d = state.order_depths.get(VFE)
        if d is None:
            return []
        bb, ba, _, _ = self._top(d)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0
        prev = self.history.get("vfe_ewma")
        ewma = mid if prev is None else (1.0 - self.VFE_ALPHA) * prev + self.VFE_ALPHA * mid
        self.history["vfe_ewma"] = ewma
        fair = ewma
        pos = state.position.get(VFE, 0)
        lim = self.LIMITS[VFE]
        out: List[Order] = []
        if ba <= fair - self.VFE_EDGE and pos < lim:
            sz = min(self.VFE_SIZE, lim - pos, -d.sell_orders[ba])
            if sz > 0:
                out.append(Order(VFE, ba, sz))
        if bb >= fair + self.VFE_EDGE and pos > -lim:
            sz = min(self.VFE_SIZE, lim + pos, d.buy_orders[bb])
            if sz > 0:
                out.append(Order(VFE, bb, -sz))
        return out

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        if self.ENABLE_HYDROGEL:
            for o in self._hydrogel_logic(state):
                result.setdefault(o.symbol, []).append(o)
        if self.ENABLE_VFE_MM:
            for o in self._vfe_mm_logic(state):
                result.setdefault(o.symbol, []).append(o)
        if self.ENABLE_VEV_ALPHA:
            for o in self._vev_alpha_logic(state):
                result.setdefault(o.symbol, []).append(o)
        return result, 0, self._save_state()

