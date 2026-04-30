import json
from collections import defaultdict
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

# WHITELIST (Final 13 stable symbols)
# Strictly respect position limit = 10 (Round 5 constraint).
WHITELIST: Dict[str, int] = {
    "ROBOT_DISHES":               10,
    "ROBOT_IRONING":              10,
    "ROBOT_VACUUMING":            10,
    "ROBOT_LAUNDRY":              10,
    "ROBOT_MOPPING":              10,
    "TRANSLATOR_ASTRO_BLACK":     10,
    "TRANSLATOR_ECLIPSE_CHARCOAL":10,
    "TRANSLATOR_GRAPHITE_MIST":   10,
    "TRANSLATOR_SPACE_GRAY":      10,
    "TRANSLATOR_VOID_BLUE":       10,
    "PANEL_2X2":                  10,
    "PANEL_2X4":                  10,
    "PANEL_4X4":                  10,
}

FAMILY_LIMITS = {
    "ROBOT":      25,
    "TRANSLATOR": 25,
    "PANEL":      15,
}

# --- Knobs ---
MM_EDGE       = 1
MM_CLIP       = 2
MM_SPREAD_MIN = 3
MM_SPREAD_MAX = 10
INV_SKEW      = 0.20
SHOCK_TRIGGER = 8.5   # Move threshold for aggressive fade
SHOCK_CLIP    = 4     # Size for shock fade

def get_family(symbol: str) -> str:
    if symbol.startswith("ROBOT_"): return "ROBOT"
    if symbol.startswith("TRANSLATOR_"): return "TRANSLATOR"
    if symbol.startswith("PANEL_"): return "PANEL"
    return symbol

class Trader:
    def _load(self, td: str) -> Dict:
        if not td: return {"last_ts": -1, "last_mid": {}}
        try:
            mem = json.loads(td)
            mem.setdefault("last_ts", -1)
            mem.setdefault("last_mid", {})
            return mem
        except:
            return {"last_ts": -1, "last_mid": {}}

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str):
        depth = state.order_depths.get(sym)
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def _family_pos(self, fam: str, position: Dict[str, int]) -> int:
        return sum(abs(p) for s, p in position.items() if get_family(s) == fam)

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["last_mid"] = {}
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        for sym, sym_lim in WHITELIST.items():
            if sym not in state.order_depths: continue
            
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None: continue
            
            mid = (bid + ask) / 2.0
            last_mid = mem["last_mid"].get(sym, mid)
            d_mid = mid - last_mid
            mem["last_mid"][sym] = mid

            pos = state.position.get(sym, 0)
            fam = get_family(sym)
            fam_lim = FAMILY_LIMITS.get(fam, 999)
            fam_used = self._family_pos(fam, state.position)
            fam_room = max(0, fam_lim - fam_used)
            
            buy_cap = max(0, sym_lim - pos)
            sell_cap = max(0, sym_lim + pos)

            # --- Strategy 1: One-Tick Shock Fade (Taker) ---
            if abs(d_mid) >= SHOCK_TRIGGER and fam_room > 0:
                if d_mid >= SHOCK_TRIGGER and sell_cap > 0:
                    q = min(SHOCK_CLIP, sell_cap, fam_room)
                    result[sym].append(Order(sym, bid, -q))
                    # Consume caps/room
                    sell_cap -= q
                    fam_room -= q
                elif d_mid <= -SHOCK_TRIGGER and buy_cap > 0:
                    q = min(SHOCK_CLIP, buy_cap, fam_room)
                    result[sym].append(Order(sym, ask, q))
                    buy_cap -= q
                    fam_room -= q

            # --- Strategy 2: Passive MM (Limit) ---
            spread = ask - bid
            if spread < MM_SPREAD_MIN or spread > MM_SPREAD_MAX: continue

            # Inventory skew fair price
            fair = mid - (INV_SKEW * pos)
            mm_bid = int(round(fair - MM_EDGE))
            mm_ask = int(round(fair + MM_EDGE))
            
            # Bound by best bid/ask
            mm_bid = min(mm_bid, ask - 1)
            mm_ask = max(mm_ask, bid + 1)
            if mm_bid >= mm_ask: mm_ask = mm_bid + 1

            if fam_room > 0:
                # Buy side
                if pos < 0 or (abs(pos) / sym_lim < 0.8):
                    bq = min(MM_CLIP, buy_cap, fam_room)
                    if bq > 0: result[sym].append(Order(sym, mm_bid, bq))
                # Sell side
                if pos > 0 or (abs(pos) / sym_lim < 0.8):
                    aq = min(MM_CLIP, sell_cap, fam_room)
                    if aq > 0: result[sym].append(Order(sym, mm_ask, -aq))

        return dict(result), 0, self._save(mem)
