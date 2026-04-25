"""trader_ken_v44.py - conservative regime/phase gating."""
from __future__ import annotations

from typing import List

from datamodel import TradingState
from trader_ken_v38 import Trader as _BaseTrader


class Trader(_BaseTrader):
    VOL_ON = 1.35
    VOL_OFF = 1.00
    VEV_Z_ENTRY = 1.95
    VEV_START_TS_IN_DAY = 450_000

    def _vev_logic(self, state: TradingState, vfe_mid: float, scale: float, risk_off: bool) -> List:
        ts_in_day = int(state.timestamp) % 1_000_000
        if ts_in_day < self.VEV_START_TS_IN_DAY:
            return []
        return super()._vev_logic(state, vfe_mid, scale, risk_off)

