"""trader_ken_v29.py — v28 + GOAT-style anti-floor circuit breaker.

Because TradingState does not expose realized PnL, we proxy "floor hits" using
mark-to-mid drawdown from internal equity peak. On the 3rd hit, we enter a
temporary anti-floor mode:
  - force risk_off
  - downscale sizing further
  - aggressively flatten large inventory (GOAT-like unwind)
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState
from trader_ken_v22 import HYDROGEL, VFE, VEV_STRIKES
from trader_ken_v28 import Trader as TraderV28


class Trader(TraderV28):
    # Drawdown-based anti-floor circuit breaker parameters
    DD_HIT_THRESHOLD = 1600.0
    DD_HIT_COOLDOWN = 25_000
    DD_HITS_TO_TRIGGER = 3
    ANTI_FLOOR_WINDOW = 80_000
    ANTI_FLOOR_SCALE_CAP = 0.25
    ANTI_FLOOR_UNWIND_MAX = 12

    def _load_state(self, state: TradingState) -> None:
        super()._load_state(state)
        self.history.setdefault("mtm_peak", 0.0)
        self.history.setdefault("dd_hits", 0)
        self.history.setdefault("last_dd_hit_ts", -10**12)
        self.history.setdefault("anti_floor_until", -1)

    def _top_mid(self, depth: Optional[OrderDepth]) -> Optional[float]:
        if depth is None:
            return None
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0

    def _estimate_mtm_equity(self, state: TradingState) -> float:
        mtm = 0.0

        hp_mid = self._top_mid(state.order_depths.get(HYDROGEL))
        if hp_mid is not None:
            mtm += state.position.get(HYDROGEL, 0) * hp_mid

        vfe_mid = self._top_mid(state.order_depths.get(VFE))
        if vfe_mid is not None:
            mtm += state.position.get(VFE, 0) * vfe_mid

        for strike in VEV_STRIKES:
            sym = f"VEV_{strike}"
            mid = self._top_mid(state.order_depths.get(sym))
            if mid is not None:
                mtm += state.position.get(sym, 0) * mid

        return mtm

    def _update_drawdown_regime(self, state: TradingState) -> bool:
        now = int(state.timestamp)
        mtm = self._estimate_mtm_equity(state)
        peak = float(self.history.get("mtm_peak", 0.0))
        if mtm > peak:
            peak = mtm
            self.history["mtm_peak"] = peak

        drawdown = peak - mtm
        if drawdown >= self.DD_HIT_THRESHOLD and (now - int(self.history.get("last_dd_hit_ts", -10**12))) >= self.DD_HIT_COOLDOWN:
            hits = int(self.history.get("dd_hits", 0)) + 1
            self.history["dd_hits"] = hits
            self.history["last_dd_hit_ts"] = now
            if hits >= self.DD_HITS_TO_TRIGGER:
                self.history["anti_floor_until"] = now + self.ANTI_FLOOR_WINDOW
                self.history["dd_hits"] = 0

        return now < int(self.history.get("anti_floor_until", -1))

    def _risk_state(
        self, state: TradingState, hp_mid: Optional[float], vfe_mid: Optional[float]
    ) -> Tuple[float, bool]:
        scale, risk_off = super()._risk_state(state, hp_mid, vfe_mid)
        anti_floor = self._update_drawdown_regime(state)
        if anti_floor:
            risk_off = True
            scale = min(scale, self.ANTI_FLOOR_SCALE_CAP)
        self.history["anti_floor"] = anti_floor
        return scale, risk_off

    def _extra_unwind(
        self, symbol: str, depth: OrderDepth, pos: int, limit: int
    ) -> List[Order]:
        anti_floor = bool(self.history.get("anti_floor", False))
        if (not anti_floor) or abs(pos) < int(0.45 * limit):
            return []
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []
        qty = min(self.ANTI_FLOOR_UNWIND_MAX, abs(pos) - int(0.45 * limit) + 1)
        if qty <= 0:
            return []
        if pos > 0:
            return [Order(symbol, bb, -qty)]
        return [Order(symbol, ba, qty)]

    def _hydrogel_logic(self, state: TradingState, scale: float, risk_off: bool) -> Tuple[List[Order], Optional[float]]:
        orders, mid = super()._hydrogel_logic(state, scale, risk_off)
        depth = state.order_depths.get(HYDROGEL)
        if depth is not None:
            pos = state.position.get(HYDROGEL, 0)
            orders.extend(self._extra_unwind(HYDROGEL, depth, pos, self.HP_LIMIT))
        return orders, mid

    def _vfe_logic(self, state: TradingState, scale: float, risk_off: bool) -> Tuple[List[Order], Optional[float]]:
        orders, mid = super()._vfe_logic(state, scale, risk_off)
        depth = state.order_depths.get(VFE)
        if depth is not None:
            pos = state.position.get(VFE, 0)
            orders.extend(self._extra_unwind(VFE, depth, pos, self.VFE_LIMIT))
        return orders, mid

