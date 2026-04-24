"""trader_ken_v13.py — The Discord Alpha Engine

This version integrates several "true alpha" signals discovered from community analysis:
1. Model-Free Valuation: VEV Fair = Intrinsic (max(VFE - K, 0)) + Extra Premium.
2. Dynamic Premium Tracking: Uses EMA to track the current market 'Extra Premium' 
   per strike, identifying temporary mispricing and stale orders.
3. Market-Taking Aggression: Actively "takes" (buys/sells) when market 
   prices deviate significantly from the Intrinsic+EMA fair value.
4. "Buy High Sell Low" (Taker Edge): Optimized for capturing 
   IV/RV inefficiency without relying on Black-Scholes.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]

class Trader:
    # ── Feature flags ──────────────────────────────────────────────────────
    ENABLE_HYDROGEL = True
    ENABLE_VFE = True
    ENABLE_VEV = True

    LIMITS: Dict[str, int] = {
        HYDROGEL: 80,
        VFE: 80,
        **{s: 60 for s in VEV_SYMBOLS},
    }

    # ── Param Stack ────────────────────────────────────────────────────────
    VFE_EWMA_ALPHA = 0.20
    VEV_PREMIUM_ALPHA = 0.05 # slow EMA for 'Time Value'
    VEV_TAKE_MARGIN = 1.0    # Take if 1 unit away from fair
    VEV_MM_EDGE = 1.5        # Quote 1.5 units away from fair

    def __init__(self):
        self.history: Dict = {}

    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("hp_ewma", None)
        for strike in VEV_STRIKES:
            self.history.setdefault(f"prem_ema_{strike}", None)

    def _save_state(self) -> str:
        return json.dumps(self.history)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int], int, int]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        bv = depth.buy_orders[bb] if bb is not None else 0
        av = -depth.sell_orders[ba] if ba is not None else 0
        return bb, ba, bv, av

    def _hydrogel_logic(self, state: TradingState) -> List[Order]:
        # Keep same safe OBI MM from v12
        if HYDROGEL not in state.order_depths: return []
        depth = state.order_depths[HYDROGEL]
        bb, ba, bv, av = self._top(depth)
        if bb is None or ba is None: return []
        
        pos = state.position.get(HYDROGEL, 0)
        mid = (bb + ba) / 2.0
        prev = self.history.get("hp_ewma")
        ewma = mid if prev is None else 0.8 * prev + 0.2 * mid
        self.history["hp_ewma"] = ewma
        
        orders = []
        limit = 80
        # Tiny tight scalping
        if ba <= ewma - 1 and pos < 20: 
            orders.append(Order(HYDROGEL, ba, min(20-pos, -depth.sell_orders[ba])))
        if bb >= ewma + 1 and pos > -20:
            orders.append(Order(HYDROGEL, bb, -min(20+pos, depth.buy_orders[bb])))
        return orders

    def _vev_logic(self, state: TradingState) -> List[Order]:
        if VFE not in state.order_depths: return []
        vfe_depth = state.order_depths[VFE]
        v_bb, v_ba, _, _ = self._top(vfe_depth)
        if v_bb is None or v_ba is None: return []
        vfe_mid = (v_bb + v_ba) / 2.0

        all_orders: List[Order] = []
        for K in VEV_STRIKES:
            sym = f"VEV_{K}"
            if sym not in state.order_depths: continue
            depth = state.order_depths[sym]
            bb, ba, _, _ = self._top(depth)
            if bb is None or ba is None: continue
            
            mid = (bb + ba) / 2.0
            intrinsic = max(vfe_mid - K, 0)
            cur_premium = mid - intrinsic
            
            # Update EMA of the "Extra Premium" (Time Value)
            ema_key = f"prem_ema_{K}"
            prev_ema = self.history.get(ema_key)
            if prev_ema is None:
                ema = cur_premium
            else:
                ema = (1 - self.VEV_PREMIUM_ALPHA) * prev_ema + self.VEV_PREMIUM_ALPHA * cur_premium
            self.history[ema_key] = ema
            
            # Calculated Fair Value based on Underlying + Historic Premium
            fair = intrinsic + ema
            pos = state.position.get(sym, 0)
            limit = 60
            
            # ── 1. Taker Sweep (Detect mispriced/stale orders) ──────────
            # if Ask is too cheap, BUY
            if ba <= fair - self.VEV_TAKE_MARGIN and pos < limit:
                sz = min(limit - pos, -depth.sell_orders[ba])
                if sz > 0: all_orders.append(Order(sym, ba, sz)); pos += sz
            # if Bid is too expensive, SELL
            if bb >= fair + self.VEV_TAKE_MARGIN and pos > -limit:
                sz = min(limit + pos, depth.buy_orders[bb])
                if sz > 0: all_orders.append(Order(sym, bb, -sz)); pos -= sz

            # ── 2. Maker Quoting (Symmetric but skewed by inventory) ─────
            # Lean against inventory to revert to zero
            skew = -int(pos / 10.0) 
            qbid = int(round(fair - self.VEV_MM_EDGE + skew))
            qask = int(round(fair + self.VEV_MM_EDGE + skew))
            
            # Ensure we don't cross ourselves
            if qbid >= qask: qbid = qask - 1
            
            # Add resting orders if room left
            room_long = limit - pos
            room_short = limit + pos
            if room_long > 0: all_orders.append(Order(sym, qbid, room_long))
            if room_short > 0: all_orders.append(Order(sym, qask, -room_short))
            
        return all_orders

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        # Alpha Stack: Options Market is leading
        if self.ENABLE_VEV:
            vev_orders = self._vev_logic(state)
            for o in vev_orders:
                result.setdefault(o.symbol, []).append(o)

        if self.ENABLE_HYDROGEL:
            hp_orders = self._hydrogel_logic(state)
            for o in hp_orders:
                result.setdefault(HYDROGEL, []).append(o)

        return result, 0, self._save_state()
