"""
trader_peter_v10.py
===================
HFT Market Maker for IMC Prosperity Round 1.
Products: INTARIAN_PEPPER_ROOT, ASH_COATED_OSMIUM

Strategy:
  - EMA(20) of weighted mid-price as Fair Value
  - Competitive quoting: Best Bid+1 / Best Ask-1
  - Minimum edge of 1.0 vs Fair Value (no adverse fills)
  - Linear inventory leaning (elastic band) toward zero
  - Osmium: velocity-based spread widening + informed trader detection
  - Full state persistence via trader_data JSON
"""

import json
from typing import Any, Dict, List
from collections import Counter
from datamodel import Order, OrderDepth, TradingState, Symbol, Trade


# ─────────────────────────────────────────
#  Config
# ─────────────────────────────────────────
PRODUCTS = ["INTARIAN_PEPPER_ROOT", "ASH_COATED_OSMIUM"]

CONFIG = {
    "INTARIAN_PEPPER_ROOT": {
        "limit":          80,
        "ema_period":     8,     # Faster (was 20)
        "base_edge":      1.0,
        "leaning_factor": 0.05,
    },
    "ASH_COATED_OSMIUM": {
        "limit":             80,
        "ema_period":        5,     # Aggressive (was 20)
        "base_edge":         1.0,
        "leaning_factor":    0.1,
        "velocity_threshold":0.5,
        "velocity_edge_add": 1.0,
        "pattern_window":    30,
        "pattern_threshold": 4,
    },
}


# ─────────────────────────────────────────
#  Logger (stdout for Prosperity visualiser)
# ─────────────────────────────────────────
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
        print(self.logs, end="")
        self.logs = ""


logger = Logger()


# ─────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────
def weighted_mid(depth: OrderDepth) -> float | None:
    """Volume-weighted mid price. Better than naive (bid+ask)/2."""
    if not depth.buy_orders or not depth.sell_orders:
        return None
    best_bid = max(depth.buy_orders)
    best_ask = min(depth.sell_orders)
    bid_vol = abs(depth.buy_orders[best_bid])
    ask_vol = abs(depth.sell_orders[best_ask])
    total = bid_vol + ask_vol
    if total == 0:
        return (best_bid + best_ask) / 2
    return (best_bid * ask_vol + best_ask * bid_vol) / total


def ema_update(prev_ema: float, price: float, period: int) -> float:
    k = 2 / (period + 1)
    return price * k + prev_ema * (1 - k)


# ─────────────────────────────────────────
#  Trader
# ─────────────────────────────────────────
class Trader:
    """
    Peter V10 — EMA Fair Value Market Maker
    ----------------------------------------
    Smooth PnL via tight competitive quoting + elastic-band inventory control.
    """

    def run(self, state: TradingState):
        # ── Load persisted state ──────────────────────────────────────────
        try:
            saved: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            saved = {}

        ema_map: dict      = saved.get("ema", {})        # product → last EMA
        prev_pos: dict     = saved.get("prev_pos", {})   # for PnL delta log
        osmium_sizes: list = saved.get("osmium_sizes", [])  # recent trade size buffer

        result: Dict[str, List[Order]] = {}

        for product in PRODUCTS:
            if product not in state.order_depths:
                continue

            cfg   = CONFIG[product]
            depth = state.order_depths[product]
            pos   = state.position.get(product, 0)
            limit = cfg["limit"]

            # ── Weighted mid / EMA with Trend Lead ────────────────────────
            wm = weighted_mid(depth)
            if wm is None:
                logger.print(f"[{state.timestamp}] {product}: empty book — skip")
                continue

            prev_ema = ema_map.get(product)
            if prev_ema is None:
                ema = wm
                fair_value = wm
            else:
                ema = ema_update(prev_ema, wm, cfg["ema_period"])
                # Trend lead: EMA + 1.2x velocity to anticipate next tick drift
                velocity   = (ema - prev_ema)
                fair_value = ema + (velocity * 1.2)
            
            ema_map[product] = ema

            # ── Best bid / ask ────────────────────────────────────────────
            best_bid = max(depth.buy_orders)
            best_ask = min(depth.sell_orders)

            # ── Required edge ─────────────────────────────────────────────
            required_edge = cfg["base_edge"]

            if product == "ASH_COATED_OSMIUM":
                v_abs = abs(ema - prev_ema) if prev_ema is not None else 0.0
                if v_abs >= cfg["velocity_threshold"]:
                    required_edge += cfg["velocity_edge_add"]

                # Pattern detection
                trades: List[Trade] = state.market_trades.get(product, [])
                for t in trades:
                    osmium_sizes.append(abs(t.quantity))
                osmium_sizes = osmium_sizes[-cfg["pattern_window"]:]

                # Count repeated sizes → detect informed traders
                size_counts = Counter(osmium_sizes)
                informed_sizes = {sz for sz, cnt in size_counts.items()
                                  if cnt >= cfg["pattern_threshold"]}
                if informed_sizes:
                    required_edge += 1.0

            # ── Inventory leaning adjustment ──────────────────────────────
            lean = cfg["leaning_factor"] * pos
            
            # Adjusted prices relative to trend-aware Fair Value
            adj_bid = fair_value - required_edge - lean
            adj_ask = fair_value + required_edge - lean

            # ── Competitive quoting ───────────────────────────────────────
            # Try to capture the spread by being at Best+/-1, 
            # but capped by our FairValue+Edge safety.
            bid_price  = min(best_bid + 1, int(adj_bid))
            ask_price  = max(best_ask - 1, int(adj_ask))

            # Guard: bid must be strictly below ask
            if bid_price >= ask_price:
                bid_price = ask_price - 1

            # ── Position capacity ─────────────────────────────────────────
            buy_cap  = limit - pos
            sell_cap = limit + pos

            orders: List[Order] = []
            if buy_cap > 0:
                orders.append(Order(product, int(bid_price),  buy_cap))
            if sell_cap > 0:
                orders.append(Order(product, int(ask_price), -sell_cap))

            result[product] = orders

            # ── Log row ───────────────────────────────────────────────────
            prev  = prev_pos.get(product, 0)
            delta = pos - prev
            logger.print(
                f"[{state.timestamp}] {product} | "
                f"Mid={wm:.1f} FV={fair_value:.1f} | "
                f"pos={pos:+d} d{delta:+d} | "
                f"bid={bid_price} ask={ask_price} edge={required_edge:.1f}"
            )
            prev_pos[product] = pos

        # ── Persist state ─────────────────────────────────────────────────
        new_state = json.dumps({
            "ema":          ema_map,
            "prev_pos":     prev_pos,
            "osmium_sizes": osmium_sizes,
        })

        logger.flush(state, result, 0, new_state)
        return result, 0, new_state
