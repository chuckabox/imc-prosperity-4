"""trader_ken_v48.py

Regime-switch hybrid:
- Low-vol regime: hydro-heavy defensive profile (v46-like).
- High-vol regime: option-enabled profile (v41/v38-like).
"""
from __future__ import annotations

from typing import List

from datamodel import TradingState
from trader_ken_v38 import Trader as _BaseTrader


class Trader(_BaseTrader):
    # Regime boundaries
    HYBRID_VOL_SPLIT = 1.18
    VEV_START_TS_IN_DAY = 380_000

    def _is_high_vol(self) -> bool:
        return float(self.history.get("vfe_vol_ewma", 0.0)) >= self.HYBRID_VOL_SPLIT

    def _hydrogel_logic(self, state: TradingState, scale: float, risk_off: bool):
        # Temporarily switch hydro params by regime.
        high = self._is_high_vol()
        old = (self.HP_MAKER_EDGE, self.HP_TAKER_EDGE, self.HP_TAKER_MAX)
        if high:
            self.HP_MAKER_EDGE = 2.2
            self.HP_TAKER_EDGE = 2.6
            self.HP_TAKER_MAX = 18
        else:
            self.HP_MAKER_EDGE = 2.0
            self.HP_TAKER_EDGE = 2.3
            self.HP_TAKER_MAX = 22
        try:
            return super()._hydrogel_logic(state, scale, risk_off)
        finally:
            self.HP_MAKER_EDGE, self.HP_TAKER_EDGE, self.HP_TAKER_MAX = old

    def _vfe_logic(self, state: TradingState, scale: float, risk_off: bool):
        high = self._is_high_vol()
        old = (self.VFE_MAKER_EDGE, self.VFE_TAKER_EDGE, self.VFE_TAKER_MAX)
        if high:
            self.VFE_MAKER_EDGE = 2.2
            self.VFE_TAKER_EDGE = 4.5
            self.VFE_TAKER_MAX = 12
        else:
            self.VFE_MAKER_EDGE = 2.6
            self.VFE_TAKER_EDGE = 5.2
            self.VFE_TAKER_MAX = 10
        try:
            return super()._vfe_logic(state, scale, risk_off)
        finally:
            self.VFE_MAKER_EDGE, self.VFE_TAKER_EDGE, self.VFE_TAKER_MAX = old

    def _vev_logic(self, state: TradingState, vfe_mid: float, scale: float, risk_off: bool) -> List:
        ts_in_day = int(state.timestamp) % 1_000_000
        # Update volatility regime state through parent logic gate path.
        _ = self._update_vol_regime(vfe_mid)
        if ts_in_day < self.VEV_START_TS_IN_DAY:
            return []
        if not self._is_high_vol():
            return []

        old_z = self.VEV_Z_ENTRY
        self.VEV_Z_ENTRY = 1.70
        try:
            return super()._vev_logic(state, vfe_mid, scale, risk_off)
        finally:
            self.VEV_Z_ENTRY = old_z

