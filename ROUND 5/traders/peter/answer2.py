import json
import math
from collections import defaultdict
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

# ANSWER2.PY: Multi-Pair Passive MM with Trend-Adaptive Skew
LIMIT = 10
MM_CLIP = 10
INV_SKEW_BASE = 0.20
LL_LOOKBACK = 100

# Groupings for pair-skewing
PAIRS = [
    ("GALAXY_SOUNDS_BLACK_HOLES", "SLEEP_POD_POLYESTER", 1.0),   # LL request
    ("TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_GRAPHITE_MIST", 0.8), # Clean pair
    ("PANEL_2X2", "PANEL_2X4", 0.9),                             # Clean pair
    ("ROBOT_DISHES", "ROBOT_MOPPING", -1.0),                     # Anti-pair
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
            "mids": {}, # sym -> list (rolling history)
        }

    def _save(self, mem: Dict) -> str:
        for sym in mem["mids"]:
            mem["mids"][sym] = mem["mids"][sym][-LL_LOOKBACK:]
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders: return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

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
            bid, ask = self._best_bid_ask(state, sym)
            if bid and ask:
                if sym not in mem["mids"]: mem["mids"][sym] = []
                mem["mids"][sym].append((bid + ask) / 2.0)

        alpha_skew = defaultdict(float)
        for s1, s2, w in PAIRS:
            if s1 in mem["mids"] and len(mem["mids"][s1]) >= 10:
                h1 = mem["mids"][s1]
                move = h1[-1] - h1[-10] # 10 tick lead
                alpha_skew[s2] += move * w * 0.2

        # 2. Universal MM with Adaptive Skew
        for sym in state.order_depths.keys():
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None: continue
            
            mid = (bid + ask) / 2.0
            pos = state.position.get(sym, 0)
            
            # Vol-aware skew (Pebbles/Chips get more)
            skew_mult = 1.0
            if "PEBBLES" in sym: skew_mult = 1.5
            if "MICROCHIP" in sym: skew_mult = 1.2
            if "ROBOT" in sym: skew_mult = 0.8
            
            fair = mid - (INV_SKEW_BASE * skew_mult * pos) + alpha_skew[sym]
            
            # Spread-aware quoting
            spread = ask - bid
            if spread < 1: continue
            
            # Maker orders
            # If we are heavily long (pos > 5), we push ask lower to exit faster
            mm_bid = min(int(round(fair - 1)), ask - 1)
            mm_ask = max(int(round(fair + 1)), bid + 1)
            
            # Limit quoting to avoid hitting our own walls
            if pos < LIMIT:
                result[sym].append(Order(sym, mm_bid, LIMIT - pos))
            if pos > -LIMIT:
                result[sym].append(Order(sym, mm_ask, -(LIMIT + pos)))

        return dict(result), 0, self._save(mem)

    def _best_bid_ask(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders: return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())
