"""trader_ken_v41.py

Candidate: concentrate options only on strongest two strikes (5000/5100).
"""
from __future__ import annotations

from typing import List, Tuple

from datamodel import Order, TradingState
from trader_ken_v35 import Trader as _BaseTrader


class Trader(_BaseTrader):
    STRIKES: Tuple[int, int] = (5000, 5100)

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
            max_spread = 8 if strike == 5000 else 6
            if spread <= 0 or spread > max_spread:
                continue

            obs_mid = (bb + ba) / 2.0
            intrinsic = max(vfe_mid - strike, 0.0)
            obs_prem = obs_mid - intrinsic
            key = str(strike)

            prev_prem = float(self.history["prem"].get(key, obs_prem))
            prem = (1 - self.PREM_ALPHA) * prev_prem + self.PREM_ALPHA * obs_prem
            if strike == 5000:
                lo, hi = 2.0, 14.0
            else:
                lo, hi = 10.0, 30.0
            prem = max(lo, min(hi, prem))
            self.history["prem"][key] = prem

            dev = obs_prem - prem
            prev_var = float(self.history["prem_var"].get(key, 9.0))
            var = (1 - self.PREM_VAR_ALPHA) * prev_var + self.PREM_VAR_ALPHA * (dev * dev)
            var = max(1.0, var)
            self.history["prem_var"][key] = var
            z = dev / (var ** 0.5)
            fair = intrinsic + prem
            cands.append((abs(z), strike, bb, ba, z, fair))

        if not cands:
            return []
        cands.sort(reverse=True, key=lambda x: x[0])
        _, strike, bb, ba, z, fair = cands[0]
        if abs(z) < self.VEV_Z_ENTRY:
            return []

        sym = f"VEV_{strike}"
        depth = state.order_depths[sym]
        pos = state.position.get(sym, 0)
        lim = 38 if strike == 5000 else 30
        taker_max = max(1, int((9 if strike == 5000 else 6) * scale))
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

