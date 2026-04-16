import json
import math
from typing import Dict, List, Any

from datamodel import Order, OrderDepth, TradingState, Symbol


class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        conversions: int,
        trader_data: str,
    ) -> None:
        pass


logger = Logger()


class Trader:
    """
    Robust Adaptive Trader (Ken v2) - Drift Defense
    ----------------------------------------------
    Start from the profitable v1 passive-first core.

    Targeted change: in low-vol / weak-trend regimes where inventory starts
    accumulating (classic slow-drift adverse selection), widen quotes and
    cut size. Everywhere else behave like v1.
    """

    WARMUP_PEPPER = 8
    WARMUP_OSMIUM = 8

    def __init__(self):
        self.limits = {
            "ASH_COATED_OSMIUM": 80,
            "INTARIAN_PEPPER_ROOT": 80,
        }
        self.history = {}

    def _load_state(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
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

    def _get_mid(self, depth: OrderDepth) -> float:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb and ba:
            return (bb + ba) / 2.0
        return bb or ba or 0.0

    def _clamp(self, value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    # ------------------------------------------------------------------
    # PEPPER ROOT
    # ------------------------------------------------------------------
    def _pepper_logic(self, state: TradingState) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)
        limit = self.limits[product]
        mid = self._get_mid(depth)
        if mid == 0:
            return []

        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        spread = (best_ask - best_bid) if (best_bid and best_ask) else 20

        hist = self.history.get("pp", [])
        hist.append(mid)
        if len(hist) > 200:
            hist = hist[-200:]
        self.history["pp"] = hist

        ema_f = self._ema(hist, 8)
        ema_s = self._ema(hist, 40)
        recent = hist[-20:] if len(hist) >= 20 else hist
        vol = max(1.0, float(max(recent) - min(recent)))
        trend = (ema_f - ema_s) / vol if len(hist) >= 40 else 0.0
        trend_skew = self._clamp(trend * 6.0, -2.0, 2.0)

        fair = ema_f if len(hist) >= self.WARMUP_PEPPER else mid
        inv_skew = pos * 0.03

        # Default v1 sizing/offsets
        buy_offset = 1
        ask_offset = 1
        base_qty = 20
        deep_qty = 15

        # Drift defense: only activate when (a) low vol, (b) weak trend signal,
        # and (c) inventory already leaning.
        low_vol = vol < 8.0
        weak_trend = abs(trend) < 0.10
        leaning = abs(pos) >= 18
        if low_vol and weak_trend and leaning:
            buy_offset = 3
            ask_offset = 3
            base_qty = 10
            deep_qty = 6

        orders = []
        buy_cap = limit - pos
        sell_cap = limit + pos

        if best_bid and buy_cap > 0:
            price = best_bid + 1
            price = min(price, math.floor(fair - buy_offset + trend_skew - inv_skew))
            q = min(buy_cap, base_qty)
            orders.append(Order(product, int(price), q))
            rem = buy_cap - q
            if rem > 0:
                orders.append(Order(product, int(price - 2), min(rem, deep_qty)))

        if best_ask and sell_cap > 0:
            price = best_ask - 1
            price = max(price, math.ceil(fair + ask_offset + trend_skew - inv_skew))
            q = min(sell_cap, base_qty)
            orders.append(Order(product, int(price), -q))
            rem = sell_cap - q
            if rem > 0:
                orders.append(Order(product, int(price + 2), -min(rem, deep_qty)))

        if pos > 60 and best_bid:
            orders.append(Order(product, best_bid, -min(pos - 50, 15)))
        elif pos < -60 and best_ask:
            orders.append(Order(product, best_ask, min(abs(pos) - 50, 15)))

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
        limit = self.limits[product]
        mid = self._get_mid(depth)
        if mid == 0:
            return []

        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        spread = (best_ask - best_bid) if (best_bid and best_ask) else 20

        hist = self.history.get("op", [])
        hist.append(mid)
        if len(hist) > 100:
            hist = hist[-100:]
        self.history["op"] = hist

        anchor = self._ema(hist, 50)
        recent = hist[-20:] if len(hist) >= 20 else hist
        local_vol = max(1.0, float(max(recent) - min(recent)))

        tape_adj = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= mid:
                    tape_adj += trade.quantity
                else:
                    tape_adj -= trade.quantity
        tape_adj = math.copysign(min(abs(tape_adj) * 0.15, 2.0), tape_adj)

        fair = anchor + tape_adj
        skew = pos * 0.05
        inv_stretched = abs(pos) >= 35
        quote_size = 20
        if inv_stretched:
            quote_size = 14

        # Slightly widen only in high local vol
        width = 0.5 + (0.5 if local_vol >= 8 else 0.0)

        bid_price = math.floor(fair - width - skew)
        ask_price = math.ceil(fair + width - skew)

        if best_bid:
            bid_price = min(bid_price, best_bid + 1)
            bid_price = min(bid_price, math.floor(fair - width))
        if best_ask:
            ask_price = max(ask_price, best_ask - 1)
            ask_price = max(ask_price, math.ceil(fair + width))
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        orders = []
        rem_buy = limit - pos
        rem_sell = limit + pos

        take_margin = max(2.0, spread * 0.4)
        if best_ask and best_ask <= fair - take_margin and rem_buy > 0:
            q = min(rem_buy, -depth.sell_orders.get(best_ask, 0))
            if q > 0:
                orders.append(Order(product, best_ask, q))
                rem_buy -= q

        if best_bid and best_bid >= fair + take_margin and rem_sell > 0:
            q = min(rem_sell, depth.buy_orders.get(best_bid, 0))
            if q > 0:
                orders.append(Order(product, best_bid, -q))
                rem_sell -= q

        if rem_buy > 0:
            top = min(rem_buy, quote_size)
            deep = rem_buy - top
            orders.append(Order(product, int(bid_price), top))
            if deep > 0 and not inv_stretched:
                orders.append(Order(product, int(bid_price - 1), min(deep, max(6, quote_size // 2))))

        if rem_sell > 0:
            top = min(rem_sell, quote_size)
            deep = rem_sell - top
            orders.append(Order(product, int(ask_price), -top))
            if deep > 0 and not inv_stretched:
                orders.append(Order(product, int(ask_price + 1), -min(deep, max(6, quote_size // 2))))

        # Keep v1 behavior: no extra emergency unwind beyond quote skew

        return orders

    # ------------------------------------------------------------------
    def run(self, state: TradingState):
        self._load_state(state.traderData)
        result = {}

        pep = self._pepper_logic(state)
        if pep:
            result["INTARIAN_PEPPER_ROOT"] = pep

        osm = self._osmium_logic(state)
        if osm:
            result["ASH_COATED_OSMIUM"] = osm

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
