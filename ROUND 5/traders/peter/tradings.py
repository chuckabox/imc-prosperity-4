import json
from collections import defaultdict
from typing import Dict, List
from datamodel import Order, TradingState

# Whitelist from ROUND 5/docs/volatility.md (Final 13-symbol stable whitelist)
# Hard constraint: limit 10 per symbol.
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

# Family caps from ROUND 5/docs/volatility.md
FAMILY_LIMITS = {
    "ROBOT":      25,
    "TRANSLATOR": 25,
    "PANEL":      15,
}

# MM knobs
MM_EDGE       = 1     # one tick inside mid
MM_CLIP       = 2     # small size to avoid adverse selection
MM_SPREAD_MIN = 3     # min spread to trade
MM_SPREAD_MAX = 10    # skip wide books
INV_SKEW      = 0.25  # fair-shift per unit position
INV_HARD_FRAC = 0.80  # cap reducing side only at 80% capacity

def get_family(symbol: str) -> str:
    if symbol.startswith("ROBOT_"): return "ROBOT"
    if symbol.startswith("TRANSLATOR_"): return "TRANSLATOR"
    if symbol.startswith("PANEL_"): return "PANEL"
    return symbol

class Trader:
    def _load(self, td: str) -> Dict:
        if not td: return {"last_ts": -1}
        try:
            mem = json.loads(td)
            mem.setdefault("last_ts", -1)
            return mem
        except:
            return {"last_ts": -1}

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
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        for sym, sym_lim in WHITELIST.items():
            if sym not in state.order_depths:
                continue
            
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None:
                continue
            
            spread = ask - bid
            if spread < MM_SPREAD_MIN or spread > MM_SPREAD_MAX:
                continue

            mid = (bid + ask) / 2
            pos = state.position.get(sym, 0)

            # Check family capacity
            fam = get_family(sym)
            fam_lim = FAMILY_LIMITS.get(fam, 999)
            fam_used = self._family_pos(fam, state.position)
            fam_room = max(0, fam_lim - fam_used)
            if fam_room <= 0 and abs(pos) < sym_lim:
                # If family full but symbol not, we only allow reducing trades.
                # Logic below handles quote sides based on pos_frac.
                pass

            buy_cap = max(0, sym_lim - pos)
            sell_cap = max(0, sym_lim + pos)

            # Skew fair based on inventory
            fair = mid - (INV_SKEW * pos)
            mm_bid_px = int(round(fair - MM_EDGE))
            mm_ask_px = int(round(fair + MM_EDGE))

            # Bound by top of book
            mm_bid_px = min(mm_bid_px, ask - 1)
            mm_ask_px = max(mm_ask_px, bid + 1)
            if mm_bid_px >= mm_ask_px:
                mm_ask_px = mm_bid_px + 1

            # Quote logic
            pos_frac = abs(pos) / sym_lim if sym_lim else 0
            
            # Reduce-only if family or symbol at limit
            can_buy = buy_cap > 0 and fam_room > 0
            can_sell = sell_cap > 0 and fam_room > 0
            
            # Hard skew if near limit
            quote_buy = can_buy and (pos_frac < INV_HARD_FRAC or pos < 0)
            quote_sell = can_sell and (pos_frac < INV_HARD_FRAC or pos > 0)

            if quote_buy:
                bq = min(MM_CLIP, buy_cap, fam_room)
                if bq > 0:
                    result[sym].append(Order(sym, mm_bid_px, bq))
            
            if quote_sell:
                aq = min(MM_CLIP, sell_cap, fam_room)
                if aq > 0:
                    result[sym].append(Order(sym, mm_ask_px, -aq))

        return dict(result), 0, self._save(mem)
