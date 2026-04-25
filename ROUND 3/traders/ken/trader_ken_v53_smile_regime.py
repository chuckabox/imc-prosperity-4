"""trader_ken_v53_smile_regime.py

Smile residual trading with volatility gate:
- In low vol: mostly hydro carry.
- In high vol: activate smile taker module more aggressively.
"""
from __future__ import annotations

from typing import List

from datamodel import TradingState
from trader_ken_v51_smile import Trader as _BaseTrader


class Trader(_BaseTrader):
    VOL_ALPHA = 0.10
    VOL_ON = 1.25
    VOL_OFF = 0.95

    def _load(self, state: TradingState) -> None:
        super()._load(state)
        self.h.setdefault("vfe_jump_ewma", 0.0)
        self.h.setdefault("smile_on", False)
        self.h.setdefault("last_vfe_mid_local", None)

    def _update_regime(self, s_mid: float) -> bool:
        last = self.h.get("last_vfe_mid_local")
        if last is not None:
            jump = abs(float(s_mid) - float(last))
            prev = float(self.h.get("vfe_jump_ewma", 0.0))
            v = (1 - self.VOL_ALPHA) * prev + self.VOL_ALPHA * jump
            self.h["vfe_jump_ewma"] = v
            on = bool(self.h.get("smile_on", False))
            if on:
                if v < self.VOL_OFF:
                    on = False
            else:
                if v > self.VOL_ON:
                    on = True
            self.h["smile_on"] = on
        self.h["last_vfe_mid_local"] = s_mid
        return bool(self.h.get("smile_on", False))

    def _vev_smile_logic(self, state: TradingState, s_mid: float, scale: float) -> List:
        on = self._update_regime(s_mid)
        if not on:
            return []
        old = (self.VEV_ENTRY_Z, self.VEV_TAKER_MAX)
        self.VEV_ENTRY_Z = 1.65
        self.VEV_TAKER_MAX = 7
        try:
            return super()._vev_smile_logic(state, s_mid, scale)
        finally:
            self.VEV_ENTRY_Z, self.VEV_TAKER_MAX = old

