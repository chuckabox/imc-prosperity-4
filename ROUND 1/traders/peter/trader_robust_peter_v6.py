"""
trader_robust_peter_v6.py
=========================
V6: Disciplined Mean-Reversion

Improvements over V5:
- Pepper EMA(15) vs EMA(8): less reactive, cleaner/stronger signals, less noise
- Osmium EMA(20) vs EMA(30): faster response, more taking opportunities
- Position-scaled take size: 20 at pos=0, ramps to 5 at |pos|=50, stops compounding
- One-sided quoting when |pos| > 45: only post orders that reduce exposure
- Stronger inventory skew (0.06/0.07 vs 0.04/0.05): position self-corrects faster
- Single-level passive only (no deep second level): fewer adverse selection fills
- Emergency threshold raised to 70: gradual management prevents reaching it
"""

import json
import math
from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState, Symbol


class Trader:
    LIMIT = 80

    def __init__(self):
        self.history = {}

    def _load_state(self, state: TradingState):
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}

    def _ema(self, prices: list, span: int) -> float:
        if not prices:
            return 0.0
        alpha = 2.0 / (span + 1)
        val = prices[0]
        for p in prices[1:]:
            val = alpha * p + (1 - alpha) * val
        return val

    def _range_vol(self, prices: list, window: int = 20) -> float:
        if len(prices) < 2:
            return 1.0
        recent = prices[-window:] if len(prices) >= window else prices
        return max(1.0, float(max(recent) - min(recent)))

    def _max_take(self, pos: int, direction: int) -> int:
        """
        Scale max take size by current position.
        direction: +1 = buying more, -1 = selling more.
        Shrinks take size as inventory grows in that direction,
        preventing cascading position build-up.
        """
        committed = pos * direction  # positive = already have inventory this way
        if committed >= 50:
            return 0   # never compound beyond 50 in same direction
        if committed >= 30:
            return 8
        if committed >= 15:
            return 14
        return 20

    # ------------------------------------------------------------------
    # PEPPER ROOT — Trend-Skewed EMA Market Maker
    # ------------------------------------------------------------------
    def _pepper_logic(self, state: TradingState) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)

        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        spread = ba - bb

        hist = self.history.get("pp", [])
        hist.append(mid)
        if len(hist) > 300:
            hist = hist[-300:]
        self.history["pp"] = hist

        # EMA(15) smoother anchor — less reactive than EMA(8), cleaner signals
        ema_f = self._ema(hist, 15)
        ema_s = self._ema(hist, 40)
        vol = self._range_vol(hist, 20)

        trend = (ema_f - ema_s) / vol if len(hist) >= 40 else 0.0
        trend_skew = max(-2.0, min(2.0, trend * 6.0))

        fair = ema_f if len(hist) >= 8 else mid
        inv_skew = pos * 0.06   # stronger skew: faster self-correction
        inv_pressure = abs(pos) / self.LIMIT

        orders: List[Order] = []
        rem_buy = self.LIMIT - pos
        rem_sell = self.LIMIT + pos

        # ── TAKE: EMA mean-reversion, position-gated ──
        take_edge = max(2.0, spread * 0.4)

        for ask, avol in sorted(depth.sell_orders.items()):
            if ask < fair - take_edge:
                cap = min(rem_buy, -avol, self._max_take(pos, +1))
                if cap > 0:
                    orders.append(Order(product, ask, cap))
                    rem_buy -= cap

        for bid, bvol in sorted(depth.buy_orders.items(), reverse=True):
            if bid > fair + take_edge:
                cap = min(rem_sell, bvol, self._max_take(pos, -1))
                if cap > 0:
                    orders.append(Order(product, bid, -cap))
                    rem_sell -= cap

        # ── EMERGENCY (safety valve only — gradual management should prevent) ──
        if pos > 70 and rem_sell > 0:
            qty = min(pos - 60, rem_sell, 15)
            orders.append(Order(product, bb, -qty))
            rem_sell -= qty
        elif pos < -70 and rem_buy > 0:
            qty = min(abs(pos) - 60, rem_buy, 15)
            orders.append(Order(product, ba, qty))
            rem_buy -= qty

        # ── MAKE: one-sided when overexposed, two-sided otherwise ──
        half_spread = 2 + int(inv_pressure * 2)   # 2–4 ticks, wider base than V5

        bid_price = math.floor(fair - half_spread + trend_skew - inv_skew)
        ask_price = math.ceil(fair + half_spread + trend_skew - inv_skew)

        bid_price = min(bid_price, bb + 1)
        ask_price = max(ask_price, ba - 1)
        if bid_price >= ask_price:
            bid_price = math.floor(fair - inv_skew)
            ask_price = bid_price + 1

        quote_size = max(8, 18 - int(inv_pressure * 10))

        # One-sided quoting when overexposed: only quote in direction that reduces pos
        want_buy = pos <= 45
        want_sell = pos >= -45

        if want_buy and rem_buy > 0 and bid_price > 0:
            orders.append(Order(product, int(bid_price), min(rem_buy, quote_size)))

        if want_sell and rem_sell > 0 and ask_price > 0:
            orders.append(Order(product, int(ask_price), -min(rem_sell, quote_size)))

        return orders

    # ------------------------------------------------------------------
    # OSMIUM — EMA(20) + Tape Contrarian Market Maker
    # ------------------------------------------------------------------
    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)

        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        spread = ba - bb

        hist = self.history.get("op", [])
        hist.append(mid)
        if len(hist) > 200:
            hist = hist[-200:]
        self.history["op"] = hist

        # EMA(20): faster than EMA(30), more taking opportunities
        anchor = self._ema(hist, 20) if len(hist) >= 5 else mid
        local_vol = self._range_vol(hist, 20)

        # Tape contrarian signal (large trades at extremes → reversion)
        tape_adj = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                qty = abs(trade.quantity)
                if trade.price >= mid:
                    tape_adj += qty
                else:
                    tape_adj -= qty
                if qty >= 15:
                    if trade.price > anchor:
                        tape_adj -= qty * 0.3
                    elif trade.price < anchor:
                        tape_adj += qty * 0.3
        tape_adj = math.copysign(min(abs(tape_adj) * 0.1, 1.5), tape_adj)

        fair = anchor + tape_adj
        inv_skew = pos * 0.07   # stronger than V5's 0.05
        inv_pressure = abs(pos) / self.LIMIT

        orders: List[Order] = []
        rem_buy = self.LIMIT - pos
        rem_sell = self.LIMIT + pos

        # ── TAKE: position-gated ──
        take_margin = max(2.5, spread * 0.5)

        if ba <= fair - take_margin and rem_buy > 0:
            cap = min(rem_buy, -depth.sell_orders[ba], self._max_take(pos, +1))
            if cap > 0:
                orders.append(Order(product, ba, cap))
                rem_buy -= cap

        if bb >= fair + take_margin and rem_sell > 0:
            cap = min(rem_sell, depth.buy_orders[bb], self._max_take(pos, -1))
            if cap > 0:
                orders.append(Order(product, bb, -cap))
                rem_sell -= cap

        # ── EMERGENCY ──
        if pos > 70 and rem_sell > 0:
            qty = min(pos - 60, rem_sell, 15)
            orders.append(Order(product, bb, -qty))
            rem_sell -= qty
        elif pos < -70 and rem_buy > 0:
            qty = min(abs(pos) - 60, rem_buy, 15)
            orders.append(Order(product, ba, qty))
            rem_buy -= qty

        # ── MAKE: one-sided when overexposed ──
        width = 1.0 + (0.5 if local_vol >= 8 else 0.0) + inv_pressure * 0.5

        bid_price = math.floor(fair - width - inv_skew)
        ask_price = math.ceil(fair + width - inv_skew)

        bid_price = min(bid_price, bb + 1)
        bid_price = min(bid_price, math.floor(fair - 0.5))
        ask_price = max(ask_price, ba - 1)
        ask_price = max(ask_price, math.ceil(fair + 0.5))
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        quote_size = max(10, 18 - int(inv_pressure * 8))

        want_buy = pos <= 45
        want_sell = pos >= -45

        if want_buy and rem_buy > 0:
            orders.append(Order(product, int(bid_price), min(rem_buy, quote_size)))

        if want_sell and rem_sell > 0:
            orders.append(Order(product, int(ask_price), -min(rem_sell, quote_size)))

        return orders

    # ------------------------------------------------------------------
    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        pep = self._pepper_logic(state)
        if pep:
            result["INTARIAN_PEPPER_ROOT"] = pep

        osm = self._osmium_logic(state)
        if osm:
            result["ASH_COATED_OSMIUM"] = osm

        return result, 0, json.dumps(self.history)
