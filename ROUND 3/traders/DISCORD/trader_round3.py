"""
IMC Prosperity Round 3 — "Gloves Off"
=====================================
Strategy:
  - HYDROGEL_PACK:          Mean-reversion market-making around ~9990
  - VELVETFRUIT_EXTRACT:    Mean-reversion market-making around ~5250
  - VEV_5000 … VEV_5500:   Black-Scholes pricing (IV ≈ 0.012/day) + market-making
  - VEV_4000, VEV_4500:    Market-make tightly around intrinsic (S - K)
  - VEV_6000, VEV_6500:    Skip (essentially worthless, no edge)

Manual bids submitted externally:
  - Bid 1: 790  →  buys from 25 counterparties, profit = 25 × (920 - 790) = 3 250
  - Bid 2: 855  →  optimal incremental bid given standard competition
"""

from datamodel import (
    OrderDepth, TradingState, Order,
    ConversionObservation, Observation
)
from typing import Dict, List, Tuple
import math, json

# ─────────────────────────────── helpers ──────────────────────────────────────

def norm_cdf(x: float) -> float:
    """Accurate standard normal CDF (Abramowitz & Stegun 26.2.17)."""
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    poly = t * (0.319381530
                + t * (-0.356563782
                       + t * (1.781477937
                              + t * (-1.821255978
                                     + t * 1.330274429))))
    cdf = 1.0 - (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x * x) * poly
    return cdf if x >= 0 else 1.0 - cdf


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    """Black-Scholes European call price (r=0)."""
    if T <= 1e-9:
        return max(S - K, 0.0)
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return S * norm_cdf(d1) - K * norm_cdf(d2)


def bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    """BS delta of call."""
    if T <= 1e-9:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
    return norm_cdf(d1)


# ─────────────────────────────── constants ────────────────────────────────────

TICKS_PER_DAY   = 1_000_000        # timestamp 0 … 999 900
SIGMA_VEV       = 0.012            # market-implied daily vol (calibrated)
TTE_ROUND_START = 5                # days to expiry at round 3 start

# Strikes we actively trade (deep ITM handled separately; deep OTM skipped)
ACTIVE_VEV_STRIKES  = [5000, 5100, 5200, 5300, 5400, 5500]
ITM_VEV_STRIKES     = [4000, 4500]

POSITION_LIMITS = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    **{f"VEV_{K}": 300 for K in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
}

# Fair-value anchors (updated each tick via EMA)
HP_FAIR_VALUE  = 9990.0
VFE_FAIR_VALUE = 5250.0

EMA_ALPHA = 0.02          # smoothing for fair value EMA

# MM spread half-widths (ticks from fair value at which we quote)
HP_SPREAD   = 4            # HYDROGEL half-spread in XIREC
VFE_SPREAD  = 2            # VELVETFRUIT half-spread
VEV_SPREAD  = 1            # VEV half-spread (added on each side of BS fair)

# Max order size per quote
HP_ORDER_SIZE   = 30
VFE_ORDER_SIZE  = 20
VEV_ORDER_SIZE  = 30       # per VEV strike

# Position soft limit at which we stop adding more
HP_SOFT_LIMIT   = 150
VFE_SOFT_LIMIT  = 150
VEV_SOFT_LIMIT  = 250


# ──────────────────────────────── trader ──────────────────────────────────────

class Trader:

    def __init__(self):
        self.hp_fair  = HP_FAIR_VALUE
        self.vfe_fair = VFE_FAIR_VALUE
        self.prev_timestamp = -1

    # ── utility ──────────────────────────────────────────────────────────────

    def _mid(self, od: OrderDepth) -> float | None:
        """Return best-bid/best-ask midpoint, or None if one side is empty."""
        if od.buy_orders and od.sell_orders:
            bb = max(od.buy_orders)
            ba = min(od.sell_orders)
            return (bb + ba) / 2.0
        return None

    def _best_bid(self, od: OrderDepth) -> int | None:
        return max(od.buy_orders) if od.buy_orders else None

    def _best_ask(self, od: OrderDepth) -> int | None:
        return min(od.sell_orders) if od.sell_orders else None

    def _pos(self, state: TradingState, product: str) -> int:
        return state.position.get(product, 0)

    # ── order helpers ────────────────────────────────────────────────────────

    def _take_orders(
        self,
        product: str,
        od: OrderDepth,
        fair: float,
        pos: int,
        limit: int,
        max_buy_size: int,
        max_sell_size: int,
    ) -> Tuple[List[Order], int]:
        """
        Aggress on mispricings:
          - buy any ask below (fair - edge)
          - sell any bid above (fair + edge)
        edge is intentionally zero here so we take any mispriced order.
        """
        orders: List[Order] = []
        remaining_pos = pos

        # Buy underpriced asks
        for ask_price in sorted(od.sell_orders):
            if ask_price >= fair:
                break
            vol = -od.sell_orders[ask_price]   # positive
            can_buy = min(vol, limit - remaining_pos, max_buy_size)
            if can_buy <= 0:
                break
            orders.append(Order(product, ask_price, can_buy))
            remaining_pos += can_buy

        # Sell overpriced bids
        for bid_price in sorted(od.buy_orders, reverse=True):
            if bid_price <= fair:
                break
            vol = od.buy_orders[bid_price]      # positive
            can_sell = min(vol, remaining_pos + limit, max_sell_size)
            if can_sell <= 0:
                break
            orders.append(Order(product, bid_price, -can_sell))
            remaining_pos -= can_sell

        return orders, remaining_pos

    def _quote_orders(
        self,
        product: str,
        od: OrderDepth,
        fair: float,
        pos: int,
        limit: int,
        half_spread: int,
        order_size: int,
        soft_limit: int,
    ) -> List[Order]:
        """
        Passive market-making: post bid at (fair - half_spread),
        ask at (fair + half_spread), skewed by position.
        """
        orders: List[Order] = []

        # Skew quotes toward inventory reduction
        skew = int(pos / limit * half_spread)

        bid_px = round(fair - half_spread - skew)
        ask_px = round(fair + half_spread - skew)

        # Buy side — only if room to add longs
        buy_capacity = limit - pos
        if buy_capacity > 0:
            size = min(order_size, buy_capacity, soft_limit + limit)
            # Don't cross existing best ask
            ba = self._best_ask(od)
            if ba is not None:
                bid_px = min(bid_px, ba - 1)
            if bid_px > 0 and size > 0:
                orders.append(Order(product, bid_px, size))

        # Sell side — only if room to add shorts
        sell_capacity = limit + pos   # pos is negative when short
        if sell_capacity > 0:
            size = min(order_size, sell_capacity, soft_limit + limit)
            bb = self._best_bid(od)
            if bb is not None:
                ask_px = max(ask_px, bb + 1)
            if size > 0:
                orders.append(Order(product, ask_px, -size))

        return orders

    # ── product-specific strategies ──────────────────────────────────────────

    def _trade_hydrogel(self, state: TradingState) -> List[Order]:
        product = "HYDROGEL_PACK"
        od = state.order_depths.get(product)
        if od is None:
            return []

        pos   = self._pos(state, product)
        limit = POSITION_LIMITS[product]

        # Update EMA fair value
        mid = self._mid(od)
        if mid is not None:
            self.hp_fair = (1 - EMA_ALPHA) * self.hp_fair + EMA_ALPHA * mid

        fair = self.hp_fair

        # 1. Aggress on clear mispricings (anything below/above fair)
        take, new_pos = self._take_orders(
            product, od, fair, pos, limit,
            max_buy_size=HP_ORDER_SIZE,
            max_sell_size=HP_ORDER_SIZE,
        )

        # 2. Passive quotes around fair
        quote = self._quote_orders(
            product, od, fair, new_pos, limit,
            half_spread=HP_SPREAD,
            order_size=HP_ORDER_SIZE,
            soft_limit=HP_SOFT_LIMIT,
        )

        return take + quote

    def _trade_velvetfruit(self, state: TradingState) -> List[Order]:
        product = "VELVETFRUIT_EXTRACT"
        od = state.order_depths.get(product)
        if od is None:
            return []

        pos   = self._pos(state, product)
        limit = POSITION_LIMITS[product]

        mid = self._mid(od)
        if mid is not None:
            self.vfe_fair = (1 - EMA_ALPHA) * self.vfe_fair + EMA_ALPHA * mid

        fair = self.vfe_fair

        take, new_pos = self._take_orders(
            product, od, fair, pos, limit,
            max_buy_size=VFE_ORDER_SIZE,
            max_sell_size=VFE_ORDER_SIZE,
        )
        quote = self._quote_orders(
            product, od, fair, new_pos, limit,
            half_spread=VFE_SPREAD,
            order_size=VFE_ORDER_SIZE,
            soft_limit=VFE_SOFT_LIMIT,
        )

        return take + quote

    def _trade_vev(self, state: TradingState, K: int, S: float) -> List[Order]:
        """
        Market-make a single VEV using BS fair value.
        S is the current VELVETFRUIT spot price.
        """
        product = f"VEV_{K}"
        od = state.order_depths.get(product)
        if od is None:
            return []

        pos   = self._pos(state, product)
        limit = POSITION_LIMITS[product]

        # Time to expiry: TTE_ROUND_START at timestamp 0, decreasing through the round
        timestamp = state.timestamp
        tte = TTE_ROUND_START - timestamp / TICKS_PER_DAY   # in days (5 → ~4)
        tte = max(tte, 1e-3)

        if K in ITM_VEV_STRIKES:
            # Deep ITM: price ≈ S - K (intrinsic), minimal vol premium
            fair = max(S - K, 0.0)
            spread_to_use = 3
            size = 15   # smaller size, wider spread
        else:
            fair = bs_call(S, K, tte, SIGMA_VEV)
            spread_to_use = VEV_SPREAD
            size = VEV_ORDER_SIZE

        # For very OTM (6000, 6500) do nothing — already filtered upstream

        take, new_pos = self._take_orders(
            product, od, fair, pos, limit,
            max_buy_size=size,
            max_sell_size=size,
        )
        quote = self._quote_orders(
            product, od, fair, new_pos, limit,
            half_spread=spread_to_use,
            order_size=size,
            soft_limit=VEV_SOFT_LIMIT,
        )

        return take + quote

    # ── main entry point ─────────────────────────────────────────────────────

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result: Dict[str, List[Order]] = {}
        conversions = 0

        # Get current VFE spot for VEV pricing
        vfe_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        vfe_spot = self.vfe_fair   # fallback
        if vfe_od:
            mid = self._mid(vfe_od)
            if mid is not None:
                vfe_spot = mid

        # 1. HYDROGEL_PACK
        orders = self._trade_hydrogel(state)
        if orders:
            result["HYDROGEL_PACK"] = orders

        # 2. VELVETFRUIT_EXTRACT
        orders = self._trade_velvetfruit(state)
        if orders:
            result["VELVETFRUIT_EXTRACT"] = orders

        # 3. VEVs — active strikes only
        for K in ACTIVE_VEV_STRIKES:
            orders = self._trade_vev(state, K, vfe_spot)
            if orders:
                result[f"VEV_{K}"] = orders

        # 4. Deep ITM VEVs
        for K in ITM_VEV_STRIKES:
            orders = self._trade_vev(state, K, vfe_spot)
            if orders:
                result[f"VEV_{K}"] = orders

        # Persist state via trader_data (EMA values)
        trader_data = json.dumps({
            "hp_fair":  round(self.hp_fair, 4),
            "vfe_fair": round(self.vfe_fair, 4),
        })

        return result, conversions, trader_data

    def __init_from_state(self, trader_data: str):
        if trader_data:
            try:
                d = json.loads(trader_data)
                self.hp_fair  = d.get("hp_fair",  HP_FAIR_VALUE)
                self.vfe_fair = d.get("vfe_fair", VFE_FAIR_VALUE)
            except Exception:
                pass
