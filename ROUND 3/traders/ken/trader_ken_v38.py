"""trader_ken_v38.py

Rapid iteration on v35:
- Keep v35 core.
- Enable VEV sparse taker only during higher-volatility VFE regime.
"""
from __future__ import annotations

from typing import List

from datamodel import TradingState
from trader_ken_v35 import Trader as _BaseTrader


class Trader(_BaseTrader):
    VOL_ALPHA = 0.10
    VOL_ON = 1.20
    VOL_OFF = 0.90

    def _load_state(self, state: TradingState) -> None:
        super()._load_state(state)
        self.history.setdefault("vfe_vol_ewma", 0.0)
        self.history.setdefault("vev_enabled_regime", False)

    def _update_vol_regime(self, vfe_mid: float) -> bool:
        last = self.history.get("last_vfe_mid")
        if last is None:
            return bool(self.history.get("vev_enabled_regime", False))
        jump = abs(float(vfe_mid) - float(last))
        prev = float(self.history.get("vfe_vol_ewma", 0.0))
        vol = (1 - self.VOL_ALPHA) * prev + self.VOL_ALPHA * jump
        self.history["vfe_vol_ewma"] = vol

        enabled = bool(self.history.get("vev_enabled_regime", False))
        if enabled:
            if vol < self.VOL_OFF:
                enabled = False
        else:
            if vol > self.VOL_ON:
                enabled = True
        self.history["vev_enabled_regime"] = enabled
        return enabled

    def _vev_logic(self, state: TradingState, vfe_mid: float, scale: float, risk_off: bool) -> List:
        enabled = self._update_vol_regime(vfe_mid)
        if not enabled:
            return []
        return super()._vev_logic(state, vfe_mid, scale, risk_off)

