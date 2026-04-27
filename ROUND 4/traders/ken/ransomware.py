import json
import math
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState

class Trader:
    # Round 4 Strategy: "Ransomware v3 - Whale Hunt"
    # IMPROVEMENTS:
    # 1. Aggressive Whale Tracking: Specifically leans with Mark 67/49 volume spikes.
    # 2. Reduced Options Bleed: Increased edge and more conservative delta-hedging.
    # 3. Dynamic Spread Skew: Narrows spread on whale side to ensure fills.

    POSITION_LIMITS = {
        "HYDROGEL_PACK": 60,
        "VELVETFRUIT_EXTRACT": 60,
        "VEV_4000": 25,
        "VEV_4500": 25,
        "VEV_5000": 30,
        "VEV_5100": 30,
        "VEV_5200": 30,
        "VEV_5300": 30,
        "VEV_5400": 25,
        "VEV_5500": 25,
        "VEV_6000": 20,
        "VEV_6500": 20,
    }

    # "Whales" with high persistence
    WHALES = {
        "Mark 67": 1.0,  # Alpha Whale (Bullish)
        "Mark 49": -1.0, # Beta Whale (Bearish)
        "Mark 22": -0.8, # Liquidity Provider (Mean-reverting)
        "Mark 38": 0.5,  # Momentum follower
        "Mark 01": 0.5,
        "Mark 14": -0.5,
    }

    def _norm_cdf(self, x):
        a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
        p, sign = 0.3275911, 1
        if x < 0: sign = -1
        x = abs(x) / math.sqrt(2.0)
        t = 1.0 / (1.0 + p * x)
        y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
        return 0.5 * (1.0 + sign * y)

    def _black_scholes_call(self, S, K, T, r, sigma):
        if T <= 0 or sigma <= 0: return max(0, S - K), (1.0 if S > K else 0.0)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        delta = self._norm_cdf(d1)
        price = S * delta - K * math.exp(-r * T) * self._norm_cdf(d2)
        return price, delta

    def _load_state(self, trader_data: str) -> Dict:
        defaults = {"mark_signal": {}, "vol_cache": 0.16, "whale_vol": {}}
        if not trader_data: return defaults
        try:
            return json.loads(trader_data)
        except:
            return defaults

    def _save_state(self, state: Dict) -> str:
        return json.dumps(state, separators=(",", ":"))

    def _get_mid(self, state: TradingState, symbol: str) -> float:
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders or not depth.sell_orders: return None
        return 0.5 * (max(depth.buy_orders.keys()) + min(depth.sell_orders.keys()))

    def run(self, state: TradingState):
        mem = self._load_state(state.traderData)
        result: Dict[str, List[Order]] = defaultdict(list)
        
        # 1. Volatility Oracle
        hydro_mid = self._get_mid(state, "HYDROGEL_PACK")
        if hydro_mid:
            mem["vol_cache"] = max(0.01, (hydro_mid - 9700) / 2400.0 + 0.13)
        sigma = mem["vol_cache"]
        vfe_mid = self._get_mid(state, "VELVETFRUIT_EXTRACT")
        
        # 2. WHALE TRACKER (Aggressive)
        for symbol, trades in state.market_trades.items():
            s = mem["mark_signal"].get(symbol, 0.0)
            wv = mem["whale_vol"].get(symbol, 0.0)
            for t in trades:
                qty = abs(t.quantity)
                # Tracking Buyer Bias
                if t.buyer in self.WHALES:
                    s += self.WHALES[t.buyer] * qty * 0.5
                    wv += qty
                # Tracking Seller Bias
                if t.seller in self.WHALES:
                    s -= self.WHALES[t.seller] * qty * 0.5
                    wv += qty
            mem["mark_signal"][symbol] = max(-100, min(100, s * 0.88))
            mem["whale_vol"][symbol] = wv * 0.8 # Decay whale volume influence

        # 3. Options (Increased Edge to stop bleed)
        total_delta = 0.0
        if vfe_mid:
            T_rem = max(0.0001, (1000000 - state.timestamp) / 1000000.0)
            for symbol in self.POSITION_LIMITS:
                if not symbol.startswith("VEV_"): continue
                strike = int(symbol.split("_")[1])
                fair_price, delta = self._black_scholes_call(vfe_mid, strike, T_rem, 0, sigma)
                if strike <= 4500: fair_price = max(fair_price, vfe_mid - strike)
                
                curr_pos = state.position.get(symbol, 0)
                total_delta += curr_pos * delta
                
                # WHALE SKEW for Options: If Mark 67 is buying Extract, we expect options to rise
                opt_skew = mem["mark_signal"].get("VELVETFRUIT_EXTRACT", 0.0) * 0.05
                base_edge = 9 # WIDENED from 6 to stop the 8k bleed
                
                limit = self.POSITION_LIMITS[symbol]
                bid_px = int(fair_price + opt_skew - base_edge - (curr_pos * 0.08))
                ask_px = int(fair_price + opt_skew + base_edge - (curr_pos * 0.08))
                
                if limit - curr_pos > 0: result[symbol].append(Order(symbol, bid_px, limit - curr_pos))
                if limit + curr_pos > 0: result[symbol].append(Order(symbol, ask_px, -(limit + curr_pos)))

        # 4. VELVETFRUIT_EXTRACT (Whale Lean)
        if vfe_mid:
            vfe_pos = state.position.get("VELVETFRUIT_EXTRACT", 0)
            vfe_skew = mem["mark_signal"].get("VELVETFRUIT_EXTRACT", 0.0) * 0.2 # DOUBLED multiplier
            
            # The Hedge target remains the same
            hedge_target = -int(round(total_delta))
            hedge_target = max(-45, min(45, hedge_target))
            
            # WHALE LEAN: Narrow spread on the side the whale is moving
            # If vfe_skew is positive (bullish), bid_px moves up more than ask_px (narrower spread on buy side)
            edge = 2
            bid_px = int(vfe_mid + vfe_skew - edge + (hedge_target - vfe_pos) * 0.15)
            ask_px = int(vfe_mid + vfe_skew + edge + (hedge_target - vfe_pos) * 0.15)
            
            limit = self.POSITION_LIMITS["VELVETFRUIT_EXTRACT"]
            if limit - vfe_pos > 0: result["VELVETFRUIT_EXTRACT"].append(Order("VELVETFRUIT_EXTRACT", bid_px, limit - vfe_pos))
            if limit + vfe_pos > 0: result["VELVETFRUIT_EXTRACT"].append(Order("VELVETFRUIT_EXTRACT", ask_px, -(limit + vfe_pos)))

        # 5. HYDROGEL_PACK
        if hydro_mid:
            h_pos = state.position.get("HYDROGEL_PACK", 0)
            h_edge = 4
            limit = self.POSITION_LIMITS["HYDROGEL_PACK"]
            bid_px = int(hydro_mid - h_edge - h_pos * 0.06)
            ask_px = int(hydro_mid + h_edge - h_pos * 0.06)
            if limit - h_pos > 0: result["HYDROGEL_PACK"].append(Order("HYDROGEL_PACK", bid_px, limit - h_pos))
            if limit + h_pos > 0: result["HYDROGEL_PACK"].append(Order("HYDROGEL_PACK", ask_px, -(limit + h_pos)))

        return result, 0, self._save_state(mem)
