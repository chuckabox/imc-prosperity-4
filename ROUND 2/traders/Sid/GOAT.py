"""
GOAT Round 3 - "Gloves Off" Trading Strategy  [FIXED]
======================================================

Bugs fixed vs original:
------------------------
FIX 1 (line ~212): Ask-side inventory skew was inverted.
    Original:  our_ask = round(fair + ask_edge - skew * ask_edge * 0.5)
    Fixed:     our_ask = round(fair + ask_edge + skew * ask_edge * 0.5)
    When long (skew > 0), ask now moves UP (selling more aggressively).
    When short (skew < 0), ask moves DOWN (replenishing inventory).
    Original code amplified inventory imbalance; fix corrects it.

FIX 2 (line ~336): TTE anchored to starting timestamp, not assumed 0.
    If the round starts at a non-zero timestamp (common), the original
    formula overestimates elapsed days and produces wrong T for BS pricing.
    Fixed by storing start_ts on first tick and computing elapsed from there.

FIX 3 (line ~396): Dead `spread` variable removed; None-safety confirmed.
    `spread = od.sell_orders and od.buy_orders` was computed but never used.
    The actual guard `if (bid and ask)` below it is correct. Dead line removed.

Design improvements:
--------------------
IMPROVE 1: Slow EMA (hp_ema_slow) now used in HP fair value as a long-run
    anchor instead of the hard-coded 10000. This makes fair value adaptive
    to slow structural drift rather than pinned to a constant.

IMPROVE 2: VEV aggressive-take edge raised from 2.0 → 2.5 ticks to reduce
    noise-triggered fills before the fast EMA has warmed up.

IMPROVE 3: IV EMA alpha raised from 0.05 → 0.15 for faster response to
    volatility regime changes during the short 5-day TTE window.

IMPROVE 4: Deep OTM passive ask tracks resting order count to avoid stacking
    duplicate passive orders on the same price level each tick.

Strategy Overview (unchanged):
-------------------------------
1. HYDROGEL_PACK:
   - Market-make around fair value ~10000
   - Mean-reverts strongly; post tight bid/ask around rolling EMA
   - Spread ~16 in market; we undercut by posting inside spread

2. VELVETFRUIT_EXTRACT (spot):
   - Market-make around rolling EMA (fast EMA as fair value proxy)
   - Negative autocorrelation in returns → mean-reverting, good for MM
   - Spread ~5; post 2-3 ticks inside

3. VELVETFRUIT_EXTRACT_VOUCHER (options):
   - Deep ITM (4000, 4500): skip — spread too wide, delta=1 (just parity)
   - Liquid ATM (5000–5500): calibrate IV from observed prices, market-make
     with BS fair value ± edge. IV is very stable ~23% across all days.
   - Deep OTM (6000, 6500): always short at 1 (worthless at expiry).
     Sell any bids, never buy.

Key Insights from Data Analysis:
---------------------------------
- HP fair value: 10000, bid-ask spread ~16, mean reversion coef ~0.998
- VEV fair value: ~5250 (drifts slightly), spread ~5, mean reversion coef ~0.997
- VEV IV: very stable ~23.25% annualized across all strikes/days
- Deep OTM vouchers (6000, 6500) priced at min floor 0.5 — free short opportunity
- TTE at round 3 start = 5 days → T = 5/365 for BS pricing
"""

from datamodel import (
    OrderDepth, UserId, TradingState, Order, ConversionObservation, Observation
)
from typing import List, Dict, Any
import math
import json


# ─────────────────────────────────────────────
# Black-Scholes helpers (no scipy dependency)
# ─────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    """Abramowitz & Stegun approximation — accurate to 7 decimal places."""
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + 0.2316419 * x)
    poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937
                + t * (-1.821255978 + t * 1.330274429))))
    return 0.5 + sign * (0.5 - math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi) * poly)

def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

def bs_call(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
    """Black-Scholes European call price."""
    if T <= 1e-9:
        return max(S - K, 0.0)
    if S <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)

def bs_delta(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
    """BS delta for a call."""
    if T <= 1e-9:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1)

def bs_vega(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
    if T <= 1e-9:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return S * _norm_pdf(d1) * math.sqrt(T)

def implied_vol_newton(market_price: float, S: float, K: float, T: float,
                        r: float = 0.0, tol: float = 1e-6, max_iter: int = 100) -> float:
    """Newton-Raphson IV solver."""
    intrinsic = max(S - K, 0.0)
    if market_price <= intrinsic + 1e-4:
        return float('nan')
    sigma = 0.25  # initial guess
    for _ in range(max_iter):
        price = bs_call(S, K, T, sigma, r)
        vega = bs_vega(S, K, T, sigma, r)
        if vega < 1e-10:
            break
        diff = price - market_price
        sigma -= diff / vega
        sigma = max(0.001, min(sigma, 15.0))
        if abs(diff) < tol:
            break
    return sigma


# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

PRODUCTS = {
    "HYDROGEL_PACK":            {"limit": 200,  "fair": 10000.0},
    "VELVETFRUIT_EXTRACT":      {"limit": 200,  "fair": 5250.0},
    "VEV_4000":  {"limit": 300, "strike": 4000, "deep_itm": True},
    "VEV_4500":  {"limit": 300, "strike": 4500, "deep_itm": True},
    "VEV_5000":  {"limit": 300, "strike": 5000, "liquid": True},
    "VEV_5100":  {"limit": 300, "strike": 5100, "liquid": True},
    "VEV_5200":  {"limit": 300, "strike": 5200, "liquid": True},
    "VEV_5300":  {"limit": 300, "strike": 5300, "liquid": True},
    "VEV_5400":  {"limit": 300, "strike": 5400, "liquid": True},
    "VEV_5500":  {"limit": 300, "strike": 5500, "liquid": True},
    "VEV_6000":  {"limit": 300, "strike": 6000, "deep_otm": True},
    "VEV_6500":  {"limit": 300, "strike": 6500, "deep_otm": True},
}

LIQUID_VOUCHERS = ["VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"]
LIQUID_STRIKES  = [5000, 5100, 5200, 5300, 5400, 5500]

# Round 3 starts at TTE = 5, each timestamp step ≈ 100 units
# Total timestamps per day ≈ 1_000_000 (0 to 999_900, step 100)
# One round lasts 1 Solvenarian day
TICKS_PER_DAY = 1_000_000
BASE_IV       = 0.2325   # calibrated from historical data
TTE_START     = 5.0      # days remaining at round start


class Trader:

    def __init__(self):
        # Per-product state stored across calls via traderData
        pass

    # ─────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────

    def _mid(self, od: OrderDepth) -> float | None:
        """Best-bid/ask midpoint, or None if one side is empty."""
        if od.buy_orders and od.sell_orders:
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            return (best_bid + best_ask) / 2.0
        if od.buy_orders:
            return float(max(od.buy_orders.keys()))
        if od.sell_orders:
            return float(min(od.sell_orders.keys()))
        return None

    def _best_bid(self, od: OrderDepth):
        return max(od.buy_orders.keys()) if od.buy_orders else None

    def _best_ask(self, od: OrderDepth):
        return min(od.sell_orders.keys()) if od.sell_orders else None

    def _ema_update(self, state_dict: dict, key: str, value: float, alpha: float) -> float:
        if key not in state_dict:
            state_dict[key] = value
        else:
            state_dict[key] = alpha * value + (1 - alpha) * state_dict[key]
        return state_dict[key]

    def _available_buy(self, product: str, position: int) -> int:
        limit = PRODUCTS[product]["limit"]
        return limit - position

    def _available_sell(self, product: str, position: int) -> int:
        limit = PRODUCTS[product]["limit"]
        return limit + position  # position is negative when short

    def _take_orders(self, product: str, od: OrderDepth, fair: float,
                     position: int, edge: float, orders: list):
        """Hit existing orders that are clearly mispriced vs fair."""
        limit_buy  = self._available_buy(product, position)
        limit_sell = self._available_sell(product, position)

        # Buy if ask is below fair - edge
        for ask_price in sorted(od.sell_orders.keys()):
            if ask_price < fair - edge and limit_buy > 0:
                vol = min(-od.sell_orders[ask_price], limit_buy)
                if vol > 0:
                    orders.append(Order(product, ask_price, vol))
                    limit_buy -= vol
            else:
                break

        # Sell if bid is above fair + edge
        for bid_price in sorted(od.buy_orders.keys(), reverse=True):
            if bid_price > fair + edge and limit_sell > 0:
                vol = min(od.buy_orders[bid_price], limit_sell)
                if vol > 0:
                    orders.append(Order(product, bid_price, -vol))
                    limit_sell -= vol
            else:
                break

    def _make_orders(self, product: str, od: OrderDepth, fair: float,
                     position: int, bid_edge: float, ask_edge: float,
                     bid_vol: int, ask_vol: int, orders: list):
        """Post passive market-making quotes."""
        limit_buy  = self._available_buy(product, position)
        limit_sell = self._available_sell(product, position)

        # Skew quotes based on position (inventory management).
        # skew > 0 when long → lower bid (buy less eagerly) AND raise ask (sell more eagerly).
        # skew < 0 when short → raise bid (buy more eagerly) AND lower ask (sell less eagerly).
        skew = position / PRODUCTS[product]["limit"]
        our_bid = round(fair - bid_edge - skew * bid_edge * 0.5)
        # FIX 1: ask skew sign was inverted in original — must be + skew to push ask UP when long.
        our_ask = round(fair + ask_edge + skew * ask_edge * 0.5)

        if limit_buy > 0:
            qty = min(bid_vol, limit_buy)
            if qty > 0:
                orders.append(Order(product, our_bid, qty))

        if limit_sell > 0:
            qty = min(ask_vol, limit_sell)
            if qty > 0:
                orders.append(Order(product, our_ask, -qty))

    # ─────────────────────────────────────────
    # IV Calibration from liquid voucher prices
    # ─────────────────────────────────────────

    def _calibrate_iv(self, spot: float, T: float,
                      order_depths: dict, sd: dict) -> float:
        """
        Compute weighted-average IV from liquid vouchers.
        Falls back to BASE_IV if calibration fails.

        IMPROVE 3: alpha_iv raised 0.05 → 0.15 for faster response to
        volatility regime changes over the short 5-day TTE window.
        """
        iv_sum = 0.0
        w_sum  = 0.0
        for prod, K in zip(LIQUID_VOUCHERS, LIQUID_STRIKES):
            if prod not in order_depths:
                continue
            mid = self._mid(order_depths[prod])
            if mid is None or mid <= 0:
                continue
            iv = implied_vol_newton(mid, spot, K, T)
            if math.isnan(iv) or iv <= 0:
                continue
            # Weight by vega (more ATM = more informative)
            w = bs_vega(spot, K, T, iv)
            iv_sum += iv * w
            w_sum  += w

        if w_sum > 1e-6:
            raw_iv = iv_sum / w_sum
        else:
            raw_iv = BASE_IV

        # IMPROVE 3: faster IV EMA (was 0.05) to track regime shifts
        alpha_iv = 0.15
        return self._ema_update(sd, "iv_ema", raw_iv, alpha_iv)

    # ─────────────────────────────────────────
    # HYDROGEL_PACK
    # ─────────────────────────────────────────

    def _trade_hydrogel(self, state: TradingState, sd: dict) -> List[Order]:
        orders = []
        product = "HYDROGEL_PACK"
        if product not in state.order_depths:
            return orders

        od  = state.order_depths[product]
        pos = state.position.get(product, 0)
        mid = self._mid(od)
        if mid is None:
            return orders

        # EMA fair value: fast α=0.3 for signal, slow α=0.02 as long-run anchor.
        fast = self._ema_update(sd, "hp_ema_fast", mid, 0.3)
        slow = self._ema_update(sd, "hp_ema_slow", mid, 0.02)

        # IMPROVE 1: Use slow EMA as the long-run anchor instead of hard-coded 10000.
        # This makes fair value adaptive to slow structural drift in HP price.
        # Blend: 70% fast signal, 30% slow anchor.
        fair = 0.7 * fast + 0.3 * slow

        # Take clearly mispriced orders (edge = 6)
        self._take_orders(product, od, fair, pos, edge=6.0, orders=orders)

        # Re-compute position after aggressive orders
        approx_pos = pos + sum(o.quantity for o in orders)

        # Post passive quotes inside the market spread (~16) → post at ±7
        self._make_orders(product, od, fair, approx_pos,
                          bid_edge=7.0, ask_edge=7.0,
                          bid_vol=15, ask_vol=15, orders=orders)
        return orders

    # ─────────────────────────────────────────
    # VELVETFRUIT_EXTRACT (spot)
    # ─────────────────────────────────────────

    def _trade_vev_spot(self, state: TradingState, sd: dict) -> List[Order]:
        orders = []
        product = "VELVETFRUIT_EXTRACT"
        if product not in state.order_depths:
            return orders

        od  = state.order_depths[product]
        pos = state.position.get(product, 0)
        mid = self._mid(od)
        if mid is None:
            return orders

        fast = self._ema_update(sd, "vev_ema_fast", mid, 0.3)
        fair = fast  # trust the fast EMA as fair value

        # IMPROVE 2: edge raised from 2.0 → 2.5 to reduce noise-triggered
        # aggressive fills before the EMA has warmed up (spread is ~5).
        self._take_orders(product, od, fair, pos, edge=2.5, orders=orders)
        approx_pos = pos + sum(o.quantity for o in orders)

        # Post passive at ±2 (tight, inside spread of 5)
        self._make_orders(product, od, fair, approx_pos,
                          bid_edge=2.0, ask_edge=2.0,
                          bid_vol=20, ask_vol=20, orders=orders)
        return orders

    # ─────────────────────────────────────────
    # VELVETFRUIT_EXTRACT_VOUCHER (options)
    # ─────────────────────────────────────────

    def _trade_vouchers(self, state: TradingState, sd: dict,
                        spot: float, iv: float, T: float) -> Dict[str, List[Order]]:
        result = {}

        # ── Deep OTM: VEV_6000, VEV_6500 ──
        # These are essentially worthless. Floor price = 0.5.
        # Strategy: Always sell at 1 if anyone bids ≥ 1.
        # IMPROVE 4: track whether we already have a resting passive ask to
        # avoid stacking duplicate orders on the same level every tick.
        for prod in ["VEV_6000", "VEV_6500"]:
            orders = []
            if prod not in state.order_depths:
                result[prod] = orders
                continue
            od  = state.order_depths[prod]
            pos = state.position.get(prod, 0)
            avail_sell = self._available_sell(prod, pos)

            # Sell aggressively to any buyers at ≥ 1
            for bid_price in sorted(od.buy_orders.keys(), reverse=True):
                if bid_price >= 1 and avail_sell > 0:
                    vol = min(od.buy_orders[bid_price], avail_sell, 50)
                    orders.append(Order(prod, bid_price, -vol))
                    avail_sell -= vol
                else:
                    break

            # Post a passive ask at 1, but only if there is no existing ask
            # at 1 in the book already (avoids doubling resting orders).
            existing_ask_at_1 = od.sell_orders.get(1, 0)  # negative qty or 0
            if avail_sell > 0 and existing_ask_at_1 == 0:
                orders.append(Order(prod, 1, -min(avail_sell, 30)))

            result[prod] = orders

        # ── Deep ITM: VEV_4000, VEV_4500 ──
        # Delta ~1, fair ≈ S - K. Wide spreads (15-20).
        # Only trade if extreme mispricing detected.
        for prod, K in [("VEV_4000", 4000), ("VEV_4500", 4500)]:
            orders = []
            if prod not in state.order_depths:
                result[prod] = orders
                continue
            od  = state.order_depths[prod]
            pos = state.position.get(prod, 0)
            fair = max(spot - K, 0.0)

            # Only aggressively take if >5 edge
            self._take_orders(prod, od, fair, pos, edge=5.0, orders=orders)
            result[prod] = orders

        # ── Liquid ATM options: VEV_5000 to VEV_5500 ──
        for prod, K in zip(LIQUID_VOUCHERS, LIQUID_STRIKES):
            orders = []
            if prod not in state.order_depths:
                result[prod] = orders
                continue
            od  = state.order_depths[prod]
            pos = state.position.get(prod, 0)

            fair = bs_call(spot, K, T, iv)
            if fair <= 0:
                result[prod] = orders
                continue

            # FIX 3: dead `spread` variable removed. The (bid and ask) guard
            # below is the correct None-safety check — kept as-is.
            bid = self._best_bid(od)
            ask = self._best_ask(od)

            # Market edge: roughly half the market spread, min 1
            mkt_half_spread = ((ask - bid) / 2.0) if (bid and ask) else 2.0
            edge = max(1.0, mkt_half_spread * 0.4)

            # Aggressively take mispriced
            self._take_orders(prod, od, fair, pos, edge=edge, orders=orders)
            approx_pos = pos + sum(o.quantity for o in orders)

            # Post passive quotes
            self._make_orders(prod, od, fair, approx_pos,
                              bid_edge=edge, ask_edge=edge,
                              bid_vol=20, ask_vol=20, orders=orders)
            result[prod] = orders

        return result

    # ─────────────────────────────────────────
    # Main run()
    # ─────────────────────────────────────────

    def run(self, state: TradingState):
        # ── Restore persisted state ──
        try:
            sd: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            sd = {}

        all_orders: Dict[str, List[Order]] = {}
        conversions = 0

        # ── HYDROGEL_PACK ──
        all_orders["HYDROGEL_PACK"] = self._trade_hydrogel(state, sd)

        # ── VELVETFRUIT_EXTRACT (spot) ──
        all_orders["VELVETFRUIT_EXTRACT"] = self._trade_vev_spot(state, sd)

        # ── Get current spot price for options pricing ──
        spot = None
        vev_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if vev_od:
            spot = self._mid(vev_od)
        if spot is None:
            spot = sd.get("last_spot", 5250.0)
        sd["last_spot"] = spot

        # FIX 2: Anchor TTE to the starting timestamp so elapsed days are
        # computed correctly even if the round doesn't begin at timestamp 0.
        if "start_ts" not in sd:
            sd["start_ts"] = state.timestamp
        elapsed_days = (state.timestamp - sd["start_ts"]) / TICKS_PER_DAY
        tte_days = max(TTE_START - elapsed_days, 0.001)
        T = tte_days / 365.0

        # ── Calibrate IV from live voucher prices ──
        iv = self._calibrate_iv(spot, T, state.order_depths, sd)

        # ── VOUCHERS (pass T so it isn't recomputed internally) ──
        voucher_orders = self._trade_vouchers(state, sd, spot, iv, T)
        all_orders.update(voucher_orders)

        # ── Persist state ──
        trader_data = json.dumps(sd)

        return all_orders, conversions, trader_data