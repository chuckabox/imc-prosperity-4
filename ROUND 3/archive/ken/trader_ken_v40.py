"""trader_ken_v40.py

Candidate: same as v35, but only enables options in latter part of each day.
Hypothesis: avoid early-session option noise.
"""
from __future__ import annotations

from typing import List

from datamodel import TradingState
from trader_ken_v35 import Trader as _BaseTrader


class Trader(_BaseTrader):
    VEV_START_TS_IN_DAY = 420_000

    def _vev_logic(self, state: TradingState, vfe_mid: float, scale: float, risk_off: bool) -> List:
        ts_in_day = int(state.timestamp) % 1_000_000
        if ts_in_day < self.VEV_START_TS_IN_DAY:
            return []
        return super()._vev_logic(state, vfe_mid, scale, risk_off)

