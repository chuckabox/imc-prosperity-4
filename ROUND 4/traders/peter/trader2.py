"""trader2.py — Round 4 Hybrid.
Baseline: lamp.py (ken)
Enhancements:
1. Increased Position Limits (200/200/300).
2. Hydrogel as Volatility Oracle for VEV (HGP mid adjusts time-value floors).
3. ITM Option Arbitrage (explicit parity checks for 4000/4500).
4. Expanded VEV strike universe (added 5100, 5200, 5300).
5. Tuned Taker/Maker sizes for higher limits.
"""
import json
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from datamodel import Order, TradingState


class Trader:
    CFG = {
        "enable_take": True,
        "hydro_edge": 4,         # Tighter for more fills
        "hydro_clip": 20,
        "hydro_momo_k": 0.15,
        "hydro_take_th": 1.5,
        "hydro_take_size": 15,
        
        "vfe_edge": 1,           # Competitive pricing
        "vfe_clip": 25,
        "vfe_momo_k": 0.15,
        "vfe_take_th": 1.2,
        "vfe_take_size": 20,
        
        "vev_strikes": [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500],
        "vev_threshold": 4.5,    # Reduced threshold for better capture
        "vev_size": 12,
        
        "oracle_sensitivity": 0.08, # Floor adjustment per HGP point dev from 10k
    }
    
    POSITION_LIMITS = {
        "HYDROGEL_PACK": 200, 
        "VELVETFRUIT_EXTRACT": 200, 
        "VEV_4000": 300, "VEV_4500": 300,
        "VEV_5000": 300, "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
        "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300, "VEV_6500": 300,
    }
    
    # Baseline floors from INITIAL_FINDINGS
    VEV_TIME_VALUE_FLOOR = {
        4000: 0.0, 4500: 0.0, 5000: 3.4, 5100: 12.2, 
        5200: 36.3, 5300: 53.7, 5400: 18.6, 5500: 7.3, 
        6000: 0.5, 6500: 0.5
    }
    
    MARK_BUY = {"Mark 67", "Mark 01", "Mark 38"}
    MARK_SELL = {"Mark 49", "Mark 22", "Mark 14"}

    def _load_state(self, trader_data: str) -> Dict:
        if not trader_data: return {"mark_signal": {}, "last_mid": {}}
        try:
            s = json.loads(trader_data)
            s.setdefault("mark_signal", {})
            s.setdefault("last_mid", {})
            return s
        except Exception:
            return {"mark_signal": {}, "last_mid": {}}

    def _save_state(self, state: Dict) -> str: 
        return json.dumps(state, separators=(",", ":"))

    @staticmethod
    def _best_bid_ask(order_depth) -> Tuple[Optional[int], Optional[int]]:
        if not order_depth.buy_orders or not order_depth.sell_orders: return None, None
        return max(order_depth.buy_orders.keys()), min(order_depth.sell_orders.keys())

    def _mid_price(self, state: TradingState, symbol: str, cache: Dict[str, float]) -> Optional[float]:
        if symbol in cache: return cache[symbol]
        depth = state.order_depths.get(symbol)
        if not depth: return None
        bid, ask = self._best_bid_ask(depth)
        if bid is None or ask is None: return None
        mid = 0.5 * (bid + ask)
        cache[symbol] = mid
        return mid

    def _update_mark_signal(self, state: TradingState, mem: Dict) -> None:
        ms = mem["mark_signal"]
        for k in list(ms.keys()):
            ms[k] *= 0.85
            if abs(ms[k]) < 0.05: del ms[k]
        for symbol, trades in state.market_trades.items():
            if not trades: continue
            s = ms.get(symbol, 0.0)
            for t in trades:
                qty = abs(t.quantity); buyer = t.buyer; seller = t.seller
                if buyer in self.MARK_BUY: s += 0.15 * qty
                if seller in self.MARK_SELL: s += 0.10 * qty
                if buyer in self.MARK_SELL: s -= 0.15 * qty
                if seller in self.MARK_BUY: s -= 0.10 * qty
            if abs(s) > 0.01: ms[symbol] = max(-50.0, min(50.0, s))

    def _mm_orders(self, symbol: str, state: TradingState, fair: float, edge: int, clip: int, skew: float) -> List[Order]:
        orders: List[Order] = []
        depth = state.order_depths.get(symbol)
        if not depth: return orders
        pos = state.position.get(symbol, 0)
        lim = self.POSITION_LIMITS.get(symbol, 100)
        bid_cap = max(0, lim - pos); ask_cap = max(0, lim + pos)
        if bid_cap <= 0 and ask_cap <= 0: return orders
        
        # Fair adjusted by skew and inventory pressure
        fair_adj = fair + skew - 0.05 * pos
        bid_px = int(math.floor(fair_adj - edge))
        ask_px = int(math.ceil(fair_adj + edge))
        
        if bid_px >= ask_px: ask_px = bid_px + 1
        
        # Use best bid/ask to cross if possible but stay within limits
        best_bid, best_ask = self._best_bid_ask(depth)
        
        if bid_cap > 0:
            orders.append(Order(symbol, bid_px, min(clip, bid_cap)))
        if ask_cap > 0:
            orders.append(Order(symbol, ask_px, -min(clip, ask_cap)))
        return orders

    def _take_edge_orders(self, symbol: str, state: TradingState, fair: float, threshold: float, max_take: int) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth: return []
        orders: List[Order] = []
        pos = state.position.get(symbol, 0); lim = self.POSITION_LIMITS.get(symbol, 100)
        buy_cap = max(0, lim - pos); sell_cap = max(0, lim + pos)
        
        best_bid, best_ask = self._best_bid_ask(depth)
        
        if best_ask is not None and best_ask <= fair - threshold and buy_cap > 0:
            qty = min(max_take, buy_cap, abs(depth.sell_orders[best_ask]))
            if qty > 0: orders.append(Order(symbol, best_ask, qty))
        if best_bid is not None and best_bid >= fair + threshold and sell_cap > 0:
            qty = min(max_take, sell_cap, abs(depth.buy_orders[best_bid]))
            if qty > 0: orders.append(Order(symbol, best_bid, -qty))
        return orders

    def _vev_orders(self, symbol: str, state: TradingState, vfe_mid: float, hydro_mid: float) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth or vfe_mid is None: return []
        
        k = int(symbol.split("_")[1])
        enabled = set(self.CFG.get("vev_strikes", []))
        if k not in enabled: return []
        
        bid, ask = self._best_bid_ask(depth)
        if bid is None or ask is None: return []
        
        # Oracle Adjustment
        oracle_adj = 0.0
        if hydro_mid is not None:
            # Shift floor based on HGP deviation from baseline 9995
            oracle_adj = (hydro_mid - 9995.0) * self.CFG.get("oracle_sensitivity", 0.08)
        
        base_floor = self.VEV_TIME_VALUE_FLOOR.get(k, 0.0)
        # Only apply oracle to strikes with significant time value
        adj_floor = base_floor + oracle_adj if base_floor > 1.0 else base_floor
        
        theo = max(vfe_mid - k, 0.0) + max(0.0, adj_floor)
        mid = 0.5 * (bid + ask)
        mispricing = mid - theo
        
        pos = state.position.get(symbol, 0)
        lim = self.POSITION_LIMITS.get(symbol, 100)
        buy_cap = max(0, lim - pos); sell_cap = max(0, lim + pos)
        
        th = self.CFG.get("vev_threshold", 4.5); size = self.CFG.get("vev_size", 10)
        
        # Aggressive take if mispriced
        if mispricing < -th and buy_cap > 0: return [Order(symbol, ask, min(size, buy_cap))]
        if mispricing > th and sell_cap > 0: return [Order(symbol, bid, -min(size, sell_cap))]
        
        # ITM Synthetic Arb (Pure Parity)
        if k in [4000, 4500]:
            intrinsic = vfe_mid - k
            if ask < intrinsic - 0.5 and buy_cap > 0:
                return [Order(symbol, ask, min(size, buy_cap))]
            if bid > intrinsic + 0.5 and sell_cap > 0:
                return [Order(symbol, bid, -min(size, sell_cap))]
        
        return []

    def run(self, state: TradingState):
        mem = self._load_state(state.traderData)
        self._update_mark_signal(state, mem)
        mids: Dict[str, float] = {}; result: Dict[str, List[Order]] = defaultdict(list)
        
        vfe_mid = self._mid_price(state, "VELVETFRUIT_EXTRACT", mids)
        hydro_mid = self._mid_price(state, "HYDROGEL_PACK", mids)
        
        # 1. HYDROGEL
        if hydro_mid is not None:
            last = mem["last_mid"].get("HYDROGEL_PACK", hydro_mid)
            momo = hydro_mid - last
            mark = mem["mark_signal"].get("HYDROGEL_PACK", 0.0)
            skew = 0.08 * mark + self.CFG.get("hydro_momo_k", 0.15) * momo
            
            result["HYDROGEL_PACK"].extend(self._mm_orders("HYDROGEL_PACK", state, hydro_mid, self.CFG["hydro_edge"], self.CFG["hydro_clip"], skew))
            result["HYDROGEL_PACK"].extend(self._take_edge_orders("HYDROGEL_PACK", state, hydro_mid + skew, self.CFG["hydro_take_th"], self.CFG["hydro_take_size"]))
            mem["last_mid"]["HYDROGEL_PACK"] = hydro_mid
            
        # 2. VFE
        if vfe_mid is not None:
            last = mem["last_mid"].get("VELVETFRUIT_EXTRACT", vfe_mid)
            momo = vfe_mid - last
            mark = mem["mark_signal"].get("VELVETFRUIT_EXTRACT", 0.0)
            skew = 0.07 * mark + self.CFG.get("vfe_momo_k", 0.15) * momo
            
            result["VELVETFRUIT_EXTRACT"].extend(self._mm_orders("VELVETFRUIT_EXTRACT", state, vfe_mid, self.CFG["vfe_edge"], self.CFG["vfe_clip"], skew))
            result["VELVETFRUIT_EXTRACT"].extend(self._take_edge_orders("VELVETFRUIT_EXTRACT", state, vfe_mid + skew, self.CFG["vfe_take_th"], self.CFG["vfe_take_size"]))
            mem["last_mid"]["VELVETFRUIT_EXTRACT"] = vfe_mid
            
            # 3. VEVs (dependent on VFE and HGP Oracle)
            for symbol in state.order_depths.keys():
                if symbol.startswith("VEV_") and symbol in self.POSITION_LIMITS:
                    result[symbol].extend(self._vev_orders(symbol, state, vfe_mid, hydro_mid))
                    
        return dict(result), 0, self._save_state(mem)
