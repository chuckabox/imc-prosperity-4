import json
from collections import defaultdict
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

# CLOWN V2: Sid's High-Trigger Logic + Spread Awareness
POS_LIMIT = 10
TAKE_CLIP = 5

# Optimized targets: Trigger must be > spread.
# Edge = Trigger - Spread. Aim for Edge > 5.
PARAMS = {
    "MICROCHIP_RECTANGLE": {"trigger": 18, "max_spread": 8},  # Edge 10
    "MICROCHIP_TRIANGLE":  {"trigger": 20, "max_spread": 10}, # Edge 10
    "PEBBLES_S":           {"trigger": 22, "max_spread": 12}, # Edge 10
    "PEBBLES_M":           {"trigger": 22, "max_spread": 12},
    "PEBBLES_L":           {"trigger": 22, "max_spread": 12},
    "ROBOT_DISHES":        {"trigger": 15, "max_spread": 7},  # Edge 8
    "PEBBLES_XL":          {"trigger": 35, "max_spread": 18}, # Edge 17
}

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
            "last_mid": {},
            "entries": {}, # sym -> ts
        }

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _best_bid_ask(self, state: TradingState, sym: str) -> Tuple[int, int]:
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders: return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]: mem = self._empty()
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        for sym, cfg in PARAMS.items():
            if sym not in state.order_depths: continue
            
            bid, ask = self._best_bid_ask(state, sym)
            if bid is None or ask is None: continue
            
            mid = (bid + ask) / 2.0
            pos = state.position.get(sym, 0)
            
            # --- EXIT: 1-tick hold ---
            ent_ts = mem["entries"].get(sym, -1)
            if pos != 0 and (ent_ts < 0 or state.timestamp > ent_ts):
                if pos > 0: result[sym].append(Order(sym, bid, -pos))
                else: result[sym].append(Order(sym, ask, -pos))
                mem["entries"].pop(sym, None)
                continue

            # --- ENTRY: High-Reversion Shock ---
            last_mid = mem["last_mid"].get(sym, mid)
            d_mid = mid - last_mid
            mem["last_mid"][sym] = mid

            if pos == 0 and abs(d_mid) >= cfg["trigger"] and (ask - bid) <= cfg["max_spread"]:
                # Fade the move (Taker)
                qty = min(TAKE_CLIP, POS_LIMIT)
                if d_mid >= cfg["trigger"]: # Spike -> Sell
                    result[sym].append(Order(sym, bid, -qty))
                else: # Drop -> Buy
                    result[sym].append(Order(sym, ask, qty))
                mem["entries"][sym] = state.timestamp

        return dict(result), 0, self._save(mem)
