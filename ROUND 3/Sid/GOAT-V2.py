"""
GOAT Round 3 - "Gloves Off"  [v2]

Major changes vs v1:
  - Liquid vouchers: fair value = market mid (no single-IV BS fit). The real
    market has a volatility smile that the previous vega-weighted IV ignored,
    which caused 5300 to be shorted to the cap and 5400 to be bought to the
    cap simultaneously. Trusting mid eliminates that bias and reduces us to
    pure spread-capture market-making.
  - Deep OTM (6000, 6500): always post a passive ask at 1, regardless of
    existing book volume at that level. The previous "skip if existing ask"
    guard meant we never posted, since the market always has resting asks at 1.
  - HP / VEV spot: per-side skew strengthened, with a forced-unwind regime
    when |position| > 80% of limit so we cross the spread to flatten rather
    than parking outside the market.
  - TTE handling: traderData persists `tte_anchor_days` so users can override
    if running on historical days; defaults to 5 (round 3 start).
  - BS pricing kept only as a sanity rail (deep-ITM parity, bound checks).
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import math
import json


def _norm_cdf(x: float) -> float:
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + 0.2316419 * x)
    poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937
                + t * (-1.821255978 + t * 1.330274429))))
    return 0.5 + sign * (0.5 - math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi) * poly)


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-9 or S <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


PRODUCTS = {
    "HYDROGEL_PACK":       {"limit": 200},
    "VELVETFRUIT_EXTRACT": {"limit": 200},
    "VEV_4000": {"limit": 300, "strike": 4000, "deep_itm": True},
    "VEV_4500": {"limit": 300, "strike": 4500, "deep_itm": True},
    "VEV_5000": {"limit": 300, "strike": 5000, "liquid": True},
    "VEV_5100": {"limit": 300, "strike": 5100, "liquid": True},
    "VEV_5200": {"limit": 300, "strike": 5200, "liquid": True},
    "VEV_5300": {"limit": 300, "strike": 5300, "liquid": True},
    "VEV_5400": {"limit": 300, "strike": 5400, "liquid": True},
    "VEV_5500": {"limit": 300, "strike": 5500, "liquid": True},
    "VEV_6000": {"limit": 300, "strike": 6000, "deep_otm": True},
    "VEV_6500": {"limit": 300, "strike": 6500, "deep_otm": True},
}

LIQUID_VOUCHERS = ["VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"]

TICKS_PER_DAY = 1_000_000
TTE_START_DAYS = 5.0
BASE_IV = 0.245


class Trader:

    def _best_bid(self, od: OrderDepth):
        return max(od.buy_orders.keys()) if od.buy_orders else None

    def _best_ask(self, od: OrderDepth):
        return min(od.sell_orders.keys()) if od.sell_orders else None

    def _mid(self, od: OrderDepth):
        b, a = self._best_bid(od), self._best_ask(od)
        if b is not None and a is not None:
            return (b + a) / 2.0
        return None

    def _microprice(self, od: OrderDepth):
        b, a = self._best_bid(od), self._best_ask(od)
        if b is None or a is None:
            return self._mid(od)
        bv = od.buy_orders[b]
        av = -od.sell_orders[a]
        denom = bv + av
        if denom <= 0:
            return (b + a) / 2.0
        return (b * av + a * bv) / denom

    def _ema(self, sd: dict, key: str, value: float, alpha: float):
        sd[key] = value if key not in sd else alpha * value + (1 - alpha) * sd[key]
        return sd[key]

    def _take(self, product: str, od: OrderDepth, fair: float, position: int,
              edge: float, orders: list, max_take: int = 999):
        limit = PRODUCTS[product]["limit"]
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

    def _make(self, product: str, od: OrderDepth, fair: float, position: int,
              edge: float, qty: int, orders: list, skew_factor: float = 1.0):
        limit = PRODUCTS[product]["limit"]
        cap_buy = limit - position
        cap_sell = limit + position
        skew = position / limit
        bid_px = round(fair - edge - skew * edge * skew_factor)
        ask_px = round(fair + edge - skew * edge * skew_factor)
        if ask_px <= bid_px:
            ask_px = bid_px + 1
        best_bid = self._best_bid(od)
        best_ask = self._best_ask(od)
        if best_bid is not None:
            bid_px = min(bid_px, best_ask - 1) if best_ask is not None else bid_px
            bid_px = max(bid_px, best_bid)
        if best_ask is not None:
            ask_px = max(ask_px, best_bid + 1) if best_bid is not None else ask_px
            ask_px = min(ask_px, best_ask)
        if cap_buy > 0:
            orders.append(Order(product, int(bid_px), min(qty, cap_buy)))
        if cap_sell > 0:
            orders.append(Order(product, int(ask_px), -min(qty, cap_sell)))

    def _force_unwind(self, product: str, od: OrderDepth, position: int, orders: list):
        limit = PRODUCTS[product]["limit"]
        if abs(position) < int(0.8 * limit):
            return
        if position > 0:
            for bid in sorted(od.buy_orders.keys(), reverse=True):
                vol = min(od.buy_orders[bid], position)
                if vol > 0:
                    orders.append(Order(product, bid, -vol))
                    position -= vol
                if position <= int(0.5 * limit):
                    break
        elif position < 0:
            for ask in sorted(od.sell_orders.keys()):
                vol = min(-od.sell_orders[ask], -position)
                if vol > 0:
                    orders.append(Order(product, ask, vol))
                    position += vol
                if position >= -int(0.5 * limit):
                    break

    def _trade_hydrogel(self, state: TradingState, sd: dict) -> List[Order]:
        product = "HYDROGEL_PACK"
        orders: List[Order] = []
        if product not in state.order_depths:
            return orders
        od = state.order_depths[product]
        pos = state.position.get(product, 0)
        mid = self._microprice(od)
        if mid is None:
            return orders
        fast = self._ema(sd, "hp_fast", mid, 0.3)
        slow = self._ema(sd, "hp_slow", mid, 0.02)
        fair = 0.7 * fast + 0.3 * slow
        self._take(product, od, fair, pos, edge=4.0, orders=orders)
        approx_pos = pos + sum(o.quantity for o in orders)
        self._force_unwind(product, od, approx_pos, orders)
        approx_pos = pos + sum(o.quantity for o in orders)
        self._make(product, od, fair, approx_pos,
                   edge=5.0, qty=20, orders=orders, skew_factor=1.5)
        return orders

    def _trade_vev_spot(self, state: TradingState, sd: dict) -> List[Order]:
        product = "VELVETFRUIT_EXTRACT"
        orders: List[Order] = []
        if product not in state.order_depths:
            return orders
        od = state.order_depths[product]
        pos = state.position.get(product, 0)
        mid = self._microprice(od)
        if mid is None:
            return orders
        fast = self._ema(sd, "vev_fast", mid, 0.35)
        fair = fast
        self._take(product, od, fair, pos, edge=2.0, orders=orders)
        approx_pos = pos + sum(o.quantity for o in orders)
        self._force_unwind(product, od, approx_pos, orders)
        approx_pos = pos + sum(o.quantity for o in orders)
        self._make(product, od, fair, approx_pos,
                   edge=2.0, qty=25, orders=orders, skew_factor=1.5)
        return orders

    def _trade_deep_otm(self, prod: str, state: TradingState) -> List[Order]:
        orders: List[Order] = []
        if prod not in state.order_depths:
            return orders
        od = state.order_depths[prod]
        pos = state.position.get(prod, 0)
        cap_sell = PRODUCTS[prod]["limit"] + pos
        for bid in sorted(od.buy_orders.keys(), reverse=True):
            if bid >= 1 and cap_sell > 0:
                vol = min(od.buy_orders[bid], cap_sell, 50)
                orders.append(Order(prod, bid, -vol))
                cap_sell -= vol
            else:
                break
        if cap_sell > 0:
            orders.append(Order(prod, 1, -min(cap_sell, 50)))
        return orders

    def _trade_deep_itm(self, prod: str, K: int, spot: float,
                        state: TradingState) -> List[Order]:
        orders: List[Order] = []
        if prod not in state.order_depths:
            return orders
        od = state.order_depths[prod]
        pos = state.position.get(prod, 0)
        fair = max(spot - K, 0.0)
        self._take(prod, od, fair, pos, edge=8.0, orders=orders, max_take=10)
        return orders

    def _trade_liquid_voucher(self, prod: str, state: TradingState,
                              spot: float, T: float) -> List[Order]:
        orders: List[Order] = []
        if prod not in state.order_depths:
            return orders
        od = state.order_depths[prod]
        pos = state.position.get(prod, 0)
        K = PRODUCTS[prod]["strike"]
        mid = self._microprice(od)
        if mid is None:
            return orders

        bid = self._best_bid(od)
        ask = self._best_ask(od)
        spread = (ask - bid) if (bid is not None and ask is not None) else 4

        intrinsic = max(spot - K, 0.0)
        bs_max = bs_call(spot, K, T, BASE_IV * 2.5)
        if mid < intrinsic - 1 or mid > bs_max + 1:
            fair = bs_call(spot, K, T, BASE_IV)
        else:
            fair = mid

        if spread <= 1:
            self._force_unwind(prod, od, pos, orders)
            approx_pos = pos + sum(o.quantity for o in orders)
            cap_buy = PRODUCTS[prod]["limit"] - approx_pos
            cap_sell = PRODUCTS[prod]["limit"] + approx_pos
            if bid is not None and cap_buy > 0 and approx_pos < int(0.5 * PRODUCTS[prod]["limit"]):
                orders.append(Order(prod, bid, min(15, cap_buy)))
            if ask is not None and cap_sell > 0 and approx_pos > -int(0.5 * PRODUCTS[prod]["limit"]):
                orders.append(Order(prod, ask, -min(15, cap_sell)))
            return orders

        take_edge = max(2.0, spread * 0.6)
        make_edge = max(1.0, spread * 0.4)
        self._take(prod, od, fair, pos, edge=take_edge, orders=orders, max_take=40)
        approx_pos = pos + sum(o.quantity for o in orders)
        self._force_unwind(prod, od, approx_pos, orders)
        approx_pos = pos + sum(o.quantity for o in orders)
        self._make(prod, od, fair, approx_pos,
                   edge=make_edge, qty=20, orders=orders, skew_factor=1.5)
        return orders

    def run(self, state: TradingState):
        try:
            sd: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            sd = {}

        all_orders: Dict[str, List[Order]] = {}
        conversions = 0

        all_orders["HYDROGEL_PACK"] = self._trade_hydrogel(state, sd)
        all_orders["VELVETFRUIT_EXTRACT"] = self._trade_vev_spot(state, sd)

        spot = None
        vev_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if vev_od:
            spot = self._microprice(vev_od)
        if spot is None:
            spot = sd.get("last_spot", 5250.0)
        sd["last_spot"] = spot

        if "start_ts" not in sd:
            sd["start_ts"] = state.timestamp
        anchor_days = sd.get("tte_anchor_days", TTE_START_DAYS)
        elapsed = (state.timestamp - sd["start_ts"]) / TICKS_PER_DAY
        tte_days = max(anchor_days - elapsed, 0.001)
        T = tte_days / 365.0

        for prod in ("VEV_6000", "VEV_6500"):
            all_orders[prod] = self._trade_deep_otm(prod, state)

        for prod, K in (("VEV_4000", 4000), ("VEV_4500", 4500)):
            all_orders[prod] = self._trade_deep_itm(prod, K, spot, state)

        for prod in LIQUID_VOUCHERS:
            all_orders[prod] = self._trade_liquid_voucher(prod, state, spot, T)

        return all_orders, conversions, json.dumps(sd)
