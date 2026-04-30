import json
import math
from collections import defaultdict
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

# ANSWER1_1.PY: Merged Group-Ratio Alpha + Top-Execution (Take)
# Strategy: 
#   1. Anchor fair value to the family group price (from answer4).
#   2. "Take in others": Execute aggressively when fair crosses the spread.
#   3. Family-level caps and stable product focus (from Tier 1 docs).

SYM_LIMIT = 10
RATIO_ALPHA = 0.01
INV_SKEW = 0.25

# Stability focus but allowing all family members to participate if they have signal
FAMILY_MEMBERS = {
    "PEBBLES":      ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"],
    "MICROCHIP":    ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
                     "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE"],
    "TRANSLATOR":   ["TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
                     "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
                     "TRANSLATOR_VOID_BLUE"],
    "ROBOT":        ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
                     "ROBOT_LAUNDRY", "ROBOT_IRONING"],
    "PANEL":        ["PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"],
}

# Family caps from volatility.md
FAMILY_LIMITS = {
    "ROBOT":      25,
    "TRANSLATOR": 25,
    "PANEL":      15,
}

MEMBER_TO_FAM = {}
for fam, members in FAMILY_MEMBERS.items():
    for m in members: MEMBER_TO_FAM[m] = fam

class Trader:
    def _load(self, td: str) -> Dict:
        if not td: return self._empty()
        try:
            mem = json.loads(td)
            if "r" not in mem: return self._empty()
            return mem
        except: return self._empty()

    def _empty(self) -> Dict:
        return {"r": {}, "ts": -1}

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders: return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["ts"] >= 0 and state.timestamp < mem["ts"]: mem = self._empty()
        mem["ts"] = state.timestamp
        
        mids = {}
        bbas = {}
        for sym in state.order_depths:
            bid, ask = self._bba(state, sym)
            if bid is not None: 
                mids[sym] = (bid + ask) / 2.0
                bbas[sym] = (bid, ask)

        gm_now = {}
        for fam, members in FAMILY_MEMBERS.items():
            vals = [mids[m] for m in members if m in mids]
            if vals: gm_now[fam] = sum(vals) / len(vals)

        # Family tracking for caps
        fam_pos = defaultdict(int)
        for s, p in state.position.items():
            fam_pos[MEMBER_TO_FAM.get(s, s)] += abs(p)

        result: Dict[str, List[Order]] = defaultdict(list)

        for sym, mid in mids.items():
            fam = MEMBER_TO_FAM.get(sym)
            if not fam or fam not in gm_now: continue

            g_now = gm_now[fam]
            
            # Ratio update
            ratio = mem["r"].get(sym, mid / g_now if g_now > 0 else 1.0)
            ratio = (1 - RATIO_ALPHA) * ratio + RATIO_ALPHA * (mid / g_now if g_now > 0 else ratio)
            mem["r"][sym] = ratio

            pos = state.position.get(sym, 0)
            bid, ask = bbas[sym]

            # Fair price calculation with inventory skew
            fair = (g_now * ratio) - (INV_SKEW * pos)
            
            # "Take in others": Top Execution logic
            # This crosses the spread (takes liquidity) when signal is strong
            mm_bid = int(math.floor(fair - 0.1))
            mm_ask = int(math.ceil(fair + 0.1))
            
            # Valid spread check
            if mm_bid >= mm_ask:
                mm_bid = mm_ask - 1

            fam_limit = FAMILY_LIMITS.get(fam, 999)
            fam_room = max(0, fam_limit - fam_pos[fam])
            
            if fam_room > 0:
                if pos < SYM_LIMIT:
                    result[sym].append(Order(sym, mm_bid, min(fam_room, SYM_LIMIT - pos)))
                if pos > -SYM_LIMIT:
                    result[sym].append(Order(sym, mm_ask, -min(fam_room, SYM_LIMIT + pos)))

        return dict(result), 0, self._save(mem)
