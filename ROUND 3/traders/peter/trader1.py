"""trader1.py - clean plug-in signal trader for ROUND 3.

Signal interface: every product handler returns List[Order]. Tunables live
on the Trader class as UPPERCASE attrs and can be overridden via
``Trader.apply_params({'HP_TAKE_EDGE': 2, ...})`` before instantiation.

Modules:
  - HYDROGEL_PACK : OBI-aware mean-reversion market maker (stable base PnL).
  - VELVETFRUIT_EXTRACT : trend + vol-regime aware MM (drift carry).
  - VEV_*  : Black-Scholes fair-value option taker (gamma alpha).

NOTE: Day 0+1 are training data. Day 2 is hidden validation. Do NOT inspect
day 2 metrics during tuning.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1)


HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]
TS_PER_DAY = 1_000_000


class Trader:
    # ── Module switches ─────────────────────────────────────────────────────
    ENABLE_HYDROGEL = True
    ENABLE_VFE = True
    ENABLE_VEV = False        # loses money in p4bt backtester
    ENABLE_HEDGE = False      # spread costs outweigh gamma PnL in backtest

    LIMITS: Dict[str, int] = {
        HYDROGEL: 80,
        VFE: 80,
        **{s: 60 for s in VEV_SYMBOLS},
    }

    # ── HYDROGEL params ─────────────────────────────────────────────────────
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

    # ── VFE params ──────────────────────────────────────────────────────────
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
    VFE_TREND_WIN = 200          # ticks for slope
    VFE_TREND_THRESHOLD = 0.05   # mid-units per tick
    VFE_TREND_BIAS = 8           # extra units to lean with confirmed trend

    # ── VEV params ──────────────────────────────────────────────────────────
    VEV_SIGMA = 0.018
    VEV_ACTIVE_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
    VEV_BID_EDGE_REQ = 1.0
    VEV_TAKE_EDGE = 6.0
    VEV_SELL_EDGE = 6.0       # sell if bid > fair + this
    VEV_PER_STRIKE_CAP = 50
    VEV_BID_SIZE = 12

    # ── Hedge params ────────────────────────────────────────────────────────
    HEDGE_DEAD_BAND = 10      # only hedge if |residual| > this
    HEDGE_MAX_PER_TICK = 15   # max lots to hedge per tick
    HEDGE_EVERY_N = 3         # hedge every N ticks

    # ── Plug-in param injection ─────────────────────────────────────────────
    @classmethod
    def apply_params(cls, params: dict) -> None:
        for k, v in params.items():
            if not hasattr(cls, k):
                raise AttributeError(f"Unknown param {k}")
            setattr(cls, k, v)

    @classmethod
    def get_params(cls) -> dict:
        return {k: getattr(cls, k) for k in vars(cls) if k.isupper()}

    # ── State ───────────────────────────────────────────────────────────────
    def __init__(self):
        self.history: Dict = {}

    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("vfe_mids", [])
        self.history.setdefault("last_ts", -1)
        self.history.setdefault("day", 0)
        ts = state.timestamp
        last = int(self.history["last_ts"])
        if 0 <= ts < last:
            self.history["day"] = int(self.history["day"]) + 1
        self.history["last_ts"] = ts

    def _save_state(self) -> str:
        h = dict(self.history)
        # Trim trail to keep traderData small.
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

    def _tte_days(self, ts: int) -> float:
        day = int(self.history.get("day", 0))
        return max(0.01, (8 - day) - ts / TS_PER_DAY)

    # ── Generic OBI MM core ─────────────────────────────────────────────────
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

    # ── Signal: trend slope on rolling mid window ───────────────────────────
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

    def _hydrogel_logic(self, state: TradingState) -> List[Order]:
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

    def _vfe_logic(self, state: TradingState) -> List[Order]:
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

    def _vev_logic(self, state: TradingState) -> Tuple[List[Order], float]:
        """Returns (orders, total_option_delta)."""
        if VFE not in state.order_depths:
            return [], 0.0
        S = self._mid(state.order_depths[VFE])
        if S is None:
            return [], 0.0
        T = self._tte_days(state.timestamp)
        sigma = self.VEV_SIGMA
        out: List[Order] = []
        total_delta = 0.0
        for K in self.VEV_ACTIVE_STRIKES:
            sym = f"VEV_{K}"
            if sym not in state.order_depths:
                continue
            depth = state.order_depths[sym]
            bb, ba, _, _ = self._top(depth)
            if bb is None or ba is None:
                continue
            fair = bs_call(S, K, T, sigma)
            delta = bs_delta(S, K, T, sigma)
            pos = state.position.get(sym, 0)
            cap = min(self.LIMITS[sym], self.VEV_PER_STRIKE_CAP)

            # Buy cheap options
            if ba < fair - self.VEV_TAKE_EDGE and pos < cap:
                sz = min(cap - pos, -depth.sell_orders[ba])
                if sz > 0:
                    out.append(Order(sym, ba, sz)); pos += sz

            # Passive bid inside spread
            quote_bid = bb + 1
            if quote_bid <= fair - self.VEV_BID_EDGE_REQ and pos < cap:
                sz = min(self.VEV_BID_SIZE, cap - pos)
                if sz > 0:
                    out.append(Order(sym, quote_bid, sz))

            # Sell overpriced options
            if bb > fair + self.VEV_SELL_EDGE and pos > -cap:
                sz = min(cap + pos, depth.buy_orders[bb])
                if sz > 0:
                    out.append(Order(sym, bb, -sz)); pos -= sz

            # Track delta for hedging (current confirmed position)
            total_delta += state.position.get(sym, 0) * delta

        return out, total_delta

    # ── Delta hedge in VFE ──────────────────────────────────────────────────
    def _hedge_logic(self, state: TradingState, option_delta: float) -> List[Order]:
        if VFE not in state.order_depths:
            return []
        tick = self.history.get("tick_count", 0)
        self.history["tick_count"] = tick + 1
        if tick % self.HEDGE_EVERY_N != 0:
            return []

        depth = state.order_depths[VFE]
        bb, ba, _, _ = self._top(depth)
        if bb is None or ba is None:
            return []

        target_vfe = int(round(-option_delta))
        limit = self.LIMITS[VFE]
        target_vfe = max(-limit, min(limit, target_vfe))
        vfe_pos = state.position.get(VFE, 0)
        residual = target_vfe - vfe_pos

        if abs(residual) <= self.HEDGE_DEAD_BAND:
            return []

        size = max(-self.HEDGE_MAX_PER_TICK, min(self.HEDGE_MAX_PER_TICK, residual))
        if size > 0:
            return [Order(VFE, ba, size)]  # buy at ask to hedge fast
        return [Order(VFE, bb, size)]       # sell at bid to hedge fast

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}
        if self.ENABLE_HYDROGEL:
            for o in self._hydrogel_logic(state):
                result.setdefault(o.symbol, []).append(o)

        option_delta = 0.0
        if self.ENABLE_VEV:
            vev_orders, option_delta = self._vev_logic(state)
            for o in vev_orders:
                result.setdefault(o.symbol, []).append(o)

        # VFE: use as hedge vehicle if hedging, otherwise standalone MM
        if self.ENABLE_HEDGE and abs(option_delta) > 0.1:
            for o in self._hedge_logic(state, option_delta):
                result.setdefault(o.symbol, []).append(o)
        if self.ENABLE_VFE:
            for o in self._vfe_logic(state):
                result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save_state()
