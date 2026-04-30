import json
import numpy as np
from collections import defaultdict
from typing import Dict, List
from datamodel import Order, TradingState

LIMIT = 10
MM_CLIP = 5
INV_SKEW = 0.35 
LEADER = "GALAXY_SOUNDS_BLACK_HOLES"
LAG = "SLEEP_POD_POLYESTER"
LL_LOOKBACK = 100
MOMENTUM_WINDOW = 10 

# --- NEW SAFETY PARAMETERS ---
MUTE_THRESHOLD = 1.5  # If the alpha signal is stronger than this, stop quoting the wrong way
EDGE_WIDEN = 0.25     # Widen spread per unit of inventory

class Trader:
    def _load(self, td: str) -> Dict:
        if not td: return self._empty()
        try:
            mem = json.loads(td)
            for k, v in self._empty().items(): mem.setdefault(k, v)
            return mem
        except: return self._empty()

    def _empty(self) -> Dict:
        return {
            "last_ts": -1,
            "bh_hist": [],
            "poly_hist": [],
        }

    def _save(self, mem: Dict) -> str:
        mem["bh_hist"] = mem["bh_hist"][-LL_LOOKBACK:]
        mem["poly_hist"] = mem["poly_hist"][-LL_LOOKBACK:]
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders: return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def _get_corr_sign(self, x: List[float], y: List[float]) -> float:
        if len(x) < 50 or len(y) < 50: return 1.0
        cov_matrix = np.cov(x, y)
        return 1.0 if cov_matrix[0, 1] >= 0 else -1.0

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]: mem = self._empty()
        mem["last_ts"] = state.timestamp
        
        result: Dict[str, List[Order]] = defaultdict(list)
        
        bh_bid, bh_ask = self._bba(state, LEADER)
        poly_bid, poly_ask = self._bba(state, LAG)
        
        if bh_bid and bh_ask: mem["bh_hist"].append((bh_bid + bh_ask) / 2.0)
        if poly_bid and poly_ask: mem["poly_hist"].append((poly_bid + poly_ask) / 2.0)
        
        ll_skew = 0.0
        if len(mem["bh_hist"]) >= LL_LOOKBACK:
            move = mem["bh_hist"][-1] - mem["bh_hist"][-MOMENTUM_WINDOW]
            sign = self._get_corr_sign(mem["bh_hist"], mem["poly_hist"])
            ll_skew = move * sign * 0.15 

        for sym in state.order_depths.keys():
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None: continue
            
            mid = (bid + ask) / 2.0
            pos = state.position.get(sym, 0)
            
            fair = mid - (INV_SKEW * pos)
            if sym == LAG:
                fair += ll_skew
                
            # OPTIMIZATION 1: Asymmetric Spread Widening
            # If we are holding long inventory, require a much lower bid to buy more.
            bid_edge = 1 + max(0, pos * EDGE_WIDEN)
            ask_edge = 1 + max(0, -pos * EDGE_WIDEN)
                
            mm_bid = min(int(round(fair - bid_edge)), ask - 1)
            mm_ask = max(int(round(fair + ask_edge)), bid + 1)
            
            # OPTIMIZATION 2: Alpha-Driven Quote Muting (The Killswitch)
            # If the alpha signal predicts a massive drop, DO NOT BUY.
            mute_bids = (sym == LAG and ll_skew < -MUTE_THRESHOLD)
            # If the alpha signal predicts a massive spike, DO NOT SELL.
            mute_asks = (sym == LAG and ll_skew > MUTE_THRESHOLD)
            
            # OPTIMIZATION 3: Inventory Hard-Stops
            # Stop quoting entirely when at LIMIT - 1 to avoid getting toxic flow at the extremes
            can_bid = pos < (LIMIT - 1) and not mute_bids
            can_ask = pos > -(LIMIT - 1) and not mute_asks

            if can_bid:
                result[sym].append(Order(sym, mm_bid, min(MM_CLIP, LIMIT - pos)))
            if can_ask:
                result[sym].append(Order(sym, mm_ask, -min(MM_CLIP, LIMIT + pos)))

        return dict(result), 0, self._save(mem)