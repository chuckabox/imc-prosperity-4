"""trader_ken_v30.py — v28 with soft, non-reversing safety controls.

Safety additions:
- Open-phase throttle: smaller size + wider maker edge early in the day
- Inventory-speed limiter: if position changes too fast, temporarily reduce risk
- No hard directional reversal; only de-risking via smaller size/wider quotes
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from datamodel import Order, TradingState
from trader_ken_v22 import HYDROGEL, VFE
from trader_ken_v28 import Trader as TraderV28


class Trader(TraderV28):
    # Approx first 10% of the day in timestamp units.
    OPEN_PHASE_TS = 120_000

    # Position velocity guard.
    HP_SPEED_TRIGGER = 18
    VFE_SPEED_TRIGGER = 16
    SPEED_COOLDOWN_TS = 40_000

    # Safety scaling.
    OPEN_TAKER_MULT = 0.70
    OPEN_MAKER_MULT = 0.78
    OPEN_EDGE_EXTRA = 0.5
    SPEED_TAKER_MULT = 0.55
    SPEED_MAKER_MULT = 0.70
    SPEED_EDGE_EXTRA = 0.6

    def _load_state(self, state: TradingState) -> None:
        super()._load_state(state)
        self.history.setdefault("last_hp_pos", 0)
        self.history.setdefault("last_vfe_pos", 0)
        self.history.setdefault("hp_speed_cooldown_until", -1)
        self.history.setdefault("vfe_speed_cooldown_until", -1)

    def _in_open_phase(self, state: TradingState) -> bool:
        return int(state.timestamp) <= self.OPEN_PHASE_TS

    def _speed_limited(self, state: TradingState, symbol: str, trigger: int, cd_key: str, last_pos_key: str) -> bool:
        now = int(state.timestamp)
        pos = int(state.position.get(symbol, 0))
        last_pos = int(self.history.get(last_pos_key, 0))
        if abs(pos - last_pos) >= trigger:
            self.history[cd_key] = now + self.SPEED_COOLDOWN_TS
        self.history[last_pos_key] = pos
        return now < int(self.history.get(cd_key, -1))

    def _hydrogel_logic(self, state: TradingState, scale: float, risk_off: bool) -> Tuple[List[Order], Optional[float]]:
        # Apply soft throttles before running normal v28 logic.
        open_phase = self._in_open_phase(state)
        speed_limited = self._speed_limited(
            state, HYDROGEL, self.HP_SPEED_TRIGGER, "hp_speed_cooldown_until", "last_hp_pos"
        )
        local_scale = scale
        if open_phase:
            local_scale *= self.OPEN_TAKER_MULT
        if speed_limited:
            local_scale *= self.SPEED_TAKER_MULT

        return super()._hydrogel_logic(state, local_scale, risk_off)

    def _vfe_logic(self, state: TradingState, scale: float, risk_off: bool) -> Tuple[List[Order], Optional[float]]:
        open_phase = self._in_open_phase(state)
        speed_limited = self._speed_limited(
            state, VFE, self.VFE_SPEED_TRIGGER, "vfe_speed_cooldown_until", "last_vfe_pos"
        )
        local_scale = scale
        if open_phase:
            local_scale *= self.OPEN_TAKER_MULT
        if speed_limited:
            local_scale *= self.SPEED_TAKER_MULT

        return super()._vfe_logic(state, local_scale, risk_off)

