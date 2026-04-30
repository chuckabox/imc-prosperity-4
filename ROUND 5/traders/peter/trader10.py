"""peter/trader10.py

Stability-first trader. Goal: smooth upward PnL, not max return.

Design choices (per analyse/round5_alphas.md):
  - Trade only LOW-VOL families: ROBOT, TRANSLATOR, PANEL.
    Skip PEBBLES (vol + day-4 trend), MICROCHIP (highest realised vol),
    SLEEP_POD (anti-pair drift), SNACKPACK/UV_VISOR/GALAXY_SOUNDS/
    OXYGEN_SHAKE (low signal quality).
  - Pure passive market making. No taker. No shock fade. No directional bets.
    Earn spread on each filled round trip -> structural positive expectation.
  - Inventory skew (INV_SKEW high) so position mean-reverts on its own and
    we never accumulate big delta on a runaway move.
  - Tight per-symbol position caps so a single bad direction can't bleed.
  - Spread gate min=3 max=10 - we only quote in the predictable regime.
  - Quote one tick inside top-of-book (MM_EDGE=1). Many fills, small profit
    each, low variance.

Why no pair / shock fade here:
  - Pair trades cross 2 spreads on entry + 2 on exit -> ~32 ticks cost vs
    ~2 ticks signal mean drift. Negative round-trip EV in our test runs.
  - Shock fade is a thin trade and the high-vol names that have big shocks
    (PEBBLES_XL, MICROCHIP_SQUARE) are exactly the unstable names we are
    avoiding.

If trader10 is flat-positive, push edge by:
  - Lowering MM_EDGE to 1 across the board (already done).
  - Raising MM_CLIP cautiously.
  - Adding more low-vol names if family-level realised vol stays small.
"""

import json
from collections import defaultdict
from typing import Dict, List

from datamodel import Order, TradingState


FAMILY_PREFIXES = [
    "PEBBLES", "SNACKPACK", "UV_VISOR", "GALAXY_SOUNDS", "MICROCHIP",
    "TRANSLATOR", "SLEEP_POD", "OXYGEN_SHAKE", "PANEL", "ROBOT",
]

# Whitelist - stable low-vol, low-spread, high signal quality.
# Limit per symbol kept modest so bad days self-cap.
WHITELIST: Dict[str, int] = {
    # ROBOT family - cheapest spreads (6-7), strongest reversion (q 0.15-0.25).
    "ROBOT_DISHES":               14,
    "ROBOT_IRONING":              14,
    "ROBOT_VACUUMING":            14,
    "ROBOT_LAUNDRY":              12,
    "ROBOT_MOPPING":              12,
    # TRANSLATOR family - all pairs tight_rate=1.0, predictable.
    "TRANSLATOR_ASTRO_BLACK":     12,
    "TRANSLATOR_ECLIPSE_CHARCOAL":12,
    "TRANSLATOR_GRAPHITE_MIST":   12,
    "TRANSLATOR_SPACE_GRAY":      12,
    "TRANSLATOR_VOID_BLUE":       12,
    # PANEL family (skip 1X4 anti-pair leg, but keep it for MM since it has
    # decent solo signal quality 0.148; just smaller cap).
    "PANEL_1X4":                  10,
    "PANEL_2X2":                  12,
    "PANEL_2X4":                  12,
    "PANEL_4X4":                  12,
}

# Family caps - sum of |pos| across symbols in family.
FAMILY_LIMITS = {
    "ROBOT":      40,
    "TRANSLATOR": 35,
    "PANEL":      30,
}

# ----- MM knobs -----
MM_EDGE       = 1     # one tick inside mid (or top-of-book, whichever tighter)
MM_CLIP       = 2     # quote size per side per tick (small -> low adverse selection)
MM_SPREAD_MIN = 3     # need at least this much spread to sit inside profitably
MM_SPREAD_MAX = 10    # avoid quoting in pathological wide books
INV_SKEW      = 0.20  # ticks of fair-shift per unit position (strong mean-reversion)
INV_HARD_FRAC = 0.85  # if |pos|/limit >= this, only quote the reducing side


def _family(symbol: str) -> str:
    for prefix in FAMILY_PREFIXES:
        if symbol.startswith(prefix + "_"):
            return prefix
    return symbol.split("_", 1)[0]


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
        depth = state.order_depths.get(sym)
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def _family_pos(self, fam: str, position: Dict[str, int]) -> int:
        return sum(abs(p) for s, p in position.items() if _family(s) == fam)

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["last_ts"] = state.timestamp     # nothing else to reset (no rolling state)
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

            mid = 0.5 * (bid + ask)
            pos = state.position.get(sym, 0)

            fam = _family(sym)
            fam_lim = FAMILY_LIMITS.get(fam, sym_lim * 3)
            fam_used = self._family_pos(fam, state.position)
            fam_room = max(0, fam_lim - fam_used)
            if fam_room <= 0:
                continue

            buy_cap = max(0, sym_lim - pos)
            sell_cap = max(0, sym_lim + pos)

            # Inventory skew - if long, lower fair so our buy quote sits
            # further from market and our sell quote gets hit faster.
            fair = mid - INV_SKEW * pos
            mm_bid_px = int(round(fair - MM_EDGE))
            mm_ask_px = int(round(fair + MM_EDGE))

            # Never cross the live top-of-book.
            mm_bid_px = min(mm_bid_px, ask - 1)
            mm_ask_px = max(mm_ask_px, bid + 1)
            if mm_bid_px >= mm_ask_px:
                mm_ask_px = mm_bid_px + 1

            # If position near hard limit, only quote the side that reduces it.
            pos_frac = abs(pos) / sym_lim if sym_lim else 0
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
