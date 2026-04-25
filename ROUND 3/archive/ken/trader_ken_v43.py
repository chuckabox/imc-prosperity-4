"""trader_ken_v43.py

Mining-driven candidate:
- Keep v35 hydro/vfe baseline.
- Shift sparse option engine to strikes with better move/spread:
  5200, 5300, 5400.
"""
from __future__ import annotations

from typing import List

from datamodel import Order, TradingState
from trader_ken_v35 import Trader as _BaseTrader


class Trader(_BaseTrader):
    STRIKES = (5200, 5300, 5400)

    # Tighter signal to avoid noisy overtrading
    VEV_Z_ENTRY = 1.75

    def _vev_logic(self, state: TradingState, vfe_mid: float, scale: float, risk_off: bool) -> List:
        if risk_off:
            return []
        cands = []
        for strike in self.STRIKES:
            sym = f"VEV_{strike}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            bb, ba = self._top(depth)
            if bb is None or ba is None:
                continue
            spread = ba - bb
            max_spread = {5200: 4, 5300: 3, 5400: 2}[strike]
            if spread <= 0 or spread > max_spread:
                continue

            obs_mid = (bb + ba) / 2.0
            intrinsic = max(vfe_mid - strike, 0.0)
            obs_prem = obs_mid - intrinsic
            key = str(strike)

            # Strike-specific prior/bounds from mined stable regions.
            if strike == 5200:
                lo, hi, init = 30.0, 72.0, 48.8
            elif strike == 5300:
                lo, hi, init = 30.0, 72.0, 47.9
            else:
                lo, hi, init = 8.0, 30.0, 17.1

            prev_prem = float(self.history["prem"].get(key, init))
            prem = (1 - self.PREM_ALPHA) * prev_prem + self.PREM_ALPHA * obs_prem
            prem = max(lo, min(hi, prem))
            self.history["prem"][key] = prem

            dev = obs_prem - prem
            prev_var = float(self.history["prem_var"].get(key, 6.0))
            var = (1 - self.PREM_VAR_ALPHA) * prev_var + self.PREM_VAR_ALPHA * (dev * dev)
            var = max(1.0, var)
            self.history["prem_var"][key] = var
            z = dev / (var ** 0.5)
            fair = intrinsic + prem
            cands.append((abs(z), strike, bb, ba, z, fair))

        if not cands:
            return []

        # Sparse execution: only single best dislocation.
        cands.sort(reverse=True, key=lambda x: x[0])
        _, strike, bb, ba, z, fair = cands[0]
        if abs(z) < self.VEV_Z_ENTRY:
            return []

        sym = f"VEV_{strike}"
        depth = state.order_depths[sym]
        pos = state.position.get(sym, 0)
        lim = {5200: 26, 5300: 24, 5400: 18}[strike]
        taker_base = {5200: 5, 5300: 5, 5400: 4}[strike]
        taker_max = max(1, int(taker_base * scale))
        orders = []

        if z <= -self.VEV_Z_ENTRY and ba <= fair and pos < lim:
            sz = min(taker_max, lim - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(sym, ba, sz))
        elif z >= self.VEV_Z_ENTRY and bb >= fair and pos > -lim:
            sz = min(taker_max, lim + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(sym, bb, -sz))
        return orders

