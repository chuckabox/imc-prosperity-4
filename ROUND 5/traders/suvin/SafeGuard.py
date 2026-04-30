"""SafeGuard.py - v3 (High Protection)
Minimizes drawdown via a multi-stage pressure system:
1. Multi-Stage Skew: 0.25 -> 0.40 -> 0.60 as family room shrinks.
2. Multi-Stage Edge: Entry edge 1 -> 2 -> 3 as family room shrinks.
3. Shock Filter: Skips quoting if mid-price shocks > max(10, 1.5*spread).
4. Tighter Limits: 16/16/10 family caps.
"""

import json
from collections import defaultdict
from typing import Dict, List

from datamodel import Order, TradingState


FAMILY_PREFIXES = [
    "PEBBLES", "SNACKPACK", "UV_VISOR", "GALAXY_SOUNDS", "MICROCHIP",
    "TRANSLATOR", "SLEEP_POD", "OXYGEN_SHAKE", "PANEL", "ROBOT",
]

# Algo.md: position limit = 10 per product. Hard cap.
SYM_LIMIT = 10

WHITELIST = (
    # ROBOT - cheapest spreads, top signal quality.
    "ROBOT_DISHES",
    "ROBOT_IRONING",
    "ROBOT_VACUUMING",
    "ROBOT_LAUNDRY",
    "ROBOT_MOPPING",
    # TRANSLATOR - all pairs tight_rate=1.0.
    "TRANSLATOR_ASTRO_BLACK",
    "TRANSLATOR_ECLIPSE_CHARCOAL",
    "TRANSLATOR_GRAPHITE_MIST",
    "TRANSLATOR_SPACE_GRAY",
    "TRANSLATOR_VOID_BLUE",
    # PANEL - skip 1X4 (anti-pair leg).
    "PANEL_2X2",
    "PANEL_2X4",
    "PANEL_4X4",
)

# High Protection Limits: Significantly lower to ensure small dip magnitude.
FAMILY_LIMITS = {
    "ROBOT":      16,
    "TRANSLATOR": 16,
    "PANEL":      10,
}

# ----- MM knobs -----
MM_EDGE       = 1     
MM_CLIP       = 2     
MM_SPREAD_MIN = 3     
MM_SPREAD_MAX = 10    
INV_SKEW_BASE = 0.25  
INV_HARD_FRAC = 0.70  


def _family(sym: str) -> str:
    for p in FAMILY_PREFIXES:
        if sym.startswith(p + "_"):
            return p
    return sym.split("_", 1)[0]


class Trader:
    def _load(self, td: str) -> Dict:
        if not td:
            return {"last_ts": -1, "mids": {}}
        try:
            mem = json.loads(td)
            mem.setdefault("last_ts", -1)
            mem.setdefault("mids", {})
            return mem
        except Exception:
            return {"last_ts": -1, "mids": {}}

    def _save(self, mem: Dict) -> str:
        # Keep traderData slim
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders:
            return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def _family_pos(self, fam: str, position: Dict[str, int]) -> int:
        return sum(abs(p) for s, p in position.items() if _family(s) == fam)

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem = {"last_ts": -1, "mids": {}}
        mem["last_ts"] = state.timestamp
        last_mids = mem["mids"]

        result: Dict[str, List[Order]] = defaultdict(list)

        for sym in WHITELIST:
            if sym not in state.order_depths:
                continue
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None:
                continue
            spread = ask - bid
            if spread < MM_SPREAD_MIN or spread > MM_SPREAD_MAX:
                continue

            mid = 0.5 * (bid + ask)
            
            # --- Shock Filter ---
            prev_mid = last_mids.get(sym, mid)
            last_mids[sym] = mid
            if abs(mid - prev_mid) > max(10, 1.5 * spread):
                continue

            pos = state.position.get(sym, 0)
            fam = _family(sym)
            fam_lim = FAMILY_LIMITS.get(fam, SYM_LIMIT * 2)
            fam_used = self._family_pos(fam, state.position)
            fam_room = max(0, fam_lim - fam_used)
            
            # Kingking logic: if family is full, STOP quoting to prevent churning.
            if fam_room <= 0:
                continue

            # --- Multi-Stage Pressure System ---
            skew = INV_SKEW_BASE
            if fam_room < 3: skew = 0.60
            elif fam_room < 6: skew = 0.40
            
            fair = mid - skew * pos
            
            # Entry/Exit edges
            bid_edge = MM_EDGE
            ask_edge = MM_EDGE
            
            # Increase edge for entries as family fills up
            if fam_room < 3:
                if pos >= 0: bid_edge = 3
                if pos <= 0: ask_edge = 3
            elif fam_room < 6:
                if pos >= 0: bid_edge = 2
                if pos <= 0: ask_edge = 2

            mm_bid_px = int(round(fair - bid_edge))
            mm_ask_px = int(round(fair + ask_edge))

            # Never cross live top-of-book.
            mm_bid_px = min(mm_bid_px, ask - 1)
            mm_ask_px = max(mm_ask_px, bid + 1)
            if mm_bid_px >= mm_ask_px:
                mm_ask_px = mm_bid_px + 1

            # Position-near-limit: only quote the reducing side.
            pos_frac = abs(pos) / SYM_LIMIT
            quote_buy  = pos_frac < INV_HARD_FRAC or pos < 0
            quote_sell = pos_frac < INV_HARD_FRAC or pos > 0

            buy_cap = max(0, SYM_LIMIT - pos)
            sell_cap = max(0, SYM_LIMIT + pos)

            if quote_buy and buy_cap > 0:
                bq = min(MM_CLIP, buy_cap, fam_room)
                if bq > 0:
                    result[sym].append(Order(sym, mm_bid_px, bq))
            if quote_sell and sell_cap > 0:
                aq = min(MM_CLIP, sell_cap, fam_room)
                if aq > 0:
                    result[sym].append(Order(sym, mm_ask_px, -aq))

        return dict(result), 0, self._save(mem)
