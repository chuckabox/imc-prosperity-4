"""trader_ken_v46.py - hydro-heavier with conservative options."""
from __future__ import annotations

from typing import List

from datamodel import TradingState
from trader_ken_v38 import Trader as _BaseTrader


class Trader(_BaseTrader):
    # Hydro emphasis
    HP_MAKER_EDGE = 2.0
    HP_TAKER_EDGE = 2.3
    HP_TAKER_MAX = 22

    # More defensive VFE to avoid dragging core
    VFE_MAKER_EDGE = 2.6
    VFE_TAKER_EDGE = 5.2
    VFE_TAKER_MAX = 10

    # Options gated
    VOL_ON = 1.25
    VOL_OFF = 0.95
    VEV_Z_ENTRY = 1.80
    VEV_START_TS_IN_DAY = 430_000

    def _vev_logic(self, state: TradingState, vfe_mid: float, scale: float, risk_off: bool) -> List:
        ts_in_day = int(state.timestamp) % 1_000_000
        if ts_in_day < self.VEV_START_TS_IN_DAY:
            return []
        return super()._vev_logic(state, vfe_mid, scale, risk_off)

