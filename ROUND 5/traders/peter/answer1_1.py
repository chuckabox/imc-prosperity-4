import json
import math
from collections import defaultdict
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

# ANSWER1.1.PY: Stability-First Hybrid Strategy
# Improvements based on: ROUND 5/docs/volatility.md and ken_round5_findings_and_alphas.md
# Alphas:
#   1. Tier 1 (Stability): Passive MM on Whitelisted symbols (ROBOT, TRANSLATOR, PANEL).
#   2. Tier 3 (Opportunity): Shock Fade on High-Vol symbols (PEBBLES_XL, MICROCHIP_SQUARE).
#   3. Family-Level Risk Management (Caps).

SYM_LIMIT = 10
INV_SKEW = 0.25 # Aggressive skew from kingking.py
MM_EDGE = 1

# Whitelist from volatility.md Tier 1
STABLE_WHITELIST = [
    "ROBOT_DISHES", "ROBOT_IRONING", "ROBOT_VACUUMING", "ROBOT_LAUNDRY", "ROBOT_MOPPING",
    "TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
    "TRANSLATOR_SPACE_GRAY", "TRANSLATOR_VOID_BLUE",
    "PANEL_2X2", "PANEL_2X4", "PANEL_4X4"
]

# Shock Fade from ken's findings
SHOCK_WHITELIST = ["PEBBLES_XL", "MICROCHIP_SQUARE"]
SHOCK_TRIGGER = 8.0 # Ken's robust winner threshold
SHOCK_CLIP = 10     # Full leverage on shocks

# Family caps from volatility.md
FAMILY_LIMITS = {
    "ROBOT":      25,
    "TRANSLATOR": 25,
    "PANEL":      15,
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

    def _bba(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders: return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def _get_family(self, sym: str) -> str:
        return sym.split("_")[0]

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]: mem = self._empty()
        mem["last_ts"] = state.timestamp
        
        result: Dict[str, List[Order]] = defaultdict(list)
        
        # 1. SHOCK FADE LAYER (Tier 3)
        for sym in SHOCK_WHITELIST:
            if sym not in state.order_depths: continue
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None: continue
            
            mid = (bid + ask) / 2.0
            pos = state.position.get(sym, 0)
            
            # Exit logic: 1-tick hold
            ent_ts = mem["entries"].get(sym, -1)
            if pos != 0 and (ent_ts < 0 or state.timestamp > ent_ts):
                if pos > 0: result[sym].append(Order(sym, bid, -pos))
                else: result[sym].append(Order(sym, ask, -pos))
                mem["entries"].pop(sym, None)
                continue
            
            # Entry logic: Shock detection
            prev_mid = mem["last_mid"].get(sym, mid)
            dmid = mid - prev_mid
            mem["last_mid"][sym] = mid
            
            if pos == 0 and abs(dmid) >= SHOCK_TRIGGER:
                if dmid >= SHOCK_TRIGGER: # Spike -> Sell
                    result[sym].append(Order(sym, bid, -SHOCK_CLIP))
                else: # Drop -> Buy
                    result[sym].append(Order(sym, ask, SHOCK_CLIP))
                mem["entries"][sym] = state.timestamp

        # 2. PASSIVE MM LAYER (Tier 1)
        # Calculate current family positions for caps
        fam_pos = defaultdict(int)
        for s, p in state.position.items():
            fam_pos[self._get_family(s)] += abs(p)

        for sym in STABLE_WHITELIST:
            if sym not in state.order_depths: continue
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None: continue
            
            mid = (bid + ask) / 2.0
            pos = state.position.get(sym, 0)
            
            fam = self._get_family(sym)
            fam_limit = FAMILY_LIMITS.get(fam, 999)
            fam_room = max(0, fam_limit - fam_pos[fam])
            
            # Fair price calculation with inventory skew
            fair = mid - (INV_SKEW * pos)
            
            # Quote 1 tick inside spread (Maker)
            mm_bid = min(int(round(fair - MM_EDGE)), ask - 1)
            mm_ask = max(int(round(fair + MM_EDGE)), bid + 1)
            
            if fam_room > 0:
                if pos < SYM_LIMIT:
                    result[sym].append(Order(sym, mm_bid, min(fam_room, SYM_LIMIT - pos)))
                if pos > -SYM_LIMIT:
                    result[sym].append(Order(sym, mm_ask, -min(fam_room, SYM_LIMIT + pos)))

        return dict(result), 0, self._save(mem)
