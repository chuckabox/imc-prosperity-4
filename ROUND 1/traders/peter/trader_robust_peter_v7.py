"""
trader_robust_peter_v7.py
=========================
V7: Full-Book Sweeping + Inventory-Adjusted Signals

Key improvements over V6:
- OSMIUM NOW SWEEPS FULL BOOK: was only checking best ask/bid, missing all deeper
  mispriced levels. This is the primary PnL unlock for Osmium.
- Inventory skew applied to TAKE conditions (adj_fair = fair - inv_skew): smooth,
  continuous position control with no hard gates. Naturally discourages compounding
  a losing position while encouraging unwinding it.
- Pepper take_edge lowered to 1.0 (was 1.5-2.0) to capture marginal opportunities.
- Osmium EMA(30) restored (V5 proven better than V6's EMA(20)).
- Second-level passive quotes restored for real-platform value.
- No hard position gates (inv_skew handles it continuously).
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
    # PEPPER ROOT
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

        ema_f = self._ema(hist, 10)
        ema_s = self._ema(hist, 40)
        vol = self._range_vol(hist, 20)

        trend = (ema_f - ema_s) / vol if len(hist) >= 40 else 0.0
        trend_skew = max(-2.0, min(2.0, trend * 6.0))

        fair = ema_f if len(hist) >= 8 else mid
        inv_skew = pos * 0.06
        adj_fair = fair - inv_skew   # inventory-adjusted: lower when long, higher when short
        inv_pressure = abs(pos) / self.LIMIT

        orders: List[Order] = []
        rem_buy = self.LIMIT - pos
        rem_sell = self.LIMIT + pos

        # ── TAKE: sweep full book, adj_fair gates position compounding ──
        # Lower edge captures more opportunities; inv_skew makes it harder to
        # buy when already long and easier to sell (continuous position control).
        take_edge = max(1.0, spread * 0.2)

        for ask, avol in sorted(depth.sell_orders.items()):
            if ask < adj_fair - take_edge and rem_buy > 0:
                qty = min(rem_buy, -avol, 25)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty

        for bid, bvol in sorted(depth.buy_orders.items(), reverse=True):
            if bid > adj_fair + take_edge and rem_sell > 0:
                qty = min(rem_sell, bvol, 25)
                if qty > 0:
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty

        # ── EMERGENCY (safety valve) ──
        if pos > 70 and rem_sell > 0:
            qty = min(pos - 60, rem_sell, 15)
            orders.append(Order(product, bb, -qty))
            rem_sell -= qty
        elif pos < -70 and rem_buy > 0:
            qty = min(abs(pos) - 60, rem_buy, 15)
            orders.append(Order(product, ba, qty))
            rem_buy -= qty

        # ── MAKE: two-sided passive quotes around adj_fair ──
        half_spread = 1 + int(inv_pressure * 2)

        bid_price = math.floor(adj_fair - half_spread + trend_skew)
        ask_price = math.ceil(adj_fair + half_spread + trend_skew)

        bid_price = min(bid_price, bb + 1)
        ask_price = max(ask_price, ba - 1)
        if bid_price >= ask_price:
            bid_price = math.floor(adj_fair)
            ask_price = bid_price + 1

        base_qty = max(8, 18 - int(inv_pressure * 10))

        if rem_buy > 0 and bid_price > 0:
            front = min(rem_buy, base_qty)
            orders.append(Order(product, int(bid_price), front))
            rem_buy -= front
            if rem_buy > 0 and inv_pressure < 0.6:
                orders.append(Order(product, int(bid_price - 1), min(rem_buy, max(6, base_qty - 6))))

        if rem_sell > 0 and ask_price > 0:
            front = min(rem_sell, base_qty)
            orders.append(Order(product, int(ask_price), -front))
            rem_sell -= front
            if rem_sell > 0 and inv_pressure < 0.6:
                orders.append(Order(product, int(ask_price + 1), -min(rem_sell, max(6, base_qty - 6))))

        return orders

    # ------------------------------------------------------------------
    # OSMIUM
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
        inv_skew = pos * 0.07
        adj_fair = fair - inv_skew   # inventory-adjusted fair value
        inv_pressure = abs(pos) / self.LIMIT

        orders: List[Order] = []
        rem_buy = self.LIMIT - pos
        rem_sell = self.LIMIT + pos

        # ── TAKE: SWEEP FULL BOOK (was only best ask/bid in V5/V6) ──
        # Each level of the book checked independently.
        take_margin = max(2.0, spread * 0.4)

        for ask, avol in sorted(depth.sell_orders.items()):
            if ask <= adj_fair - take_margin and rem_buy > 0:
                qty = min(rem_buy, -avol, 25)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty

        for bid, bvol in sorted(depth.buy_orders.items(), reverse=True):
            if bid >= adj_fair + take_margin and rem_sell > 0:
                qty = min(rem_sell, bvol, 25)
                if qty > 0:
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty

        # ── EMERGENCY ──
        if pos > 70 and rem_sell > 0:
            qty = min(pos - 60, rem_sell, 15)
            orders.append(Order(product, bb, -qty))
            rem_sell -= qty
        elif pos < -70 and rem_buy > 0:
            qty = min(abs(pos) - 60, rem_buy, 15)
            orders.append(Order(product, ba, qty))
            rem_buy -= qty

        # ── MAKE: two-sided passive quotes ──
        width = 1.0 + (0.5 if local_vol >= 8 else 0.0) + inv_pressure * 0.5

        bid_price = math.floor(adj_fair - width)
        ask_price = math.ceil(adj_fair + width)

        bid_price = min(bid_price, bb + 1)
        bid_price = min(bid_price, math.floor(fair - 0.5))
        ask_price = max(ask_price, ba - 1)
        ask_price = max(ask_price, math.ceil(fair + 0.5))
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        quote_size = max(10, 18 - int(inv_pressure * 8))

        if rem_buy > 0:
            front = min(rem_buy, quote_size)
            orders.append(Order(product, int(bid_price), front))
            rem_buy -= front
            if rem_buy > 0 and inv_pressure < 0.6:
                orders.append(Order(product, int(bid_price - 1), min(rem_buy, max(6, quote_size // 2))))

        if rem_sell > 0:
            front = min(rem_sell, quote_size)
            orders.append(Order(product, int(ask_price), -front))
            rem_sell -= front
            if rem_sell > 0 and inv_pressure < 0.6:
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
