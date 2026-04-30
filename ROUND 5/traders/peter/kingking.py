"""peter/kingking.py

Stability king. Trade only Tier-1 low-vol products from
`ROUND 5/docs/volatility.md`:

  ROBOT family       (5 symbols, spreads 6-8, signal quality 0.15-0.25)
  TRANSLATOR family  (5 symbols, spreads 8-9, all pairs tight_rate=1.0)
  PANEL family       (3 symbols, spreads 8-9, ex-1X4 anti-pair)

13 symbols total. Skip Tier 2/3/4 entirely - PEBBLES/MICROCHIP/SLEEP_POD/
OXYGEN_SHAKE/SNACKPACK/UV_VISOR/GALAXY_SOUNDS. They either drift, fail to
clear cost, or rarely meet the tight-spread gate.

Hard constraint from `ROUND 5/docs/algo.md`: position limit = 10 per product.
This trader respects it strictly via SYM_LIMIT = 10.

Strategy: pure passive market making.
  - Quote 1 tick inside fair on every whitelisted symbol.
  - Inv skew aggressive (0.25) to keep position near zero.
  - Hard-side switch at |pos| >= 80% of limit.
  - No taker, no shock fade, no z-score gamble - those add variance.
  - Family caps below 5 * sym_lim because intra-family signals correlate.
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

# Cap sum-of-|pos| within family - prevents all 5 ROBOT names loading
# the same direction (their residuals correlate).
FAMILY_LIMITS = {
    "ROBOT":      25,
    "TRANSLATOR": 25,
    "PANEL":      15,
}

# ----- MM knobs -----
MM_EDGE       = 1     # one tick inside fair = frequent fills
MM_CLIP       = 2     # small clip = low adverse selection
MM_SPREAD_MIN = 3     # need room to sit inside top-of-book
MM_SPREAD_MAX = 10    # avoid widebook noise
INV_SKEW      = 0.25  # strong fair-shift per unit position
INV_HARD_FRAC = 0.80  # at |pos|/lim >= this, only quote reducing side


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
            buy_cap = max(0, SYM_LIMIT - pos)
            sell_cap = max(0, SYM_LIMIT + pos)

            fam = _family(sym)
            fam_lim = FAMILY_LIMITS.get(fam, SYM_LIMIT * 3)
            fam_used = self._family_pos(fam, state.position)
            fam_room = max(0, fam_lim - fam_used)
            if fam_room <= 0:
                continue

            # Inventory-skewed fair price.
            fair = mid - INV_SKEW * pos
            mm_bid_px = int(round(fair - MM_EDGE))
            mm_ask_px = int(round(fair + MM_EDGE))

            # Never cross live top-of-book.
            mm_bid_px = min(mm_bid_px, ask - 1)
            mm_ask_px = max(mm_ask_px, bid + 1)
            if mm_bid_px >= mm_ask_px:
                mm_ask_px = mm_bid_px + 1

            # Position-near-limit: only quote the reducing side.
            pos_frac = abs(pos) / SYM_LIMIT
            quote_buy  = pos_frac < INV_HARD_FRAC or pos < 0
            quote_sell = pos_frac < INV_HARD_FRAC or pos > 0

            if quote_buy and buy_cap > 0:
                bq = min(MM_CLIP, buy_cap, fam_room)
                if bq > 0:
                    result[sym].append(Order(sym, mm_bid_px, bq))
            if quote_sell and sell_cap > 0:
                aq = min(MM_CLIP, sell_cap, fam_room)
                if aq > 0:
                    result[sym].append(Order(sym, mm_ask_px, -aq))

        return dict(result), 0, self._save(mem)
