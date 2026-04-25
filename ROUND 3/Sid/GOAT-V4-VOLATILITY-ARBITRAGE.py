"""
GOAT Round 3 v4 - Volatility Arbitrage

KEY DISCOVERY: The market is massively overpricing OTM/ATM options
relative to the actual spot volatility.

Spot vol: 0.3% daily (4.7% annualized)
Market pricing for near-ATM/OTM: 50%+ moves implied
=> MASSIVE opportunity to SHORT premium

Strategy:
1. AGGRESSIVELY SHORT OTM options (5300, 5400, 5500, 6000, 6500)
   - Collected premium: ~47, 16, 7, 0.5, 0.5 per contract
   - Realized vol doesn't justify this pricing
   - Build short gamma, let theta work

2. SHORT near-ATM options (5200, 5100) - moderately
   - Still overpriced relative to realized vol
   - Good premium collection

3. HEDGE with deep ITM (4000, 4500)
   - These are fairly priced (only intrinsic value)
   - Buy them to limit downside if spot has rare 500+ move
   - Acts as insurance

4. MARKET-MAKE spot + HP
   - Minimal capital, capture spreads
   - Ensure we don't get wrecked on spot moves

5. DYNAMIC POSITION MGMT
   - Rebalance shorts as spot moves
   - Keep hedge ratio appropriate for risk

This is a VOLATILITY SHORT = short vega, positive theta
Perfect for low-vol regime like this.
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

    # ===== SPOT & HP MM (keep as spread-capture) =====
    
    def _trade_spot_and_hp(self, state: TradingState) -> Dict[str, List[Order]]:
        """Market-make spot and hydrogel with minimal inventory."""
        all_orders = {}
        
        for product in ["VELVETFRUIT_EXTRACT", "HYDROGEL_PACK"]:
            orders = []
            if product not in state.order_depths:
                all_orders[product] = orders
                continue
            
            od = state.order_depths[product]
            pos = state.position.get(product, 0)
            
            limit = {"VELVETFRUIT_EXTRACT": 200, "HYDROGEL_PACK": 200}.get(product)
            
            bid = self._best_bid(od)
            ask = self._best_ask(od)
            if bid is None or ask is None:
                all_orders[product] = orders
                continue
            
            # Tight MM: just join book at best bid/ask
            cap_buy = limit - pos
            cap_sell = limit + pos
            
            if bid is not None and cap_buy > 0:
                orders.append(Order(product, int(bid), min(15, cap_buy)))
            if ask is not None and cap_sell > 0:
                orders.append(Order(product, int(ask), -min(15, cap_sell)))
            
            all_orders[product] = orders
        
        return all_orders

    # ===== VOLATILITY ARBITRAGE: SHORT EXPENSIVE OPTIONS =====
    
    def _trade_short_expensive_otm(self, state: TradingState) -> Dict[str, List[Order]]:
        """
        SHORT the massively overpriced OTM options.
        These price in 50%+ moves but realized vol is 0.3% daily.
        """
        all_orders = {}
        
        # OTM options ranked by mispricing severity:
        # VEV_5300: 47pt time value (2866% overpriced)
        # VEV_5400: 16pt time value (very overpriced)
        # VEV_5500: 7pt time value (overpriced)
        # VEV_6000/6500: 0.5pt time value (marginally overpriced, but free short)
        
        otm_shorts = [
            ("VEV_5300", 45),   # Aggressive short, big premium
            ("VEV_5400", 30),   # Moderate short
            ("VEV_5500", 25),   # Smaller position
            ("VEV_6000", 50),   # Ultra deep OTM, post at 1
            ("VEV_6500", 50),   # Ultra deep OTM, post at 1
        ]
        
        for prod, qty in otm_shorts:
            orders = []
            if prod not in state.order_depths:
                all_orders[prod] = orders
                continue
            
            od = state.order_depths[prod]
            pos = state.position.get(prod, 0)
            cap_sell = 300 + pos
            
            if prod in ["VEV_6000", "VEV_6500"]:
                # Post OTM asks at 1 (free short)
                if cap_sell > 0:
                    orders.append(Order(prod, 1, -min(qty, cap_sell)))
            else:
                # VEV_5300, 5400, 5500: take at market, be aggressive
                bid = self._best_bid(od)
                if bid is not None and cap_sell > 0:
                    # Sell at best bid to get filled on the expensive premium
                    vol_to_sell = min(qty, cap_sell, max(1, int(od.buy_orders.get(bid, qty))))
                    if vol_to_sell > 0:
                        orders.append(Order(prod, bid, -vol_to_sell))
                    cap_sell -= vol_to_sell
                
                # Also post below bid for more fills
                if cap_sell > 0 and bid is not None:
                    our_bid = max(1, int(bid - 1))
                    orders.append(Order(prod, our_bid, -min(qty // 2, cap_sell)))
            
            all_orders[prod] = orders
        
        return all_orders

    # ===== NEAR-ATM SHORT (moderate) =====
    
    def _trade_short_near_atm(self, state: TradingState) -> Dict[str, List[Order]]:
        """
        SHORT near-ATM options that are still overpriced.
        VEV_5200: 45pt time value (85% overpriced)
        VEV_5100: 17pt time value (11% overpriced)
        """
        all_orders = {}
        
        atm_shorts = [
            ("VEV_5200", 25),   # Significant short
            ("VEV_5100", 15),   # Smaller short
        ]
        
        for prod, qty in atm_shorts:
            orders = []
            if prod not in state.order_depths:
                all_orders[prod] = orders
                continue
            
            od = state.order_depths[prod]
            pos = state.position.get(prod, 0)
            cap_sell = 300 + pos
            
            bid = self._best_bid(od)
            if bid is not None and cap_sell > 0:
                vol_to_sell = min(qty, cap_sell, max(1, int(od.buy_orders.get(bid, qty))))
                if vol_to_sell > 0:
                    orders.append(Order(prod, bid, -vol_to_sell))
                    cap_sell -= vol_to_sell
            
            # Post just below bid for fills
            if cap_sell > 0 and bid is not None:
                our_bid = max(1, int(bid - 1))
                orders.append(Order(prod, our_bid, -min(qty // 2, cap_sell)))
            
            all_orders[prod] = orders
        
        return all_orders

    # ===== HEDGE: LONG DEEP ITM =====
    
    def _trade_hedge_deep_itm(self, state: TradingState) -> Dict[str, List[Order]]:
        """
        BUY deep ITM options as a hedge against rare large spot moves.
        These are fairly priced (only intrinsic value), so reasonable risk/reward.
        VEV_4000, VEV_4500: depth provides gamma long protection.
        """
        all_orders = {}
        
        # Deep ITM hedges - buy them to limit downside
        itm_hedges = [
            ("VEV_4000", 8),    # Small hedge position
            ("VEV_4500", 10),   # Slightly larger hedge
        ]
        
        for prod, qty in itm_hedges:
            orders = []
            if prod not in state.order_depths:
                all_orders[prod] = orders
                continue
            
            od = state.order_depths[prod]
            pos = state.position.get(prod, 0)
            cap_buy = 300 - pos
            
            if cap_buy > 0:
                ask = self._best_ask(od)
                if ask is not None:
                    vol_to_buy = min(qty, cap_buy, max(1, int(od.sell_orders.get(ask, qty))))
                    if vol_to_buy > 0:
                        orders.append(Order(prod, ask, vol_to_buy))
            
            all_orders[prod] = orders
        
        return all_orders

    # ===== LIQUID ATM OPTIONS: QUOTE BALANCED =====
    
    def _trade_liquid_options(self, state: TradingState) -> Dict[str, List[Order]]:
        """
        VEV_5000: slightly overpriced (2%), minimal position
        Be more balanced here - quote both sides but lean short.
        """
        all_orders = {}
        
        prod = "VEV_5000"
        orders = []
        if prod in state.order_depths:
            od = state.order_depths[prod]
            pos = state.position.get(prod, 0)
            
            bid = self._best_bid(od)
            ask = self._best_ask(od)
            if bid is not None and ask is not None:
                # Prefer to short (overpriced)
                cap_sell = 300 + pos
                if cap_sell > 0:
                    orders.append(Order(prod, int(bid), -min(12, cap_sell)))
                
                # Also willing to buy cheaper
                cap_buy = 300 - pos
                if cap_buy > 0:
                    orders.append(Order(prod, int(ask), min(8, cap_buy)))
        
        all_orders[prod] = orders
        return all_orders

    def run(self, state: TradingState):
        try:
            sd: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            sd = {}

        all_orders: Dict[str, List[Order]] = {}

        # Execute strategies
        all_orders.update(self._trade_spot_and_hp(state))
        all_orders.update(self._trade_short_expensive_otm(state))
        all_orders.update(self._trade_short_near_atm(state))
        all_orders.update(self._trade_hedge_deep_itm(state))
        all_orders.update(self._trade_liquid_options(state))

        return all_orders, 0, json.dumps(sd)
