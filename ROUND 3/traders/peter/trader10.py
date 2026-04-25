"""trader10.py - Simple stable MM for HYDROGEL_PACK + VELVETFRUIT_EXTRACT.

No options trading. Vouchers ignored (too complex, unstable).

Design (validated D0/D1/D2):
  - Single OBI-aware market-making core for both delta-1 products.
  - Quote at best-bid+1 / best-ask-1 (top-of-book improvement) for fills.
  - EWMA mid as fair value, take asym edges, skew/flatten by inventory.
  - VFE adds a slow trend bias from rolling slope.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState


HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"


class Trader:
    LIMITS = {HYDROGEL: 80, VFE: 80}

    # ---- HP ----
    HP_EWMA_ALPHA = 0.20
    HP_TAKE_EDGE = 1
    HP_OBI_THRESHOLD = 0.10
    HP_NEUTRAL_FRONT = 12
    HP_NEUTRAL_SECOND = 12
    HP_LEAN_AGG = 30
    HP_LEAN_DEF = 6
    HP_LEAN_OFFSET = 2
    HP_SKEW_SOFT = 25
    HP_SKEW_HARD = 50
    HP_FLATTEN_HARD = 70

    # ---- VFE ----
    VFE_EWMA_ALPHA = 0.35
    VFE_TAKE_EDGE = 1
    VFE_OBI_THRESHOLD = 0.15
    VFE_NEUTRAL_FRONT = 8
    VFE_NEUTRAL_SECOND = 8
    VFE_LEAN_AGG = 25
    VFE_LEAN_DEF = 5
    VFE_LEAN_OFFSET = 3
    VFE_SKEW_SOFT = 25
    VFE_SKEW_HARD = 50
    VFE_FLATTEN_HARD = 70
    VFE_TREND_WIN = 200
    VFE_TREND_THRESHOLD = 0.05
    VFE_TREND_BIAS = 8

    def __init__(self) -> None:
        self.history: Dict = {}

    @classmethod
    def apply_params(cls, params: dict) -> None:
        for k, v in params.items():
            if hasattr(cls, k):
                setattr(cls, k, v)

    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("vfe_mids", [])

    def _save(self) -> str:
        h = dict(self.history)
        if "vfe_mids" in h and len(h["vfe_mids"]) > 600:
            h["vfe_mids"] = h["vfe_mids"][-600:]
        return json.dumps(h)

    @staticmethod
    def _top(d: OrderDepth) -> Tuple[Optional[int], Optional[int], int, int]:
        bb = max(d.buy_orders) if d.buy_orders else None
        ba = min(d.sell_orders) if d.sell_orders else None
        bv = d.buy_orders[bb] if bb is not None else 0
        av = -d.sell_orders[ba] if ba is not None else 0
        return bb, ba, bv, av

    @staticmethod
    def _mid(d: OrderDepth) -> Optional[float]:
        bb = max(d.buy_orders) if d.buy_orders else None
        ba = min(d.sell_orders) if d.sell_orders else None
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0

    def _obi_mm(
        self, symbol, depth, pos, ewma_key, *,
        ewma_alpha, take_edge, obi_thr, neutral_front, neutral_second,
        lean_agg, lean_def, lean_offset, skew_soft, skew_hard, flatten_hard,
        bias_buy: int = 0, bias_sell: int = 0,
    ) -> List[Order]:
        bb, ba, bv, av = self._top(depth)
        if bb is None or ba is None:
            return []
        limit = self.LIMITS[symbol]
        orders: List[Order] = []
        mid = (bb + ba) / 2.0
        prev = self.history.get(ewma_key)
        ewma = mid if prev is None else (1 - ewma_alpha) * prev + ewma_alpha * mid
        self.history[ewma_key] = ewma
        fair = ewma
        obi = (bv - av) / (bv + av) if (bv + av) > 0 else 0.0

        if ba <= fair - take_edge and pos < limit:
            sz = min(limit - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(symbol, ba, sz)); pos += sz
        if bb >= fair + take_edge and pos > -limit:
            sz = min(limit + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(symbol, bb, -sz)); pos -= sz

        bullish = obi > obi_thr
        bearish = obi < -obi_thr
        room_long = max(0, limit - pos)
        room_short = max(0, limit + pos)

        if pos >= flatten_hard:
            buy_front = buy_second = 0
        else:
            base = lean_agg if bullish else (lean_def if bearish else neutral_front)
            buy_front = min(base + bias_buy, room_long)
            buy_second = min(neutral_second, max(0, room_long - buy_front))

        if pos <= -flatten_hard:
            sell_front = sell_second = 0
        else:
            base = lean_agg if bearish else (lean_def if bullish else neutral_front)
            sell_front = min(base + bias_sell, room_short)
            sell_second = min(neutral_second, max(0, room_short - sell_front))

        if pos >= skew_hard: skew = -2
        elif pos >= skew_soft: skew = -1
        elif pos <= -skew_hard: skew = 2
        elif pos <= -skew_soft: skew = 1
        else: skew = 0

        if bullish:
            qbid, qask = bb + 1 + skew, ba + lean_offset + skew
        elif bearish:
            qbid, qask = bb - lean_offset + skew, ba - 1 + skew
        else:
            qbid, qask = bb + 1 + skew, ba - 1 + skew
        if qbid >= qask:
            qbid = qask - 1

        if buy_front > 0: orders.append(Order(symbol, qbid, buy_front))
        if sell_front > 0: orders.append(Order(symbol, qask, -sell_front))
        if buy_second > 0: orders.append(Order(symbol, qbid - 2, buy_second))
        if sell_second > 0: orders.append(Order(symbol, qask + 2, -sell_second))
        return orders

    def _vfe_trend_bias(self, mid: float) -> Tuple[int, int]:
        mids = self.history.setdefault("vfe_mids", [])
        mids.append(mid)
        if len(mids) > self.VFE_TREND_WIN + 5:
            del mids[: len(mids) - (self.VFE_TREND_WIN + 5)]
        if len(mids) < self.VFE_TREND_WIN:
            return 0, 0
        slope = (mids[-1] - mids[-self.VFE_TREND_WIN]) / self.VFE_TREND_WIN
        if slope > self.VFE_TREND_THRESHOLD:
            return self.VFE_TREND_BIAS, 0
        if slope < -self.VFE_TREND_THRESHOLD:
            return 0, self.VFE_TREND_BIAS
        return 0, 0

    def _hp(self, state: TradingState) -> List[Order]:
        if HYDROGEL not in state.order_depths:
            return []
        return self._obi_mm(
            HYDROGEL, state.order_depths[HYDROGEL], state.position.get(HYDROGEL, 0),
            "hp_ewma",
            ewma_alpha=self.HP_EWMA_ALPHA, take_edge=self.HP_TAKE_EDGE,
            obi_thr=self.HP_OBI_THRESHOLD,
            neutral_front=self.HP_NEUTRAL_FRONT, neutral_second=self.HP_NEUTRAL_SECOND,
            lean_agg=self.HP_LEAN_AGG, lean_def=self.HP_LEAN_DEF,
            lean_offset=self.HP_LEAN_OFFSET,
            skew_soft=self.HP_SKEW_SOFT, skew_hard=self.HP_SKEW_HARD,
            flatten_hard=self.HP_FLATTEN_HARD,
        )

    def _vfe(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        depth = state.order_depths[VFE]
        m = self._mid(depth)
        bias_buy, bias_sell = (0, 0)
        if m is not None:
            bias_buy, bias_sell = self._vfe_trend_bias(m)
        return self._obi_mm(
            VFE, depth, state.position.get(VFE, 0),
            "vfe_ewma",
            ewma_alpha=self.VFE_EWMA_ALPHA, take_edge=self.VFE_TAKE_EDGE,
            obi_thr=self.VFE_OBI_THRESHOLD,
            neutral_front=self.VFE_NEUTRAL_FRONT, neutral_second=self.VFE_NEUTRAL_SECOND,
            lean_agg=self.VFE_LEAN_AGG, lean_def=self.VFE_LEAN_DEF,
            lean_offset=self.VFE_LEAN_OFFSET,
            skew_soft=self.VFE_SKEW_SOFT, skew_hard=self.VFE_SKEW_HARD,
            flatten_hard=self.VFE_FLATTEN_HARD,
            bias_buy=bias_buy, bias_sell=bias_sell,
        )

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._load(state)
        result: Dict[str, List[Order]] = {}
        o = self._hp(state)
        if o:
            result[HYDROGEL] = o
        o = self._vfe(state)
        if o:
            result[VFE] = o
        return result, 0, self._save()
