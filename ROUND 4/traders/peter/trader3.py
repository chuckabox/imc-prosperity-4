"""trader3.py — Round 4 Production Candidate.
Base: trader1.py + lamp.py
Integrations:
1. Hydrogel and VFE Market Making (from trader1.py, with optimized anchor).
2. Flow Signals for HP and VFE.
3. VEV Intrinsic + Time Value Floor Strategy (from lamp.py), discarding the complex Black-Scholes that blew up trader1.
4. Scale up limits to 200/200/300.
5. VFE Delta Hedging for the VEV options position.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState, Trade

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]
TS_PER_DAY = 1_000_000


class Trader:
    # Updated Position Limits for Round 4
    LIMITS = {HYDROGEL: 200, VFE: 200, **{s: 300 for s in VEV_SYMBOLS}}

    # ── HYDROGEL ─────────────────────────────────────────────────────────────
    HP_ANCHOR = 9994.65 # Updated to mean from findings
    HP_BLEND = 0.35
    HP_EWMA_ALPHA = 0.20
    HP_TAKE_EDGE = 1.5
    HP_TAKER_MAX = 40
    HP_GAMMA = 0.03
    HP_MAKER_EDGE = 1.5
    HP_FLOW_SKEW = 0.1  # Impact of flow on fair value

    # ── VFE ──────────────────────────────────────────────────────────────────
    VFE_EWMA_ALPHA = 0.20
    VFE_MAKER_EDGE = 1.5
    VFE_REV_EMA_ALPHA = 0.03
    VFE_REV_THRESHOLD = 7.0
    VFE_REV_SIZE = 20
    VFE_REV_MAX_POS = 100
    VFE_FLOW_SKEW = 0.2  # Impact of flow on fair value

    # ── VEV (From lamp.py) ───────────────────────────────────────────────────
    VEV_TIME_VALUE_FLOOR = {
        4000: 0.0, 4500: 0.0, 5000: 3.4, 5100: 12.2, 
        5200: 36.3, 5300: 53.7, 5400: 18.6, 5500: 7.3, 
        6000: 0.5, 6500: 0.5
    }
    # We only trade the highly profitable subset of strikes (no broad exposure)
    VEV_STRIKES_TO_TRADE = [4000, 4500, 5000, 5400, 5500]
    VEV_THRESHOLD = 6.8
    VEV_SIZE = 25

    # Delta hedge
    VFE_HEDGE_BAND = 25
    VFE_HEDGE_MAX = 80

    DELTA_APPROX: Dict[int, float] = {
        4000: 1.00, 4500: 0.98, 5000: 0.82, 5100: 0.70,
        5200: 0.57, 5300: 0.44, 5400: 0.31, 5500: 0.21,
        6000: 0.10, 6500: 0.05,
    }

    def __init__(self) -> None:
        self.history: Dict = {}

    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("vfe_rev_ema", None)
        self.history.setdefault("vfe_flow_ema", 0.0)
        self.history.setdefault("hp_flow_ema", 0.0)

    def _save(self) -> str:
        return json.dumps(self.history)

    def _process_trades(self, state: TradingState) -> None:
        # VFE Flow: Mark 67 (B), Mark 49, 22 (S)
        vfe_trades = state.market_trades.get(VFE, [])
        vfe_imbalance = 0
        for t in vfe_trades:
            if getattr(t, 'buyer', '') == 'Mark 67': vfe_imbalance += t.quantity
            if getattr(t, 'seller', '') == 'Mark 67': vfe_imbalance -= t.quantity
            if getattr(t, 'buyer', '') in ['Mark 49', 'Mark 22']: vfe_imbalance -= t.quantity
            if getattr(t, 'seller', '') in ['Mark 49', 'Mark 22']: vfe_imbalance += t.quantity
        
        prev_vfe_flow = self.history.get("vfe_flow_ema", 0.0)
        self.history["vfe_flow_ema"] = 0.85 * prev_vfe_flow + 0.15 * vfe_imbalance

        # HGP Flow: Mark 38 (B), Mark 14 (S)
        hp_trades = state.market_trades.get(HYDROGEL, [])
        hp_imbalance = 0
        for t in hp_trades:
            if getattr(t, 'buyer', '') == 'Mark 38': hp_imbalance += t.quantity
            if getattr(t, 'seller', '') == 'Mark 38': hp_imbalance -= t.quantity
            if getattr(t, 'buyer', '') == 'Mark 14': hp_imbalance -= t.quantity
            if getattr(t, 'seller', '') == 'Mark 14': hp_imbalance += t.quantity
        
        prev_hp_flow = self.history.get("hp_flow_ema", 0.0)
        self.history["hp_flow_ema"] = 0.85 * prev_hp_flow + 0.15 * hp_imbalance

    @staticmethod
    def _top(d: OrderDepth) -> Tuple[Optional[int], Optional[int], int, int]:
        bb = max(d.buy_orders) if d.buy_orders else None
        ba = min(d.sell_orders) if d.sell_orders else None
        bv = d.buy_orders[bb] if bb is not None else 0
        av = -d.sell_orders[ba] if ba is not None else 0
        return bb, ba, bv, av

    @staticmethod
    def _mid(d: OrderDepth) -> Optional[float]:
        bb = max(d.buy_orders) if d.buy_orders else None
        ba = min(d.sell_orders) if d.sell_orders else None
        return (bb + ba) / 2.0 if bb is not None and ba is not None else None

    # ── HYDROGEL ─────────────────────────────────────────────────────────────
    def _hp(self, state: TradingState) -> List[Order]:
        od = state.order_depths.get(HYDROGEL)
        if not od: return []
        bb, ba, _, _ = self._top(od)
        if bb is None or ba is None: return []

        mid = (bb + ba) / 2.0
        prev = self.history.get("hp_ewma")
        ewma = mid if prev is None else (1 - self.HP_EWMA_ALPHA) * prev + self.HP_EWMA_ALPHA * mid
        self.history["hp_ewma"] = ewma

        # Fair price with flow skew
        flow_skew = self.history.get("hp_flow_ema", 0.0) * self.HP_FLOW_SKEW
        fair = (1 - self.HP_BLEND) * ewma + self.HP_BLEND * self.HP_ANCHOR + flow_skew
        
        pos = state.position.get(HYDROGEL, 0)
        lim = self.LIMITS[HYDROGEL]
        orders: List[Order] = []

        # Taker
        if ba <= fair - self.HP_TAKE_EDGE and pos < lim:
            qty = min(self.HP_TAKER_MAX, lim - pos, -od.sell_orders[ba])
            if qty > 0:
                orders.append(Order(HYDROGEL, ba, qty))
                pos += qty
        if bb >= fair + self.HP_TAKE_EDGE and pos > -lim:
            qty = min(self.HP_TAKER_MAX, lim + pos, od.buy_orders[bb])
            if qty > 0:
                orders.append(Order(HYDROGEL, bb, -qty))
                pos -= qty

        # Maker
        reservation = fair - self.HP_GAMMA * pos
        bid_px = int(round(reservation - self.HP_MAKER_EDGE))
        ask_px = int(round(reservation + self.HP_MAKER_EDGE))
        if bid_px >= ba: bid_px = ba - 1
        if ask_px <= bb: ask_px = bb + 1
        if pos < lim: orders.append(Order(HYDROGEL, bid_px, lim - pos))
        if pos > -lim: orders.append(Order(HYDROGEL, ask_px, -(lim + pos)))
        return orders

    # ── VFE ──────────────────────────────────────────────────────────────────
    def _vfe(self, state: TradingState, target_delta_pos: int) -> List[Order]:
        od = state.order_depths.get(VFE)
        if not od: return []
        bb, ba, _, _ = self._top(od)
        if bb is None or ba is None: return []

        mid = (bb + ba) / 2.0
        prev_ewma = self.history.get("vfe_ewma")
        ewma = mid if prev_ewma is None else (1 - self.VFE_EWMA_ALPHA) * prev_ewma + self.VFE_EWMA_ALPHA * mid
        self.history["vfe_ewma"] = ewma

        # Slow mean-rev EMA
        prev_rev = self.history.get("vfe_rev_ema")
        rev_ema = mid if prev_rev is None else (1 - self.VFE_REV_EMA_ALPHA) * prev_rev + self.VFE_REV_EMA_ALPHA * mid
        self.history["vfe_rev_ema"] = rev_ema

        # Fair with flow skew
        flow_skew = self.history.get("vfe_flow_ema", 0.0) * self.VFE_FLOW_SKEW
        fair = ewma + flow_skew
        
        pos = state.position.get(VFE, 0)
        lim = self.LIMITS[VFE]
        orders: List[Order] = []

        # Mean-rev taker
        dev = mid - rev_ema
        if dev <= -self.VFE_REV_THRESHOLD and pos < self.VFE_REV_MAX_POS:
            sz = min(self.VFE_REV_SIZE, self.VFE_REV_MAX_POS - pos, -od.sell_orders[ba])
            if sz > 0:
                orders.append(Order(VFE, ba, sz))
                pos += sz
        elif dev >= self.VFE_REV_THRESHOLD and pos > -self.VFE_REV_MAX_POS:
            sz = min(self.VFE_REV_SIZE, self.VFE_REV_MAX_POS + pos, od.buy_orders[bb])
            if sz > 0:
                orders.append(Order(VFE, bb, -sz))
                pos -= sz

        # Delta hedge taker
        residual = target_delta_pos - pos
        if abs(residual) >= self.VFE_HEDGE_BAND:
            if residual > 0 and pos < lim:
                hq = min(self.VFE_HEDGE_MAX, residual, lim - pos, -od.sell_orders[ba])
                if hq > 0:
                    orders.append(Order(VFE, ba, hq))
                    pos += hq
            elif residual < 0 and pos > -lim:
                hq = min(self.VFE_HEDGE_MAX, -residual, lim + pos, od.buy_orders[bb])
                if hq > 0:
                    orders.append(Order(VFE, bb, -hq))
                    pos -= hq

        # Maker
        bid_px = int(round(fair - self.VFE_MAKER_EDGE))
        ask_px = int(round(fair + self.VFE_MAKER_EDGE))
        if bid_px >= ba: bid_px = ba - 1
        if ask_px <= bb: ask_px = bb + 1
        if pos < lim: orders.append(Order(VFE, bid_px, min(lim - pos, 100)))
        if pos > -lim: orders.append(Order(VFE, ask_px, -min(lim + pos, 100)))
        return orders

    # ── VEV (Time-Value Floor Logic) ─────────────────────────────────────────
    def _vev_orders(self, symbol: str, state: TradingState, vfe_mid: float) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth or vfe_mid is None: return []
        
        k = int(symbol.split("_")[1])
        if k not in self.VEV_STRIKES_TO_TRADE: return []
        
        bb, ba, _, _ = self._top(depth)
        if bb is None or ba is None: return []
        
        theo = max(vfe_mid - k, 0.0) + self.VEV_TIME_VALUE_FLOOR.get(k, 0.0)
        mid = 0.5 * (bb + ba)
        mispricing = mid - theo
        
        pos = state.position.get(symbol, 0)
        lim = self.LIMITS.get(symbol, 300)
        buy_cap = max(0, lim - pos)
        sell_cap = max(0, lim + pos)
        
        orders = []
        if k in (4000, 4500):
            # ITM parity arb - check against bid/ask directly
            if ba < theo - 0.5 and buy_cap > 0:
                orders.append(Order(symbol, ba, min(self.VEV_SIZE, buy_cap)))
            elif bb > theo + 0.5 and sell_cap > 0:
                orders.append(Order(symbol, bb, -min(self.VEV_SIZE, sell_cap)))
        else:
            # Standard edge taking
            if mispricing < -self.VEV_THRESHOLD and buy_cap > 0:
                orders.append(Order(symbol, ba, min(self.VEV_SIZE, buy_cap)))
            elif mispricing > self.VEV_THRESHOLD and sell_cap > 0:
                orders.append(Order(symbol, bb, -min(self.VEV_SIZE, sell_cap)))
            
        return orders

    def _target_vfe_from_delta(self, state: TradingState) -> int:
        net_delta = 0.0
        for k in VEV_STRIKES:
            pos = state.position.get(f"VEV_{k}", 0)
            if pos == 0: continue
            delta = self.DELTA_APPROX.get(k, 0.5)
            net_delta += pos * delta
        lim = self.LIMITS[VFE]
        return max(-lim, min(lim, int(round(-net_delta))))

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._load(state)
        self._process_trades(state)
        result: Dict[str, List[Order]] = {}

        # Hydrogel MM
        for o in self._hp(state):
            result.setdefault(o.symbol, []).append(o)

        # VEV Trades
        od = state.order_depths.get(VFE)
        vfe_mid = self._mid(od) if od else None
        
        if vfe_mid is not None:
            for k in self.VEV_STRIKES_TO_TRADE:
                sym = f"VEV_{k}"
                for o in self._vev_orders(sym, state, vfe_mid):
                    result.setdefault(o.symbol, []).append(o)

        # VFE Hedging & MM
        target_vfe = self._target_vfe_from_delta(state)
        for o in self._vfe(state, target_vfe):
            result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save()
