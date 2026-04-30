import json
import math
from collections import defaultdict
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

# ANSWER3.PY: OBI-Aware, Multi-Pair, Family-Skewed Passive MM
LIMIT = 10
INV_SKEW_BASE = 0.20
OBI_SKEW = 0.5 # Skew fair price by this based on book imbalance
LL_LOOKBACK = 100

# High-conviction pairs for leader-lag
PAIRS = [
    ("GALAXY_SOUNDS_BLACK_HOLES", "SLEEP_POD_POLYESTER", 1.0),
    ("TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_GRAPHITE_MIST", 0.8),
    ("PANEL_2X2", "PANEL_2X4", 0.9),
    ("ROBOT_DISHES", "ROBOT_MOPPING", -1.0),
]

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
            "mids": {}, # rolling history
        }

    def _save(self, mem: Dict) -> str:
        for sym in mem["mids"]:
            mem["mids"][sym] = mem["mids"][sym][-LL_LOOKBACK:]
        return json.dumps(mem, separators=(",", ":"))

    def _bba_with_vols(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders: return None, None, 0, 0
        best_bid = max(d.buy_orders.keys())
        best_ask = min(d.sell_orders.keys())
        bid_vol = sum(d.buy_orders.values())
        ask_vol = sum(d.sell_orders.values())
        return best_bid, best_ask, bid_vol, ask_vol

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]: mem = self._empty()
        mem["last_ts"] = state.timestamp
        
        result: Dict[str, List[Order]] = defaultdict(list)
        
        # 1. Update histories and compute pair alpha
        all_tracked = set()
        for s1, s2, w in PAIRS:
            all_tracked.add(s1)
            all_tracked.add(s2)
        
        for sym in all_tracked:
            bid, ask, _, _ = self._bba_with_vols(state, sym)
            if bid and ask:
                if sym not in mem["mids"]: mem["mids"][sym] = []
                mem["mids"][sym].append((bid + ask) / 2.0)

        pair_skew = defaultdict(float)
        for s1, s2, w in PAIRS:
            if s1 in mem["mids"] and len(mem["mids"][s1]) >= 10:
                h1 = mem["mids"][s1]
                move = h1[-1] - h1[-10]
                pair_skew[s2] += move * w * 0.25

        # 2. Universal MM with OBI + Pair Skew
        for sym in state.order_depths.keys():
            bid, ask, bvol, avol = self._bba_with_vols(state, sym)
            if bid is None or ask is None: continue
            
            mid = (bid + ask) / 2.0
            pos = state.position.get(sym, 0)
            
            # Order Book Imbalance (OBI)
            # Higher bvol relative to avol => price likely moves UP
            total_vol = bvol + avol
            obi = (bvol - avol) / total_vol if total_vol > 0 else 0
            
            # Vol-aware multiplier
            skew_mult = 1.0
            if "PEBBLES" in sym: skew_mult = 1.6
            elif "MICROCHIP" in sym: skew_mult = 1.3
            elif "ROBOT" in sym: skew_mult = 0.7
            
            fair = mid - (INV_SKEW_BASE * skew_mult * pos) + pair_skew[sym] + (obi * OBI_SKEW)
            
            # Quote inside or at BBA
            mm_bid = min(int(round(fair - 1)), ask - 1)
            mm_ask = max(int(round(fair + 1)), bid + 1)
            
            if pos < LIMIT:
                # Use smaller clip for volatile items to avoid getting steamrolled
                clip = LIMIT - pos
                if "PEBBLES" in sym: clip = min(clip, 5)
                result[sym].append(Order(sym, mm_bid, clip))
                
            if pos > -LIMIT:
                clip = LIMIT + pos
                if "PEBBLES" in sym: clip = min(clip, 5)
                result[sym].append(Order(sym, mm_ask, -clip))

        return dict(result), 0, self._save(mem)
