"""
trader_robust_peter_v5.py
=========================
V5: Unified EMA-Anchored Strategy

Key fixes over V4:
- Pepper Root: EMA(8) fair value replaces raw mid. Take logic now fires.
- Dual-EMA trend signal (EMA8 vs EMA40) skews Pepper quotes for trend regime.
- Osmium: EMA(30) anchor replaces EMA(10). Tape contrarian signal preserved.
- Taking uses EMA vs market price (not mid vs mid — that never fires).
- Osmium taking uses spread-scaled margin (Ken approach: max(2, spread*0.4)).
- Quote sizes shrink with inventory pressure → smoother equity curve.
- Spread widens when over-exposed → less adverse selection.
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

        ema_f = self._ema(hist, 8)
        ema_s = self._ema(hist, 40)
        vol = self._range_vol(hist, 20)

        trend = (ema_f - ema_s) / vol if len(hist) >= 40 else 0.0
        trend_skew = max(-2.0, min(2.0, trend * 6.0))

        fair = ema_f if len(hist) >= 8 else mid
        inv_skew = pos * 0.04
        inv_pressure = abs(pos) / self.LIMIT  # 0.0 to 1.0

        orders: List[Order] = []
        rem_buy = self.LIMIT - pos
        rem_sell = self.LIMIT + pos

        # ── TAKE: buy below EMA, sell above EMA ──
        take_edge = max(1.5, spread * 0.3)

        for ask, avol in sorted(depth.sell_orders.items()):
            if ask < fair - take_edge and rem_buy > 0:
                qty = min(rem_buy, -avol, 20)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty

        for bid, bvol in sorted(depth.buy_orders.items(), reverse=True):
            if bid > fair + take_edge and rem_sell > 0:
                qty = min(rem_sell, bvol, 20)
                if qty > 0:
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty

        # ── EMERGENCY unwind ──
        if pos > 65 and rem_sell > 0:
            qty = min(pos - 55, rem_sell, 15)
            orders.append(Order(product, bb, -qty))
            rem_sell -= qty
        elif pos < -65 and rem_buy > 0:
            qty = min(abs(pos) - 55, rem_buy, 15)
            orders.append(Order(product, ba, qty))
            rem_buy -= qty

        # ── MAKE: penny quotes around EMA with trend + inventory skew ──
        # Spread widens with inventory to reduce adverse selection
        half_spread = 1 + int(inv_pressure * 2)

        bid_price = math.floor(fair - half_spread + trend_skew - inv_skew)
        ask_price = math.ceil(fair + half_spread + trend_skew - inv_skew)

        bid_price = min(bid_price, bb + 1)
        ask_price = max(ask_price, ba - 1)
        if bid_price >= ask_price:
            bid_price = math.floor(fair - inv_skew)
            ask_price = bid_price + 1

        # Quote size shrinks when inventory is stretched
        base_qty = max(10, 20 - int(inv_pressure * 10))

        if rem_buy > 0 and bid_price > 0:
            front = min(rem_buy, base_qty)
            orders.append(Order(product, int(bid_price), front))
            rem_buy -= front
            if rem_buy > 0 and inv_pressure < 0.7:
                orders.append(Order(product, int(bid_price - 1), min(rem_buy, max(6, base_qty - 5))))

        if rem_sell > 0 and ask_price > 0:
            front = min(rem_sell, base_qty)
            orders.append(Order(product, int(ask_price), -front))
            rem_sell -= front
            if rem_sell > 0 and inv_pressure < 0.7:
                orders.append(Order(product, int(ask_price + 1), -min(rem_sell, max(6, base_qty - 5))))

        return orders

    # ------------------------------------------------------------------
    # OSMIUM — EMA + Tape Contrarian Market Maker
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

        anchor = self._ema(hist, 30) if len(hist) >= 5 else mid
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
        inv_skew = pos * 0.05
        inv_pressure = abs(pos) / self.LIMIT

        orders: List[Order] = []
        rem_buy = self.LIMIT - pos
        rem_sell = self.LIMIT + pos

        # ── TAKE: aggressive when strongly mispriced vs EMA ──
        take_margin = max(2.0, spread * 0.4)

        if ba <= fair - take_margin and rem_buy > 0:
            qty = min(rem_buy, -depth.sell_orders[ba], 20)
            if qty > 0:
                orders.append(Order(product, ba, qty))
                rem_buy -= qty

        if bb >= fair + take_margin and rem_sell > 0:
            qty = min(rem_sell, depth.buy_orders[bb], 20)
            if qty > 0:
                orders.append(Order(product, bb, -qty))
                rem_sell -= qty

        # ── EMERGENCY ──
        if pos > 65 and rem_sell > 0:
            qty = min(pos - 55, rem_sell, 15)
            orders.append(Order(product, bb, -qty))
            rem_sell -= qty
        elif pos < -65 and rem_buy > 0:
            qty = min(abs(pos) - 55, rem_buy, 15)
            orders.append(Order(product, ba, qty))
            rem_buy -= qty

        # ── MAKE: passive quotes around EMA ──
        # Width widens in high vol or high inventory
        width = 0.5 + (0.5 if local_vol >= 8 else 0.0) + inv_pressure * 0.5

        bid_price = math.floor(fair - width - inv_skew)
        ask_price = math.ceil(fair + width - inv_skew)

        bid_price = min(bid_price, bb + 1)
        bid_price = min(bid_price, math.floor(fair - 0.5))
        ask_price = max(ask_price, ba - 1)
        ask_price = max(ask_price, math.ceil(fair + 0.5))
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        quote_size = max(12, 20 - int(inv_pressure * 8))

        if rem_buy > 0:
            front = min(rem_buy, quote_size)
            orders.append(Order(product, int(bid_price), front))
            rem_buy -= front
            if rem_buy > 0 and inv_pressure < 0.7:
                orders.append(Order(product, int(bid_price - 1), min(rem_buy, max(6, quote_size // 2))))

        if rem_sell > 0:
            front = min(rem_sell, quote_size)
            orders.append(Order(product, int(ask_price), -front))
            rem_sell -= front
            if rem_sell > 0 and inv_pressure < 0.7:
                orders.append(Order(product, int(ask_price + 1), -min(rem_sell, max(6, quote_size // 2))))

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
