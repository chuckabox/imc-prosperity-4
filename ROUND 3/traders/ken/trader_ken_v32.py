"""trader_ken_v32.py

Three-module trader for Round 3:
  - HYDROGEL_PACK: EWMA fair + L1 imbalance quote skew
  - VELVETFRUIT_EXTRACT: passive symmetric maker
  - VEV_5200 / VEV_5300: BS-fair taker when ask < fair - MIN_EDGE

Single-file, no local imports beyond datamodel.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

# ── Products ──────────────────────────────────────────────────────────────────
HP  = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_ACTIVE_STRIKES = [5200, 5300]

# ── HYDROGEL parameters ───────────────────────────────────────────────────────
HP_LIMIT         = 80
HP_EWMA_ALPHA    = 0.003   # half-life ~300 ticks, matches OU from data analysis
HP_EDGE          = 8       # half of observed 16-wide spread
HP_SKEW          = 4       # matches ~4 XIRECs predicted by imbalance signal
HP_INV_TRIGGER   = 40      # |pos| threshold to start inventory lean
HP_INV_FACTOR    = 0.15    # quote shift per unit of pos above trigger
HP_TAKER_MAX     = 5       # max lots to take when reducing wrong-side exposure

# ── VFE parameters ────────────────────────────────────────────────────────────
VFE_LIMIT        = 60
VFE_EWMA_ALPHA   = 0.05
VFE_EDGE         = 3
VFE_INV_TRIGGER  = 30
VFE_INV_FACTOR   = 0.10

# ── VEV parameters ────────────────────────────────────────────────────────────
VEV_LIMIT        = 20      # per strike
VEV_SIGMA        = 0.0176  # bias-corrected realized vol per day
VEV_MIN_EDGE     = 5       # minimum XIRECs edge to enter


class Trader:

    def __init__(self) -> None:
        self._state: Dict = {}

    # ── State persistence ──────────────────────────────────────────────────────

    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self._state = json.loads(state.traderData)
            except Exception:
                self._state = {}
        self._state.setdefault("hp_ewma", None)
        self._state.setdefault("vfe_ewma", None)

    def _save(self) -> str:
        return json.dumps(self._state)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders) if depth.buy_orders else None
        ba = min(depth.sell_orders) if depth.sell_orders else None
        return bb, ba

    @staticmethod
    def _top_vol(depth: OrderDepth) -> Tuple[int, int]:
        """Return (bid_vol_1, ask_vol_1) at the best level."""
        bv = depth.buy_orders[max(depth.buy_orders)] if depth.buy_orders else 0
        av = abs(depth.sell_orders[min(depth.sell_orders)]) if depth.sell_orders else 0
        return bv, av

    # ── BS helpers (no scipy -- inline approximation) ─────────────────────────

    @staticmethod
    def _norm_cdf(x: float) -> float:
        """Abramowitz & Stegun 26.2.17 rational approximation, error < 1.5e-7."""
        sign = 1.0 if x >= 0 else -1.0
        x = abs(x)
        t = 1.0 / (1.0 + 0.2316419 * x)
        p = t * (0.319381530
              + t * (-0.356563782
              + t * (1.781477937
              + t * (-1.821255978
              + t * 1.330274429))))
        pdf_val = (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x * x)
        if sign >= 0:
            return 1.0 - pdf_val * p
        else:
            return pdf_val * p

    def _bs_call(self, S: float, K: int, tte: float) -> float:
        """Black-Scholes call price, r=0."""
        if tte <= 0:
            return max(S - K, 0.0)
        sigma_sqrt_t = VEV_SIGMA * math.sqrt(tte)
        if sigma_sqrt_t == 0:
            return max(S - K, 0.0)
        d1 = (math.log(S / K) + 0.5 * VEV_SIGMA ** 2 * tte) / sigma_sqrt_t
        d2 = d1 - sigma_sqrt_t
        return S * self._norm_cdf(d1) - K * self._norm_cdf(d2)

    @staticmethod
    def _tte(state: TradingState) -> float:
        """Time-to-expiry in days. TTE=8 at ts=0 day=0; decays continuously."""
        ts = int(state.timestamp)
        day_num = ts // 1_000_000
        tick_ts = ts % 1_000_000
        return 8.0 - day_num - tick_ts / 1_000_000.0

    # ── Module 1: HYDROGEL ─────────────────────────────────────────────────────

    def _hp_logic(self, state: TradingState) -> List[Order]:
        depth = state.order_depths.get(HP)
        if depth is None:
            return []
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0

        # EWMA fair — no static anchor
        prev = self._state["hp_ewma"]
        ewma = mid if prev is None else (1 - HP_EWMA_ALPHA) * prev + HP_EWMA_ALPHA * mid
        self._state["hp_ewma"] = ewma
        fair = ewma

        # L1 imbalance signal
        bv, av = self._top_vol(depth)
        total_vol = bv + av
        imb = (bv - av) / total_vol if total_vol > 0 else 0.0

        # Inventory skew — lean against large positions
        pos = state.position.get(HP, 0)
        inv_lean = 0.0
        if abs(pos) > HP_INV_TRIGGER:
            inv_lean = pos * HP_INV_FACTOR

        # Quote prices: shift both quotes in direction of imbalance
        skew = HP_SKEW * (1 if imb > 0 else -1 if imb < 0 else 0)
        q_bid = round(fair - HP_EDGE + skew - inv_lean)
        q_ask = round(fair + HP_EDGE + skew - inv_lean)

        # Clamp: never cross the existing inside market
        if q_bid >= ba:
            q_bid = ba - 1
        if q_ask <= bb:
            q_ask = bb + 1
        if q_bid >= q_ask:
            q_bid = q_ask - 1

        orders: List[Order] = []

        # Defensive taker: reduce wrong-side exposure when imbalance is present
        if imb != 0.0:
            if imb < 0 and pos > 0:  # price moving down, we are long → hit bid to reduce
                reduce = min(HP_TAKER_MAX, pos, depth.buy_orders.get(bb, 0))
                if reduce > 0:
                    orders.append(Order(HP, bb, -reduce))
                    pos -= reduce
            elif imb > 0 and pos < 0:  # price moving up, we are short → lift ask to reduce
                reduce = min(HP_TAKER_MAX, -pos, abs(depth.sell_orders.get(ba, 0)))
                if reduce > 0:
                    orders.append(Order(HP, ba, reduce))
                    pos += reduce

        # Passive maker quotes
        room_long  = HP_LIMIT - pos
        room_short = HP_LIMIT + pos
        if room_long > 0:
            orders.append(Order(HP, q_bid, room_long))
        if room_short > 0:
            orders.append(Order(HP, q_ask, -room_short))

        return orders

    # ── Module 2: VFE ─────────────────────────────────────────────────────────

    def _vfe_logic(self, state: TradingState) -> Tuple[List[Order], Optional[float]]:
        depth = state.order_depths.get(VFE)
        if depth is None:
            return [], None
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return [], None

        mid = (bb + ba) / 2.0

        prev = self._state["vfe_ewma"]
        ewma = mid if prev is None else (1 - VFE_EWMA_ALPHA) * prev + VFE_EWMA_ALPHA * mid
        self._state["vfe_ewma"] = ewma
        fair = ewma

        pos = state.position.get(VFE, 0)
        inv_lean = 0.0
        if abs(pos) > VFE_INV_TRIGGER:
            inv_lean = pos * VFE_INV_FACTOR

        q_bid = round(fair - VFE_EDGE - inv_lean)
        q_ask = round(fair + VFE_EDGE - inv_lean)

        if q_bid >= ba:
            q_bid = ba - 1
        if q_ask <= bb:
            q_ask = bb + 1
        if q_bid >= q_ask:
            q_bid = q_ask - 1

        orders: List[Order] = []
        room_long  = VFE_LIMIT - pos
        room_short = VFE_LIMIT + pos
        if room_long > 0:
            orders.append(Order(VFE, q_bid, room_long))
        if room_short > 0:
            orders.append(Order(VFE, q_ask, -room_short))

        return orders, mid

    # ── Module 3: VEV ─────────────────────────────────────────────────────────

    def _vev_logic(self, state: TradingState, vfe_mid: float) -> List[Order]:
        return []

    # ── Entry point ────────────────────────────────────────────────────────────

    def run(self, state: TradingState):
        self._load(state)
        result: Dict[str, List[Order]] = {}

        hp_orders = self._hp_logic(state)
        for o in (hp_orders or []):
            result.setdefault(o.symbol, []).append(o)

        vfe_orders, vfe_mid = self._vfe_logic(state)
        for o in (vfe_orders or []):
            result.setdefault(o.symbol, []).append(o)

        if vfe_mid is not None:
            vev_orders = self._vev_logic(state, vfe_mid)
            for o in (vev_orders or []):
                result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save()
