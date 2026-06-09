"""
GOAT V6 - Live-Calibrated for IMC Prosperity 4 Round 3

Live submission of V5 (day 2) showed:
- HP: 0 PnL (no fills) - inside-spread quotes never matched live
- VFE: bleeding (-140 trough) - trend lag in fair value
- Wide options 5000-5200: +$25-40 each (the ONLY thing working)
- Tight options 5300-5500: 0 PnL (touch quotes queue-stuck)
- Deep ITM/OTM: always 0

V6 design:
1. HP: aggressive cross-spread taking on EMA edge + queue-join AT touch (not inside).
   Forced unwind at 60% of limit. No multi-level ladder (those don't fill live).
2. VFE: same touch-quoting + trend-aware skew. Unwind into trends aggressively.
3. Wide options: keep V5 logic with minor tuning - this works.
4. Tight options: take-only on EMA deviation + small queue-join at touch.
   No more directional posting (didn't work live).
5. Deep OTM (6000, 6500): post sells at 1 (free hit if anyone bids).
6. Deep ITM (4000, 4500): drop entirely - never trades.
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import json


LIMITS = {
    "HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300, "VEV_4500": 300,
    "VEV_5000": 300, "VEV_5100": 300, "VEV_5200": 300,
    "VEV_5300": 300, "VEV_5400": 300, "VEV_5500": 300,
    "VEV_6000": 300, "VEV_6500": 300,
}


class Trader:

    def _best_bid(self, od):
        return max(od.buy_orders.keys()) if od.buy_orders else None

    def _best_ask(self, od):
        return min(od.sell_orders.keys()) if od.sell_orders else None

    def _mid(self, od):
        b, a = self._best_bid(od), self._best_ask(od)
        if b is not None and a is not None:
            return (b + a) / 2.0
        return None

    def _microprice(self, od):
        b, a = self._best_bid(od), self._best_ask(od)
        if b is None or a is None:
            return self._mid(od)
        bv = od.buy_orders[b]
        av = -od.sell_orders[a]
        denom = bv + av
        if denom <= 0:
            return (b + a) / 2.0
        return (b * av + a * bv) / denom

    def _ema(self, sd, key, value, alpha):
        sd[key] = value if key not in sd else alpha * value + (1 - alpha) * sd[key]
        return sd[key]

    def _take(self, product, od, fair, position, edge, orders, max_take=999):
        limit = LIMITS[product]
        cap_buy = limit - position
        cap_sell = limit + position
        for ask in sorted(od.sell_orders.keys()):
            if ask <= fair - edge and cap_buy > 0 and max_take > 0:
                vol = min(-od.sell_orders[ask], cap_buy, max_take)
                if vol > 0:
                    orders.append(Order(product, ask, vol))
                    cap_buy -= vol
                    max_take -= vol
            else:
                break
        for bid in sorted(od.buy_orders.keys(), reverse=True):
            if bid >= fair + edge and cap_sell > 0 and max_take > 0:
                vol = min(od.buy_orders[bid], cap_sell, max_take)
                if vol > 0:
                    orders.append(Order(product, bid, -vol))
                    cap_sell -= vol
                    max_take -= vol
            else:
                break

    def _force_unwind(self, product, od, position, orders, threshold=0.60, target_frac=0.30):
        """Cross spread to flatten when position too big."""
        limit = LIMITS[product]
        if abs(position) < int(threshold * limit):
            return
        target = int(target_frac * limit)
        if position > 0:
            for bid in sorted(od.buy_orders.keys(), reverse=True):
                vol = min(od.buy_orders[bid], position - target, 50)
                if vol > 0:
                    orders.append(Order(product, bid, -vol))
                    position -= vol
                if position <= target:
                    break
        else:
            for ask in sorted(od.sell_orders.keys()):
                vol = min(-od.sell_orders[ask], -position - target, 50)
                if vol > 0:
                    orders.append(Order(product, ask, vol))
                    position += vol
                if position >= -target:
                    break

    # =====================================================================
    # HYDROGEL_PACK: queue-join at touch + cross-spread taking on EMA edge
    # =====================================================================
    def _trade_hp(self, state, sd):
        product = "HYDROGEL_PACK"
        orders = []
        if product not in state.order_depths:
            return orders
        od = state.order_depths[product]
        pos = state.position.get(product, 0)
        bid = self._best_bid(od)
        ask = self._best_ask(od)
        if bid is None or ask is None:
            return orders
        mid = (bid + ask) / 2.0

        fast = self._ema(sd, "hp_fast", mid, 0.25)
        slow = self._ema(sd, "hp_slow", mid, 0.02)
        fair = 0.7 * fast + 0.3 * slow

        # 1. Cross-spread take when there's a clear edge (3+ ticks)
        self._take(product, od, fair, pos, edge=3.0, orders=orders, max_take=40)
        approx_pos = pos + sum(o.quantity for o in orders)

        # 2. Force unwind near limit
        self._force_unwind(product, od, approx_pos, orders, threshold=0.60, target_frac=0.30)
        approx_pos = pos + sum(o.quantity for o in orders)

        # 3. Queue-join AT touch (best bid + best ask), not inside spread
        cap_buy = LIMITS[product] - approx_pos
        cap_sell = LIMITS[product] + approx_pos
        skew = approx_pos / LIMITS[product]

        # Skew-aware quote sizing
        bid_qty = int(20 * max(0.1, 1 - skew))  # smaller bid when long
        ask_qty = int(20 * max(0.1, 1 + skew))  # smaller ask when short

        if cap_buy > 0 and skew < 0.75:
            orders.append(Order(product, bid, min(bid_qty, cap_buy)))
        if cap_sell > 0 and skew > -0.75:
            orders.append(Order(product, ask, -min(ask_qty, cap_sell)))

        # 4. Also post one tick inside spread for opportunistic fill if spread is wide
        if ask - bid >= 4:
            inside_bid = bid + 1
            inside_ask = ask - 1
            if cap_buy > bid_qty and skew < 0.5:
                orders.append(Order(product, inside_bid, min(8, cap_buy - bid_qty)))
            if cap_sell > ask_qty and skew > -0.5:
                orders.append(Order(product, inside_ask, -min(8, cap_sell - ask_qty)))

        return orders

    # =====================================================================
    # VELVETFRUIT_EXTRACT: trend-aware taking + touch quotes with strong skew
    # =====================================================================
    def _trade_vev_spot(self, state, sd):
        product = "VELVETFRUIT_EXTRACT"
        orders = []
        if product not in state.order_depths:
            return orders
        od = state.order_depths[product]
        pos = state.position.get(product, 0)
        bid = self._best_bid(od)
        ask = self._best_ask(od)
        if bid is None or ask is None:
            return orders
        mid = (bid + ask) / 2.0

        fast = self._ema(sd, "vev_fast", mid, 0.5)
        slow = self._ema(sd, "vev_slow", mid, 0.04)
        trend = fast - slow
        # Don't fight trend: fair = fast (no -0.4*trend like V5)
        fair = fast

        # Asymmetric take edges based on trend
        # If trending up, take harder on the buy side (asks below fair)
        buy_edge = 1.5 if trend > 0 else 2.5
        sell_edge = 1.5 if trend < 0 else 2.5

        # Cross-spread take
        cap_buy = LIMITS[product] - pos
        cap_sell = LIMITS[product] + pos
        for ask_px in sorted(od.sell_orders.keys()):
            if ask_px <= fair - buy_edge and cap_buy > 0:
                vol = min(-od.sell_orders[ask_px], cap_buy, 40)
                if vol > 0:
                    orders.append(Order(product, ask_px, vol))
                    cap_buy -= vol
            else:
                break
        for bid_px in sorted(od.buy_orders.keys(), reverse=True):
            if bid_px >= fair + sell_edge and cap_sell > 0:
                vol = min(od.buy_orders[bid_px], cap_sell, 40)
                if vol > 0:
                    orders.append(Order(product, bid_px, -vol))
                    cap_sell -= vol
            else:
                break

        approx_pos = pos + sum(o.quantity for o in orders)

        # Aggressive unwind when trend is against position
        unwind_threshold = 0.50 if abs(trend) > 1.5 else 0.65
        self._force_unwind(product, od, approx_pos, orders,
                          threshold=unwind_threshold, target_frac=0.25)
        approx_pos = pos + sum(o.quantity for o in orders)

        # Touch quotes with trend-aware skew
        cap_buy = LIMITS[product] - approx_pos
        cap_sell = LIMITS[product] + approx_pos
        skew = approx_pos / LIMITS[product]

        # Trend-skewed sizing
        bid_qty = 25
        ask_qty = 25
        if trend > 1:
            ask_qty = int(ask_qty * 0.4)  # less aggressive selling in uptrend
            bid_qty = int(bid_qty * 1.2)
        elif trend < -1:
            bid_qty = int(bid_qty * 0.4)
            ask_qty = int(ask_qty * 1.2)
        # Position skew
        bid_qty = int(bid_qty * max(0.1, 1 - skew))
        ask_qty = int(ask_qty * max(0.1, 1 + skew))

        if cap_buy > 0 and skew < 0.7 and trend > -2.5:
            orders.append(Order(product, bid, min(bid_qty, cap_buy)))
        if cap_sell > 0 and skew > -0.7 and trend < 2.5:
            orders.append(Order(product, ask, -min(ask_qty, cap_sell)))

        return orders

    # =====================================================================
    # WIDE OPTIONS (5000, 5100, 5200): the working V5 strategy, slightly tuned
    # =====================================================================
    def _trade_wide_option(self, prod, state, sd):
        orders = []
        if prod not in state.order_depths:
            return orders
        od = state.order_depths[prod]
        pos = state.position.get(prod, 0)
        bid = self._best_bid(od)
        ask = self._best_ask(od)
        if bid is None or ask is None:
            return orders
        mid = (bid + ask) / 2.0
        spread = ask - bid

        fast = self._ema(sd, f"{prod}_fast", mid, 0.4)
        slow = self._ema(sd, f"{prod}_slow", mid, 0.05)
        fair = fast

        # EMA mean-reversion taking
        take_edge = max(1.5, spread * 0.45)
        self._take(prod, od, fair, pos, edge=take_edge, orders=orders, max_take=35)
        approx_pos = pos + sum(o.quantity for o in orders)

        self._force_unwind(prod, od, approx_pos, orders, threshold=0.65, target_frac=0.30)
        approx_pos = pos + sum(o.quantity for o in orders)

        # Inside-spread MM with skew
        skew = approx_pos / 300
        bid_off = max(1, int(spread * 0.3))
        ask_off = max(1, int(spread * 0.3))
        our_bid = int(round(fair - bid_off - skew * bid_off * 2.0))
        our_ask = int(round(fair + ask_off - skew * ask_off * 2.0))
        if our_bid >= ask:
            our_bid = ask - 1
        if our_ask <= bid:
            our_ask = bid + 1
        if our_bid >= our_ask:
            our_bid = bid
            our_ask = ask

        cap_buy = 300 - approx_pos
        cap_sell = 300 + approx_pos
        if cap_buy > 0:
            orders.append(Order(prod, our_bid, min(30, cap_buy)))
        if cap_sell > 0:
            orders.append(Order(prod, our_ask, -min(30, cap_sell)))
        return orders

    # =====================================================================
    # TIGHT OPTIONS (5300, 5400, 5500): take-only + small touch quotes
    # =====================================================================
    def _trade_tight_option(self, prod, state, sd):
        orders = []
        if prod not in state.order_depths:
            return orders
        od = state.order_depths[prod]
        pos = state.position.get(prod, 0)
        bid = self._best_bid(od)
        ask = self._best_ask(od)
        if bid is None or ask is None:
            return orders
        mid = (bid + ask) / 2.0

        fast = self._ema(sd, f"{prod}_fast", mid, 0.4)
        fair = fast

        # Aggressive taking on tiny edges (these spreads are 1-2 ticks)
        self._take(prod, od, fair, pos, edge=1.0, orders=orders, max_take=25)
        approx_pos = pos + sum(o.quantity for o in orders)

        self._force_unwind(prod, od, approx_pos, orders, threshold=0.65, target_frac=0.30)
        approx_pos = pos + sum(o.quantity for o in orders)

        # Small touch quotes - might catch occasional fills
        cap_buy = 300 - approx_pos
        cap_sell = 300 + approx_pos
        skew = approx_pos / 300

        bid_qty = int(12 * max(0.1, 1 - skew))
        ask_qty = int(12 * max(0.1, 1 + skew))

        if cap_buy > 0 and skew < 0.7:
            orders.append(Order(prod, bid, min(bid_qty, cap_buy)))
        if cap_sell > 0 and skew > -0.7:
            orders.append(Order(prod, ask, -min(ask_qty, cap_sell)))

        return orders

    # =====================================================================
    # DEEP OTM (6000, 6500): post sells at 1, take any bids ≥ 1
    # =====================================================================
    def _trade_deep_otm(self, prod, state):
        orders = []
        if prod not in state.order_depths:
            return orders
        od = state.order_depths[prod]
        pos = state.position.get(prod, 0)
        cap_sell = 300 + pos
        bid = self._best_bid(od)
        if bid is not None and bid >= 1 and cap_sell > 0:
            vol = min(od.buy_orders[bid], cap_sell, 80)
            orders.append(Order(prod, bid, -vol))
            cap_sell -= vol
        if cap_sell > 0:
            orders.append(Order(prod, 1, -min(cap_sell, 100)))
        return orders

    # =====================================================================
    # MAIN
    # =====================================================================
    def run(self, state: TradingState):
        try:
            sd: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            sd = {}

        all_orders: Dict[str, List[Order]] = {}

        all_orders["HYDROGEL_PACK"] = self._trade_hp(state, sd)
        all_orders["VELVETFRUIT_EXTRACT"] = self._trade_vev_spot(state, sd)

        for prod in ("VEV_5000", "VEV_5100", "VEV_5200"):
            all_orders[prod] = self._trade_wide_option(prod, state, sd)
        for prod in ("VEV_5300", "VEV_5400", "VEV_5500"):
            all_orders[prod] = self._trade_tight_option(prod, state, sd)
        for prod in ("VEV_6000", "VEV_6500"):
            all_orders[prod] = self._trade_deep_otm(prod, state)

        # Skip deep ITM - never trades
        all_orders["VEV_4000"] = []
        all_orders["VEV_4500"] = []

        return all_orders, 0, json.dumps(sd)
