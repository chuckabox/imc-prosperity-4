"""SafeGuard.py - Refined version of kingking.py
Restores the profitable 'holding' core of kingking while adding a 
dynamic entry buffer to reduce drawdown depth.
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

# Balanced Limits: Slightly lower than kingking's 25/25/15 to reduce dip depth.
FAMILY_LIMITS = {
    "ROBOT":      22,
    "TRANSLATOR": 22,
    "PANEL":      14,
}

# ----- MM knobs -----
MM_EDGE       = 1     # Base edge
MM_CLIP       = 2     
MM_SPREAD_MIN = 3     
MM_SPREAD_MAX = 10    # Reverted to kingking
INV_SKEW      = 0.25  # Reverted to kingking (prevents churning)
INV_HARD_FRAC = 0.80  # Reverted to kingking


def _family(sym: str) -> str:
    for p in FAMILY_PREFIXES:
        if sym.startswith(p + "_"):
            return p
    return sym.split("_", 1)[0]


class Trader:
    def _load(self, td: str) -> Dict:
        if not td:
            return {"last_ts": -1}
        try:
            mem = json.loads(td)
            mem.setdefault("last_ts", -1)
            return mem
        except Exception:
            return {"last_ts": -1}

    def _save(self, mem: Dict) -> str:
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
        mem["last_ts"] = state.timestamp

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
            pos = state.position.get(sym, 0)
            
            fam = _family(sym)
            fam_lim = FAMILY_LIMITS.get(fam, SYM_LIMIT * 2)
            fam_used = self._family_pos(fam, state.position)
            fam_room = max(0, fam_lim - fam_used)
            
            # Kingking logic: if family is full, STOP quoting to prevent churning at realized losses.
            # This allows the trader to 'hold' through the dip and wait for mean reversion recovery.
            if fam_room <= 0:
                continue

            # Inventory-skewed fair price.
            fair = mid - INV_SKEW * pos
            
            # Dynamic Entry Buffer: If we are near the family limit, 
            # increase the required edge for entries to slow down loading.
            # Entry on bid side means we are increasing pos (pos >= 0) or closing short (pos < 0).
            # We only increase edge for true entries (increasing pos).
            bid_edge = 2 if fam_room < 5 and pos >= 0 else MM_EDGE
            ask_edge = 2 if fam_room < 5 and pos <= 0 else MM_EDGE
            
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
