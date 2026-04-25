"""trader_ken_v54_smile_pairs.py

Smile pair-arb:
- Fit smile residuals each tick.
- Trade one underpriced strike vs one overpriced strike simultaneously.
- Maintain relative-value stance instead of outright directional option bets.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

import numpy as np
from datamodel import Order, OrderDepth, TradingState

VFE = "VELVETFRUIT_EXTRACT"
STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
DELTA = {5000: 0.82, 5100: 0.70, 5200: 0.57, 5300: 0.44, 5400: 0.31, 5500: 0.21}


class Trader:
    VEV_LIMIT = 20
    Z_ENTRY = 1.70
    SPREAD_MAX = 4
    PAIR_QTY = 4
    VAR_ALPHA = 0.08

    VFE_LIMIT = 80
    HEDGE_MAX = 14
    HEDGE_GAIN = 0.55

    def __init__(self):
        self.h: Dict = {}

    def _load(self, state: TradingState):
        if state.traderData:
            try:
                self.h = json.loads(state.traderData)
            except Exception:
                self.h = {}
        self.h.setdefault("var", {})
        for k in STRIKES:
            self.h["var"].setdefault(str(k), 4.0)

    def _save(self):
        return json.dumps(self.h)

    @staticmethod
    def _top(d: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(d.buy_orders.keys()) if d.buy_orders else None
        ba = min(d.sell_orders.keys()) if d.sell_orders else None
        return bb, ba

    def _build(self, state: TradingState, s_mid: float):
        rows = []
        for k in STRIKES:
            sym = f"VEV_{k}"
            d = state.order_depths.get(sym)
            if d is None:
                continue
            bb, ba = self._top(d)
            if bb is None or ba is None or ba <= bb:
                continue
            sp = ba - bb
            if sp > self.SPREAD_MAX:
                continue
            mid = (bb + ba) / 2.0
            intr = max(s_mid - k, 0.0)
            prem = mid - intr
            rows.append((k, sym, bb, ba, prem))
        return rows

    def _smile(self, rows, s_mid: float):
        if len(rows) < 4:
            return None
        x = np.array([(k - s_mid) / 100.0 for (k, *_rest) in rows], dtype=float)
        y = np.array([prem for (*_a, prem) in rows], dtype=float)
        try:
            c = np.polyfit(x, y, 2)
        except Exception:
            return None
        out = []
        for k, sym, bb, ba, prem in rows:
            fair = float(np.polyval(c, (k - s_mid) / 100.0))
            r = prem - fair
            key = str(k)
            pv = float(self.h["var"].get(key, 4.0))
            nv = (1 - self.VAR_ALPHA) * pv + self.VAR_ALPHA * (r * r)
            nv = max(1.0, nv)
            self.h["var"][key] = nv
            z = r / (nv ** 0.5)
            out.append((k, sym, bb, ba, z))
        return out

    def _options_logic(self, state: TradingState, s_mid: float) -> List[Order]:
        rows = self._build(state, s_mid)
        sig = self._smile(rows, s_mid)
        if not sig:
            return []

        over = [x for x in sig if x[4] >= self.Z_ENTRY]
        under = [x for x in sig if x[4] <= -self.Z_ENTRY]
        if not over or not under:
            return []
        over.sort(key=lambda t: t[4], reverse=True)
        under.sort(key=lambda t: t[4])
        ok, osym, obb, _oba, _oz = over[0]
        uk, usym, _ubb, uba, _uz = under[0]

        d_over = state.order_depths[osym]
        d_under = state.order_depths[usym]
        pos_o = int(state.position.get(osym, 0))
        pos_u = int(state.position.get(usym, 0))

        lim_o = self.VEV_LIMIT
        lim_u = self.VEV_LIMIT
        q_sell = min(self.PAIR_QTY, lim_o + pos_o, d_over.buy_orders.get(obb, 0))
        q_buy = min(self.PAIR_QTY, lim_u - pos_u, -d_under.sell_orders.get(uba, 0))
        q = min(q_sell, q_buy)
        if q <= 0:
            return []

        return [Order(osym, obb, -q), Order(usym, uba, q)]

    def _vfe_hedge(self, state: TradingState) -> List[Order]:
        d = state.order_depths.get(VFE)
        if d is None:
            return []
        bb, ba = self._top(d)
        if bb is None or ba is None:
            return []
        desired = 0.0
        for k in STRIKES:
            desired += state.position.get(f"VEV_{k}", 0) * (-DELTA[k])
        desired = max(-self.VFE_LIMIT, min(self.VFE_LIMIT, desired))
        pos = int(state.position.get(VFE, 0))
        gap = desired - pos
        if abs(gap) < 3:
            return []
        q = min(self.HEDGE_MAX, int(abs(gap) * self.HEDGE_GAIN))
        q = max(0, q)
        if q == 0:
            return []
        if gap > 0 and pos < self.VFE_LIMIT:
            q = min(q, self.VFE_LIMIT - pos, -d.sell_orders.get(ba, 0))
            return [Order(VFE, ba, q)] if q > 0 else []
        if gap < 0 and pos > -self.VFE_LIMIT:
            q = min(q, self.VFE_LIMIT + pos, d.buy_orders.get(bb, 0))
            return [Order(VFE, bb, -q)] if q > 0 else []
        return []

    def run(self, state: TradingState):
        self._load(state)
        result: Dict[str, List[Order]] = {}

        vd = state.order_depths.get(VFE)
        if vd is not None:
            bb, ba = self._top(vd)
            if bb is not None and ba is not None:
                s_mid = (bb + ba) / 2.0
                for o in self._options_logic(state, s_mid):
                    result.setdefault(o.symbol, []).append(o)
                for o in self._vfe_hedge(state):
                    result.setdefault(o.symbol, []).append(o)
        return result, 0, self._save()

