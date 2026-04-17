"""
trader_robust_peter_v4.py
=========================
V4: Smooth Equity Curve Market Maker

DESIGN PRINCIPLE: separate TAKING logic (conservative, backtester-safe) from
MAKING logic (adaptive, shines on real platform).

TAKING uses RAW MID (never fights trends, near-zero backtester PnL).
MAKING uses adaptive fair (pennying with inventory lean, earns on real platform).

Backtester limitation: only fills aggressive orders → passive MM shows ~$0.
Real platform: penny fills constantly → smooth monotonic PnL curve.
"""

import json
import math
from typing import Dict, List, Any

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

    # ------------------------------------------------------------------
    # PEPPER ROOT — Kelp Treatment
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
        skew = pos * 0.04

        # TAKE fair = raw mid (conservative, never trend-fights)
        take_fair = mid - skew
        # MAKE fair = raw mid (user specified: mid-price as absolute anchor)
        make_fair = mid - skew

        orders: List[Order] = []
        rem_buy = self.LIMIT - pos
        rem_sell = self.LIMIT + pos

        # ── TAKE: sweep genuinely mispriced ──
        for ask, vol in sorted(depth.sell_orders.items()):
            if ask < take_fair and rem_buy > 0:
                qty = min(rem_buy, -vol)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty

        for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
            if bid > take_fair and rem_sell > 0:
                qty = min(rem_sell, vol)
                if qty > 0:
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty

        # ── EMERGENCY: force unwind at extreme ──
        if abs(pos) > 60:
            unwind = min(abs(pos) - 50, 15)
            if pos > 60 and rem_sell > 0:
                qty = min(unwind, rem_sell)
                orders.append(Order(product, bb, -qty))
                rem_sell -= qty
            elif pos < -60 and rem_buy > 0:
                qty = min(unwind, rem_buy)
                orders.append(Order(product, ba, qty))
                rem_buy -= qty

        # ── PENNY: passive quotes (real platform revenue) ──
        bid_price = min(bb + 1, math.floor(make_fair))
        ask_price = max(ba - 1, math.ceil(make_fair))

        if bid_price >= ask_price:
            if pos > 0:
                ask_price = math.ceil(make_fair)
                bid_price = ask_price - 1
            elif pos < 0:
                bid_price = math.floor(make_fair)
                ask_price = bid_price + 1
            else:
                bid_price = math.floor(mid)
                ask_price = bid_price + 1

        if rem_buy > 0 and bid_price > 0:
            front = min(rem_buy, 20)
            orders.append(Order(product, int(bid_price), front))
            rem_buy -= front
            if rem_buy > 0:
                orders.append(Order(product, int(bid_price - 1), min(rem_buy, 15)))

        if rem_sell > 0 and ask_price > 0:
            front = min(rem_sell, 20)
            orders.append(Order(product, int(ask_price), -front))
            rem_sell -= front
            if rem_sell > 0:
                orders.append(Order(product, int(ask_price + 1), -min(rem_sell, 15)))

        return orders

    # ------------------------------------------------------------------
    # OSMIUM — Squid Ink Treatment
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
        skew = pos * 0.05

        # Price history for EMA
        hist = self.history.get("op", [])
        hist.append(mid)
        if len(hist) > 200:
            hist = hist[-200:]
        self.history["op"] = hist

        # TAKE fair = raw mid (conservative, backtester-safe)
        take_fair = mid - skew

        # MAKE fair = EMA + tape (adaptive, only affects real platform penny quotes)
        ema = self._ema(hist, 10) if len(hist) >= 5 else mid

        # Tape pattern detection (real platform only, backtester has no market_trades)
        tape_adj = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                qty = abs(trade.quantity)
                if trade.price >= mid:
                    tape_adj += qty
                else:
                    tape_adj -= qty
                # Large trades at extremes → contrarian signal (Squid Ink pattern)
                if qty >= 15:
                    if trade.price > ema:
                        tape_adj -= qty * 0.3  # Big buy at high → bearish
                    elif trade.price < ema:
                        tape_adj += qty * 0.3  # Big sell at low → bullish

        tape_adj = math.copysign(min(abs(tape_adj) * 0.08, 1.5), tape_adj)
        make_fair = ema + tape_adj - skew

        orders: List[Order] = []
        rem_buy = self.LIMIT - pos
        rem_sell = self.LIMIT + pos

        # ── TAKE: sweep genuinely mispriced (raw mid, no EMA lag) ──
        for ask, vol in sorted(depth.sell_orders.items()):
            if ask < take_fair and rem_buy > 0:
                qty = min(rem_buy, -vol, 15)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty

        for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
            if bid > take_fair and rem_sell > 0:
                qty = min(rem_sell, vol, 15)
                if qty > 0:
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty

        # ── EMERGENCY ──
        if abs(pos) > 60:
            unwind = min(abs(pos) - 50, 15)
            if pos > 60 and rem_sell > 0:
                qty = min(unwind, rem_sell)
                orders.append(Order(product, bb, -qty))
                rem_sell -= qty
            elif pos < -60 and rem_buy > 0:
                qty = min(unwind, rem_buy)
                orders.append(Order(product, ba, qty))
                rem_buy -= qty

        # ── PENNY: adaptive positioning (EMA + tape, real platform) ──
        bid_price = min(bb + 1, math.floor(make_fair - 0.5))
        ask_price = max(ba - 1, math.ceil(make_fair + 0.5))

        if bid_price >= ask_price:
            if pos > 0:
                ask_price = math.ceil(make_fair + 0.1)
                bid_price = ask_price - 1
            elif pos < 0:
                bid_price = math.floor(make_fair - 0.1)
                ask_price = bid_price + 1
            else:
                bid_price = math.floor(mid)
                ask_price = bid_price + 1

        if rem_buy > 0 and bid_price > 0:
            front = min(rem_buy, 20)
            orders.append(Order(product, int(bid_price), front))
            rem_buy -= front
            if rem_buy > 0:
                orders.append(Order(product, int(bid_price - 1), min(rem_buy, 15)))

        if rem_sell > 0 and ask_price > 0:
            front = min(rem_sell, 20)
            orders.append(Order(product, int(ask_price), -front))
            rem_sell -= front
            if rem_sell > 0:
                orders.append(Order(product, int(ask_price + 1), -min(rem_sell, 15)))

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

        trader_data = json.dumps(self.history)
        return result, 0, trader_data
