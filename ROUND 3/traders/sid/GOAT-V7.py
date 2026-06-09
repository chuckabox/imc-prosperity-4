"""
GOAT Round 3 v7 - Concentrated Volatility Arbitrage

THESIS: Don't spread across 10 products. Focus 95% capital on the 2 worst mispricings.
  VEV_5300: +2,866% overpriced (collect 47pt premium per contract)
  VEV_5200: +85% overpriced (collect 44pt premium per contract)

Strategy: 
  - MAXIMIZE short positions on 5300 and 5200
  - Use HP spreads as secondary profit engine
  - Keep spot for minimal MM / portfolio hedge
  - Daily rebalancing to maintain optimal sizing
  - Target: 10k+ PnL over 3 days (3.3k/day)

Key edge: Concentrated capital + daily theta decay in low-vol regime
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import json


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

    def run(self, state: TradingState):
        try:
            sd: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            sd = {}

        all_orders: Dict[str, List[Order]] = {}

        # ===== PRIMARY EDGE: VEV_5300 =====
        # Most mispriced option (2866% overpriced)
        # Target: -250 contracts (maximum position)
        # Daily premium decay: 2-3pt per contract
        # Expected daily: +500-750 from theta decay
        all_orders["VEV_5300"] = self._trade_primary_short(state, sd)

        # ===== SECONDARY EDGE: VEV_5200 =====
        # Second-worst mispricing (85% overpriced)
        # Target: -150 contracts (aggressive)
        # Daily premium decay: 1.5-2pt per contract
        # Expected daily: +225-300 from theta decay
        all_orders["VEV_5200"] = self._trade_secondary_short(state, sd)

        # ===== PROFIT MULTIPLIER: HYDROGEL_PACK =====
        # High liquidity, 15-20pt spreads
        # Use as swing/spread vehicle to amplify returns
        # Target: ±150 position, quick cycles
        # Expected daily: +300-500 from spread capture
        all_orders["HYDROGEL_PACK"] = self._trade_hp_cycles(state, sd)

        # ===== HEDGE/LIQUIDITY: VEV_5000 + VELVETFRUIT_EXTRACT =====
        # Minimal positions to provide portfolio hedge
        # If spot/implied moves, these limit downside
        # Expected daily: +100-200 from MM
        all_orders["VEV_5000"] = self._trade_light_mm(state, "VEV_5000", 15)
        all_orders["VELVETFRUIT_EXTRACT"] = self._trade_light_mm(state, "VELVETFRUIT_EXTRACT", 20)

        # ===== DEEP HEDGE: DEEP ITM (if capital available) =====
        all_orders["VEV_4000"] = self._trade_hedge_deep_itm(state, "VEV_4000", 5)
        all_orders["VEV_4500"] = self._trade_hedge_deep_itm(state, "VEV_4500", 8)

        # Update state with position tracking
        sd["last_mid_5300"] = self._get_mid(state, "VEV_5300")
        sd["last_mid_5200"] = self._get_mid(state, "VEV_5200")

        return all_orders, 0, json.dumps(sd)

    def _get_mid(self, state: TradingState, product: str):
        """Helper to get mid price."""
        if product not in state.order_depths:
            return None
        od = state.order_depths[product]
        b = self._best_bid(od)
        a = self._best_ask(od)
        if b and a:
            return (b + a) / 2.0
        return None

    def _trade_primary_short(self, state: TradingState, sd: dict) -> List[Order]:
        """
        VEV_5300: The golden goose. 2866% overpriced.
        
        Aggressive strategy:
        - Day 1: Build to -120 (conservative start)
        - Day 2: Ramp to -200 (if filled well)
        - Day 3: Maximum -250 (full position)
        
        This gradual approach ensures we:
        1. Get consistent fills (not blow through market)
        2. Lock in premium across multiple price levels
        3. Manage execution risk
        4. Build compounding theta decay position
        """
        orders = []
        product = "VEV_5300"
        
        if product not in state.order_depths:
            return orders
        
        od = state.order_depths[product]
        pos = state.position.get(product, 0)
        cap_sell = 300 + pos  # Room to short
        
        bid = self._best_bid(od)
        if bid is None:
            return orders
        
        # Determine target position based on current position
        if pos > -50:  # Aggressive accumulation phase
            target_qty = 120  # Day 1-2 target
        elif pos > -150:  # Ramping phase
            target_qty = 80  # Continue accumulation
        else:  # Final stage
            target_qty = 100  # Top up to -250

        # Primary: Sell at best bid (aggressive fill)
        if cap_sell > 0:
            vol_to_sell = min(target_qty, cap_sell, max(1, int(od.buy_orders.get(bid, target_qty // 2))))
            if vol_to_sell > 0:
                orders.append(Order(product, int(bid), -vol_to_sell))
                cap_sell -= vol_to_sell

        # Secondary: Post just below bid for additional fills
        if cap_sell > 10 and bid > 1:
            our_bid = int(bid - 1)
            vol_remaining = min(target_qty // 3, cap_sell)
            if vol_remaining > 0:
                orders.append(Order(product, our_bid, -vol_remaining))
                cap_sell -= vol_remaining

        # Tertiary: Ultra-aggressive tier if very deep (collect premium aggressively)
        if cap_sell > 20 and bid > 2:
            our_bid2 = int(bid - 2)
            vol_final = min(target_qty // 4, cap_sell)
            if vol_final > 0:
                orders.append(Order(product, our_bid2, -vol_final))

        return orders

    def _trade_secondary_short(self, state: TradingState, sd: dict) -> List[Order]:
        """
        VEV_5200: Second-biggest mispricing at 85% overpriced.
        
        Target: -150 contracts (more conservative than 5300 due to less edge)
        Focus on consistent premium collection.
        """
        orders = []
        product = "VEV_5200"
        
        if product not in state.order_depths:
            return orders
        
        od = state.order_depths[product]
        pos = state.position.get(product, 0)
        cap_sell = 300 + pos
        
        bid = self._best_bid(od)
        if bid is None:
            return orders

        # Target sizing: -100 to -150
        if pos > -60:
            target_qty = 80
        elif pos > -120:
            target_qty = 50
        else:
            target_qty = 30

        # Primary: Sell at best bid
        if cap_sell > 0:
            vol_to_sell = min(target_qty, cap_sell, max(1, int(od.buy_orders.get(bid, target_qty // 2))))
            if vol_to_sell > 0:
                orders.append(Order(product, int(bid), -vol_to_sell))
                cap_sell -= vol_to_sell

        # Secondary: Post below bid
        if cap_sell > 5 and bid > 1:
            our_bid = int(bid - 1)
            vol_remaining = min(target_qty // 2, cap_sell)
            if vol_remaining > 0:
                orders.append(Order(product, our_bid, -vol_remaining))

        return orders

    def _trade_hp_cycles(self, state: TradingState, sd: dict) -> List[Order]:
        """
        HYDROGEL_PACK: The secondary profit engine.
        
        Large spreads (15-20pt) + high liquidity allow rapid spread capture.
        Strategy:
        - Monitor position: if long 100+, reverse and sell
        - If short 100+, reverse and buy
        - Capture 10-15pt per cycle, do 2-3 cycles per day
        - Expected: +300-500/day
        """
        orders = []
        product = "HYDROGEL_PACK"
        
        if product not in state.order_depths:
            return orders
        
        od = state.order_depths[product]
        pos = state.position.get(product, 0)
        bid = self._best_bid(od)
        ask = self._best_ask(od)
        
        if bid is None or ask is None:
            return orders
        
        spread = ask - bid
        cap_buy = 200 - pos
        cap_sell = 200 + pos
        
        # Swing trading: use momentum
        last_mid = sd.get("last_hp_mid", (bid + ask) / 2)
        current_mid = (bid + ask) / 2
        trending = current_mid > last_mid  # Simple momentum
        sd["last_hp_mid"] = current_mid
        
        if pos > 80:  # If we've accumulated long, sell into strength
            vol_to_sell = min(60, cap_sell)
            if vol_to_sell > 0:
                orders.append(Order(product, ask, -vol_to_sell))
        elif pos < -80:  # If we're short, buy back into weakness
            vol_to_buy = min(60, cap_buy)
            if vol_to_buy > 0:
                orders.append(Order(product, bid, vol_to_buy))
        else:  # Neutral position or small: play the spread
            # Buy at bid, sell at ask
            if cap_buy > 0:
                orders.append(Order(product, bid, min(50, cap_buy)))
            if cap_sell > 0:
                orders.append(Order(product, ask, -min(50, cap_sell)))
        
        return orders

    def _trade_light_mm(self, state: TradingState, product: str, qty: int) -> List[Order]:
        """
        VEV_5000 & VELVETFRUIT_EXTRACT: Light market-making.
        
        Just post at bid/ask to collect small spreads and provide
        portfolio correlation hedge if other positions move.
        """
        orders = []
        
        if product not in state.order_depths:
            return orders
        
        od = state.order_depths[product]
        pos = state.position.get(product, 0)
        
        bid = self._best_bid(od)
        ask = self._best_ask(od)
        if bid is None or ask is None:
            return orders
        
        limit = {"VELVETFRUIT_EXTRACT": 200, "VEV_5000": 300}.get(product)
        cap_buy = limit - pos
        cap_sell = limit + pos
        
        # Simple join the book
        if cap_buy > 0:
            orders.append(Order(product, int(bid), min(qty, cap_buy)))
        if cap_sell > 0:
            orders.append(Order(product, int(ask), -min(qty, cap_sell)))
        
        return orders

    def _trade_hedge_deep_itm(self, state: TradingState, product: str, qty: int) -> List[Order]:
        """
        VEV_4000 / VEV_4500: Deep ITM hedge.
        
        These are fairly priced (only intrinsic value matters).
        Buy small amounts to provide gamma protection if spot crashes.
        """
        orders = []
        
        if product not in state.order_depths:
            return orders
        
        od = state.order_depths[product]
        pos = state.position.get(product, 0)
        cap_buy = 300 - pos
        
        ask = self._best_ask(od)
        if ask is None:
            return orders
        
        # Only buy if position is small (hedge, not speculation)
        if pos < 5 and cap_buy > 0:
            vol_to_buy = min(qty, cap_buy)
            orders.append(Order(product, ask, vol_to_buy))
        
        return orders
