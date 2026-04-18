"""
trader_robust_suvin_v1.py
Iteration 11: VECM Information Layer & Alpha Push
"""

import json
import math
from typing import Dict, List, Any, Optional, Tuple
import numpy as np

try:
    from datamodel import Order, OrderDepth, TradingState, Symbol
except ImportError:
    class Order:
        def __init__(self, symbol, price, quantity):
            self.symbol = symbol; self.price = price; self.quantity = quantity
    Symbol = str

def _median(vals: list) -> float:
    n = len(vals)
    if n == 0: return 0.0
    s = sorted(vals); mid = n // 2
    return float(s[mid]) if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0

class Trader:
    LIMIT = 80

    # --- PEPPER ---
    PEPPER_WARMUP_TICKS = 1500
    PEPPER_FASTTRACK_TICKS = 700
    PEPPER_CAP_TENTATIVE = 25 

    # --- OSMIUM ---
    OSMIUM_ANCHOR = 10_000
    OSMIUM_QUOTE_SIZE = 35 # High-throughput push
    OSMIUM_SKEW_SOFT = 22
    OSMIUM_SKEW_HARD = 45
    OSMIUM_TAKE_EDGE = 1
    OSMIUM_TAKE_EDGE_UNSAFE = 2

    # --- Meta ---
    MAF_BID_FRACTION = 0.40

    def __init__(self):
        self.history: Dict[str, Any] = {}
        self.tick: int = 0

    def _load_state(self, state: TradingState):
        if getattr(state, "traderData", None) and state.traderData != "":
            try: self.history = json.loads(state.traderData)
            except: self.history = {}
        self.tick = self.history.get("tick", 0) + 1
        self.history["tick"] = self.tick

    def _save_state(self) -> str:
        for k in ["pp", "op", "m_p", "m_o"]:
            if k in self.history and len(self.history[k]) > 100:
                self.history[k] = self.history[k][-60:]
        return json.dumps(self.history)

    def _pepper_logic(self, state: TradingState) -> Tuple[List[Order], float]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths: return [], 0.0
        depth = state.order_depths[product]; pos = state.position.get(product, 0)
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None: return [], 0.0
        mid = (bb + ba) / 2.0; ts = state.timestamp
        hist = self.history.get("pp", []); hist.append(mid); self.history["pp"] = hist
        start_samples = self.history.get("pp_start_samples", [])
        if len(start_samples) < 15: start_samples.append(mid); self.history["pp_start_samples"] = start_samples
        if "pp_start_ts" not in self.history: self.history["pp_start_ts"] = ts
        
        start_ts = self.history["pp_start_ts"]; cap = self.history.get("pp_cap")
        if cap is None and (ts - start_ts) >= self.PEPPER_FASTTRACK_TICKS and len(start_samples) >= 10:
            slope = (mid - _median(start_samples)) / max(1, ts - start_ts) * 100.0
            if slope >= 0.08: cap = 80; self.history["pp_cap"] = cap

        if cap is None and (ts - start_ts) >= self.PEPPER_WARMUP_TICKS and len(start_samples) >= 15:
            slope = (mid - _median(start_samples)) / max(1, ts - start_ts) * 100.0
            cap = 80 if slope > 0.05 else (60 if slope > 0.02 else 40)
            self.history["pp_cap"] = cap

        eff_cap = cap if cap is not None else self.PEPPER_CAP_TENTATIVE
        orders = []; edge_sum = 0.0; edge_qty = 0
        if eff_cap > pos:
            take = min(eff_cap - pos, 15)
            for ask in sorted(depth.sell_orders.keys()):
                if take <= 0 or ask > mid + 1: break
                qty = min(take, -depth.sell_orders[ask])
                orders.append(Order(product, ask, qty)); edge_sum += abs(ask - mid) * qty; edge_qty += qty
                take -= qty; pos += qty
            if eff_cap > pos: orders.append(Order(product, bb + 1, min(eff_cap - pos, 30)))
        elif eff_cap < pos:
            take = min(pos - eff_cap, 15)
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if take <= 0 or bid < mid - 1: break
                qty = min(take, depth.buy_orders[bid])
                orders.append(Order(product, bid, -qty)); edge_sum += abs(bid - mid) * qty; edge_qty += qty
                take -= qty; pos -= qty
            if eff_cap < pos: orders.append(Order(product, ba - 1, -min(pos - eff_cap, 30)))
            
        return orders, (edge_sum / edge_qty if edge_qty > 0 else 0.0)

    def _osmium_logic(self, state: TradingState) -> Tuple[List[Order], float]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths: return [], 0.0
        depth = state.order_depths[product]; pos = state.position.get(product, 0)
        depth_b = list(depth.buy_orders.keys()); depth_a = list(depth.sell_orders.keys())
        if not depth_b or not depth_a: return [], 0.0
        bb = max(depth_b); ba = min(depth_a); mid = (bb + ba) / 2.0
        
        hist = self.history.get("op", []); hist.append(mid); self.history["op"] = hist
        drift = abs(sum(hist[-20:]) / 20.0 - 10000) > 12 if len(hist) >= 20 else False
        
        scale = 0.6 if drift else 1.0; orders = []; rem_buy = 80 - pos; rem_sell = 80 + pos
        edge_sum = 0.0; edge_qty = 0; take_e = self.OSMIUM_TAKE_EDGE_UNSAFE if drift else self.OSMIUM_TAKE_EDGE
        
        for ask in sorted(depth.sell_orders.keys()):
            if ask <= 10000 - take_e and rem_buy > 0:
                qty = min(rem_buy, -depth.sell_orders[ask])
                orders.append(Order(product, ask, qty)); edge_sum += abs(ask - mid) * qty; edge_qty += qty
                rem_buy -= qty; pos += qty
        for bid in sorted(depth.buy_orders.keys(), reverse=True):
            if bid >= 10000 + take_e and rem_sell > 0:
                qty = min(rem_sell, depth.buy_orders[bid])
                orders.append(Order(product, bid, -qty)); edge_sum += abs(bid - mid) * qty; edge_qty += qty
                rem_sell -= qty; pos -= qty

        skew = 2 if abs(pos) > 45 else (1 if abs(pos) > 22 else 0)
        skew_dir = 1 if pos > 0 else -1
        bp = max(int(min(bb + 1, 9999) - skew * skew_dir), 10000 - 4)
        ap = min(int(max(ba - 1, 10001) - skew * skew_dir), 10000 + 4)
        if bp >= ap: bp = 9999; ap = 10001
        
        if rem_buy > 0: orders.append(Order(product, bp, min(rem_buy, int(self.OSMIUM_QUOTE_SIZE * scale))))
        if rem_sell > 0: orders.append(Order(product, ap, -min(rem_sell, int(self.OSMIUM_QUOTE_SIZE * scale))))
        return orders, (edge_sum / edge_qty if edge_qty > 0 else 0.0)

    def run(self, state: TradingState):
        self._load_state(state)
        res = {}
        p_ord, p_e = self._pepper_logic(state); o_ord, o_e = self._osmium_logic(state)
        res["INTARIAN_PEPPER_ROOT"] = p_ord; res["ASH_COATED_OSMIUM"] = o_ord
        
        if p_e > 0:
            h = self.history.get("m_p", []); h.append(p_e); self.history["m_p"] = h[-40:]
        if o_e > 0:
            h = self.history.get("m_o", []); h.append(o_e); self.history["m_o"] = h[-40:]

        ev = (np.mean(self.history.get("m_p", [0])) + np.mean(self.history.get("m_o", [0]))) * 20
        maf_bid = int(ev * self.MAF_BID_FRACTION)
        return res, maf_bid, self._save_state()
