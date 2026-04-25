"""trader50.py - Aggressive High-PnL Trader.
Baseline: DISCORD trader_round3.py.
Optimized for 98k+ on HYDROGEL_PACK.

Alpha:
1. Lead-Lag Correlation: HP price is biased by VFE price action (VFE leads HP).
2. Fast Mean Reversion: High EMA alpha (0.25) to catch quick reversions.
3. Pennying MM: Aggressively quoting at best-bid + 1 and best-ask - 1.
4. Deep Take: Aggressing on all liquidity better than fair, not just top-of-book.
5. Adaptive Skew: Nonlinear skew to flatten inventory faster near limits.
"""

from datamodel import (
    OrderDepth, TradingState, Order,
    ConversionObservation, Observation
)
from typing import Dict, List, Tuple
import math, json

# ─────────────────────────────── Constants ────────────────────────────────────

TICKS_PER_DAY   = 1_000_000
SIGMA_VEV       = 0.0126           # Calibrated from scan results
TTE_ROUND_START = 8                # Adjusted from scratch/vev_iv_scan.py

ACTIVE_VEV_STRIKES  = [5000, 5100, 5200, 5300, 5400, 5500]
ITM_VEV_STRIKES     = [4000, 4500]

POSITION_LIMITS = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    **{f"VEV_{K}": 60 for K in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
}

# Initial fair-value anchors
HP_FAIR_ANCHOR  = 9991.0
VFE_FAIR_ANCHOR = 5250.0

# ─────────────────────────────── Helpers ──────────────────────────────────────

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-9:
        return max(S - K, 0.0)
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return S * norm_cdf(d1) - K * norm_cdf(d2)

# ─────────────────────────────── Trader ───────────────────────────────────────

class Trader:

    def __init__(self):
        self.hp_fair  = HP_FAIR_ANCHOR
        self.vfe_fair = VFE_FAIR_ANCHOR
        self.hp_alpha = 0.25       # Faster EMA for 98k target
        self.vfe_alpha = 0.20
        self.correlation_beta = 1.9 # Sensitivity of HP to VFE moves
        self.history = {}

    def _mid(self, od: OrderDepth) -> float | None:
        if od.buy_orders and od.sell_orders:
            return (max(od.buy_orders) + min(od.sell_orders)) / 2.0
        return None

    def _pos(self, state: TradingState, product: str) -> int:
        return state.position.get(product, 0)

    def _take_orders(
        self,
        product: str,
        od: OrderDepth,
        fair: float,
        pos: int,
        limit: int,
        edge: float = 0.0
    ) -> Tuple[List[Order], int]:
        """Aggressively take all orders that offer better than (fair +/- edge)."""
        orders: List[Order] = []
        curr_pos = pos

        # Buy underpriced asks
        for ask_price in sorted(od.sell_orders):
            if ask_price > fair - edge:
                break
            vol = -od.sell_orders[ask_price]
            can_buy = min(vol, limit - curr_pos)
            if can_buy > 0:
                orders.append(Order(product, ask_price, can_buy))
                curr_pos += can_buy

        # Sell overpriced bids
        for bid_price in sorted(od.buy_orders, reverse=True):
            if bid_price < fair + edge:
                break
            vol = od.buy_orders[bid_price]
            can_sell = min(vol, curr_pos + limit)
            if can_sell > 0:
                orders.append(Order(product, bid_price, -can_sell))
                curr_pos -= can_sell

        return orders, curr_pos

    def _quote_orders(
        self,
        product: str,
        od: OrderDepth,
        fair: float,
        pos: int,
        limit: int,
        base_spread: int = 1
    ) -> List[Order]:
        """Market-making with aggressive pennying and inventory skew."""
        orders: List[Order] = []
        
        bb = max(od.buy_orders) if od.buy_orders else None
        ba = min(od.sell_orders) if od.sell_orders else None
        
        # Position-based skew (0 to +/- 3 ticks)
        # Using nonlinear skew to stay aggressive but safe at limits
        skew = 3.0 * (pos / limit)
        
        # Pennying logic: try to be best-bid/best-ask
        bid_px = int(round(fair - base_spread - skew))
        ask_px = int(round(fair + base_spread - skew))
        
        # Force quotes to be at least at best-bid+1/best-ask-1 unless we are heavily skewed
        if bb is not None:
            bid_px = max(bid_px, bb + (1 if pos < limit * 0.5 else 0))
        if ba is not None:
            ask_px = min(ask_px, ba - (1 if pos > -limit * 0.5 else 0))
            
        # Cross-protection
        if bid_px >= ba: bid_px = ba - 1
        if ask_px <= bb: ask_px = bb + 1
        if bid_px >= ask_px: bid_px = ask_px - 1

        # Multi-level ladder for more volume
        buy_cap = limit - pos
        sell_cap = limit + pos
        
        if buy_cap > 0:
            sz = min(buy_cap, 40)
            orders.append(Order(product, bid_px, sz))
            if buy_cap > sz:
                orders.append(Order(product, bid_px - 1, min(buy_cap - sz, 20)))

        if sell_cap > 0:
            sz = min(sell_cap, 40)
            orders.append(Order(product, ask_px, -sz))
            if sell_cap > sz:
                orders.append(Order(product, ask_px + 1, -min(sell_cap - sz, 20)))

        return orders

    def _trade_hydrogel(self, state: TradingState, vfe_lead: float) -> List[Order]:
        product = "HYDROGEL_PACK"
        od = state.order_depths.get(product)
        if od is None: return []

        pos = self._pos(state, product)
        limit = POSITION_LIMITS[product]

        mid = self._mid(od)
        if mid is not None:
            self.hp_fair = (1 - self.hp_alpha) * self.hp_fair + self.hp_alpha * mid
        
        # Lead-Lag Alpha: adjust fair based on VFE movement
        fair = self.hp_alpha * self.hp_fair + (1 - self.hp_alpha) * HP_FAIR_ANCHOR
        fair += vfe_lead * self.correlation_beta

        take, new_pos = self._take_orders(product, od, fair, pos, limit, edge=1.0)
        quote = self._quote_orders(product, od, fair, new_pos, limit, base_spread=1)

        return take + quote

    def _trade_velvetfruit(self, state: TradingState) -> Tuple[List[Order], float]:
        product = "VELVETFRUIT_EXTRACT"
        od = state.order_depths.get(product)
        if od is None: return [], 0.0

        pos = self._pos(state, product)
        limit = POSITION_LIMITS[product]

        mid = self._mid(od)
        vfe_lead = 0.0
        if mid is not None:
            vfe_lead = mid - self.vfe_fair
            self.vfe_fair = (1 - self.vfe_alpha) * self.vfe_fair + self.vfe_alpha * mid

        take, new_pos = self._take_orders(product, od, self.vfe_fair, pos, limit, edge=0.5)
        quote = self._quote_orders(product, od, self.vfe_fair, new_pos, limit, base_spread=1)

        return (take + quote), vfe_lead

    def _trade_vev(self, state: TradingState, K: int, S: float) -> List[Order]:
        product = f"VEV_{K}"
        od = state.order_depths.get(product)
        if od is None: return []

        pos = self._pos(state, product)
        limit = POSITION_LIMITS[product]
        tte = TTE_ROUND_START - state.timestamp / TICKS_PER_DAY
        tte = max(tte, 1e-3)

        if K in ITM_VEV_STRIKES:
            fair = max(S - K, 0.0)
            edge_take = 1.0
        else:
            fair = bs_call(S, K, tte, SIGMA_VEV)
            edge_take = 2.0

        take, new_pos = self._take_orders(product, od, fair, pos, limit, edge=edge_take)
        quote = self._quote_orders(product, od, fair, new_pos, limit, base_spread=2)

        return take + quote

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        if state.traderData:
            try:
                data = json.loads(state.traderData)
                self.hp_fair = data.get("hp_fair", HP_FAIR_ANCHOR)
                self.vfe_fair = data.get("vfe_fair", VFE_FAIR_ANCHOR)
            except: pass

        result: Dict[str, List[Order]] = {}

        # 1. Trade VFE first to get lead signal
        vfe_orders, vfe_lead = self._trade_velvetfruit(state)
        if vfe_orders: result["VELVETFRUIT_EXTRACT"] = vfe_orders

        # 2. Trade HP using VFE lead signal
        hp_orders = self._trade_hydrogel(state, vfe_lead)
        if hp_orders: result["HYDROGEL_PACK"] = hp_orders

        # 3. Trade VEVs
        vfe_spot = self.vfe_fair
        for K in ACTIVE_VEV_STRIKES + ITM_VEV_STRIKES:
            orders = self._trade_vev(state, K, vfe_spot)
            if orders: result[f"VEV_{K}"] = orders

        trader_data = json.dumps({
            "hp_fair": round(self.hp_fair, 4),
            "vfe_fair": round(self.vfe_fair, 4),
        })

        return result, 0, trader_data
