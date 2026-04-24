"""trader_ken_v25.py — adaptive-protection upgrade over v24.

Goal:
- Match or beat v22 in favorable regimes.
- Keep v24-style protection, but activate adaptively using realized volatility.
"""
from __future__ import annotations

from typing import Optional, Tuple

from trader_ken_v24 import Trader as BaseTrader


class Trader(BaseTrader):
    # Volatility-adaptive protection settings
    VOL_EWMA_ALPHA = 0.12
    VOL_BASE = 1.6
    VOL_SPIKE = 2.8

    # Baseline thresholds in calm conditions
    DD_TRIGGER = 2500.0
    DD_RELEASE = 1200.0
    DD_PROTECT_TICKS = 18

    # Risk thresholds are adapted each tick in _risk_state
    RISK_NET_DELTA_TRIGGER = 74.0
    RISK_HP_POS_TRIGGER = 74
    RISK_ADVERSE_MOVE = 3.8
    RISK_MIN_SCALE = 0.62

    def _load_state(self, state):
        super()._load_state(state)
        self.history.setdefault("vfe_vol_ewma", 0.0)

    def _update_vfe_vol(self, vfe_mid: Optional[float]) -> float:
        last_vfe = self.history.get("last_vfe_mid")
        prev = float(self.history.get("vfe_vol_ewma", 0.0))
        if vfe_mid is None or last_vfe is None:
            self.history["vfe_vol_ewma"] = prev
            return prev
        move = abs(float(vfe_mid) - float(last_vfe))
        vol = (1.0 - self.VOL_EWMA_ALPHA) * prev + self.VOL_EWMA_ALPHA * move
        self.history["vfe_vol_ewma"] = vol
        return vol

    def _adaptive_dd_params(self, vol: float) -> Tuple[float, float, int]:
        if vol >= self.VOL_SPIKE:
            # High turbulence: protect earlier and longer
            return 1800.0, 850.0, 32
        if vol <= self.VOL_BASE:
            # Calm regime: let winners run
            return self.DD_TRIGGER, self.DD_RELEASE, self.DD_PROTECT_TICKS
        # Interpolate between calm and spike regimes
        w = (vol - self.VOL_BASE) / (self.VOL_SPIKE - self.VOL_BASE)
        trig = self.DD_TRIGGER * (1.0 - 0.28 * w)
        rel = self.DD_RELEASE * (1.0 - 0.25 * w)
        ticks = int(round(self.DD_PROTECT_TICKS * (1.0 + 0.65 * w)))
        return trig, rel, ticks

    def _update_drawdown_guard(self, state) -> bool:
        # Use base logic from v24, but with adaptive thresholds by current vol.
        vfe_mid = self._mid(state, "VELVETFRUIT_EXTRACT")
        vol = self._update_vfe_vol(vfe_mid)
        dd_trigger, dd_release, dd_ticks = self._adaptive_dd_params(vol)

        prev_mid = self.history["prev_mid"]
        prev_pos = self.history["prev_pos"]
        step = 0.0
        for s in self.TRACKED if hasattr(self, "TRACKED") else []:
            # Fallback not needed since BaseTrader uses module-level TRACKED; keep robust.
            pass

        # Reuse BaseTrader's mark-to-market scheme with local copy.
        from trader_ken_v24 import TRACKED  # local import keeps file standalone for contest loader

        step = 0.0
        for s in TRACKED:
            m = self._mid(state, s)
            pm = prev_mid.get(s)
            pp = float(prev_pos.get(s, 0))
            if m is not None and pm is not None:
                step += pp * (m - float(pm))
        mtm = float(self.history["mtm_proxy"]) + step
        peak = max(float(self.history["mtm_peak"]), mtm)
        dd = peak - mtm

        protect = int(self.history.get("protect_ticks_left", 0))
        if dd >= dd_trigger:
            protect = dd_ticks
        elif protect > 0:
            protect -= 1
            if dd <= dd_release:
                protect = 0

        self.history["mtm_proxy"] = mtm
        self.history["mtm_peak"] = peak
        self.history["protect_ticks_left"] = protect
        return protect > 0

    def _risk_state(self, state, vfe_mid: Optional[float], protect_mode: bool):
        # Adaptive risk thresholds by vol regime.
        vol = self._update_vfe_vol(vfe_mid)
        net_delta_trigger = self.RISK_NET_DELTA_TRIGGER
        hp_trigger = self.RISK_HP_POS_TRIGGER
        adverse = self.RISK_ADVERSE_MOVE
        min_scale = self.RISK_MIN_SCALE

        if vol >= self.VOL_SPIKE:
            net_delta_trigger -= 10.0
            hp_trigger -= 8
            adverse -= 1.0
            min_scale = min(min_scale, 0.52)
        elif vol > self.VOL_BASE:
            w = (vol - self.VOL_BASE) / (self.VOL_SPIKE - self.VOL_BASE)
            net_delta_trigger -= 10.0 * w
            hp_trigger -= int(round(8 * w))
            adverse -= 1.0 * w
            min_scale = min(min_scale, 0.62 - 0.10 * w)

        hp_pos = abs(state.position.get("HYDROGEL_PACK", 0))
        net_delta = abs(self._portfolio_net_delta(state))
        score = 0.0
        score += 0.45 * min(1.0, hp_pos / float(self.HP_LIMIT))
        score += 0.55 * min(1.0, net_delta / float(self.VFE_LIMIT))
        last_vfe = self.history.get("last_vfe_mid")
        if vfe_mid is not None and last_vfe is not None:
            dv = float(vfe_mid) - float(last_vfe)
            signed = self._portfolio_net_delta(state)
            if (signed > 0 and dv < -adverse) or (signed < 0 and dv > adverse):
                score += 0.20

        risk_off = protect_mode or hp_pos >= hp_trigger or net_delta >= net_delta_trigger or score >= 0.98
        scale = max(min_scale, 1.0 - min(1.0, score))
        if protect_mode:
            scale = min(scale, 0.52)
        return scale, risk_off

