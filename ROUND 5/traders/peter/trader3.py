"""peter/trader3.py

trader1 and trader2 lost money because every action took liquidity (entry at
ask, exit at bid). Each round trip paid 1.0 - 1.5 spreads while the alpha edge
per round trip was at most ~1 spread of mid reversion. Net negative.

ken/CSSE1001.py is a market maker - it posts passive orders at `fair +/- MM_EDGE`
(inside the top-of-book spread). When those orders fill, we *earn* the spread
instead of paying it. The shock-fade primitive sits as a small overlay on top.

trader3 is a market maker first, shock-fade second:

  Core (passive MM):
    - For each whitelisted symbol with spread >= 4, post a buy at fair-EDGE
      and a sell at fair+EDGE.
    - `fair = mid - INV_SKEW * pos` so we naturally mean-revert position.
    - Small clip per quote (3) so we don't get run over by an informed taker.
    - Refresh quotes every tick.

  Overlay (taker shock fade):
    - On a big one-tick mid jump (>= BIG_SHOCK), take liquidity in the
      reverting direction at top-of-book.
    - Has its own cooldown to avoid revenge trading.

Whitelist combines:
    - Top signal-quality names from
      docs/item_over_time/summary/top_symbols_by_signal_quality.csv (low-spread,
      strong residual reversion - perfect MM names).
    - PEBBLES_XL and MICROCHIP_SQUARE for the high-vol shock-fade overlay.
"""

import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


FAMILY_PREFIXES = [
    "PEBBLES", "SNACKPACK", "UV_VISOR", "GALAXY_SOUNDS", "MICROCHIP",
    "TRANSLATOR", "SLEEP_POD", "OXYGEN_SHAKE", "PANEL", "ROBOT",
]

# Per-symbol position limits. Tighter than ken/pot.py because the MM book
# accumulates a directional inventory passively and we need quick mean-reversion.
SYM_LIMIT_DEFAULT = 14

# Symbols we are willing to quote / trade. Limit shown is per-symbol cap.
WHITELIST: Dict[str, int] = {
    # Best signal quality + cheap spreads -> strongest MM candidates.
    "ROBOT_DISHES":               18,
    "ROBOT_IRONING":              18,
    "ROBOT_VACUUMING":            18,
    "ROBOT_LAUNDRY":              16,
    "ROBOT_MOPPING":              16,
    "MICROCHIP_OVAL":             16,
    "MICROCHIP_RECTANGLE":        16,
    "MICROCHIP_CIRCLE":           16,
    "MICROCHIP_TRIANGLE":         14,
    "TRANSLATOR_ASTRO_BLACK":     14,
    "TRANSLATOR_ECLIPSE_CHARCOAL":14,
    "TRANSLATOR_GRAPHITE_MIST":   14,
    "TRANSLATOR_SPACE_GRAY":      14,
    "PANEL_1X4":                  14,
    "PANEL_2X2":                  14,
    "PANEL_4X4":                  14,
    "SLEEP_POD_NYLON":            14,
    "PEBBLES_XS":                 14,
    # High realised vol - shock-fade only, MM still allowed when their book
    # is unusually tight.
    "MICROCHIP_SQUARE":           12,
    "PEBBLES_XL":                 12,
}

# Per-family caps so MICROCHIP / ROBOT don't soak the whole book.
FAMILY_LIMITS = {
    "ROBOT": 50,
    "MICROCHIP": 45,
    "TRANSLATOR": 35,
    "PANEL": 35,
    "SLEEP_POD": 20,
    "PEBBLES": 20,
}

# ----- Market-making knobs -----
MM_EDGE = 2                  # post this many ticks inside the top-of-book mid
MM_CLIP = 3                  # quote size per side per symbol per tick
MM_SPREAD_MIN = 4            # only quote when book is wide enough to sit inside
MM_SPREAD_MAX = 16           # avoid quoting in pathological wide books
INV_SKEW = 0.10              # shifts fair by 0.10 ticks per unit position

# ----- Shock-fade overlay knobs -----
BIG_SHOCK = 14.0             # |d_mid| trigger to take liquidity (CSSE1001 used 14)
TAKE_CLIP = 4                # taker clip
COOLDOWN_TICKS = 3           # ticks between taker entries on the same symbol
TAKER_HOLD = 1               # hold the taker leg for this many ticks then flatten


def _family(symbol: str) -> str:
    for prefix in FAMILY_PREFIXES:
        if symbol.startswith(prefix + "_"):
            return prefix
    return symbol.split("_", 1)[0]


class Trader:
    def _load(self, td: str) -> Dict:
        if not td:
            return self._empty()
        try:
            mem = json.loads(td)
        except Exception:
            return self._empty()
        for k, v in self._empty().items():
            mem.setdefault(k, v)
        return mem

    def _empty(self) -> Dict:
        return {
            "last_ts": -1,
            "day_idx": 0,
            "last_mid": {},        # for shock detection
            "last_trade_ts": {},   # cooldown for taker entries
            "taker_entry_ts": {},  # symbol -> ts when we took (for hold/exit)
            "taker_dir": {},       # symbol -> +1/-1 direction of last take
        }

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, symbol: str):
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def _family_pos(self, fam: str, position: Dict[str, int]) -> int:
        total = 0
        for sym, p in position.items():
            if _family(sym) == fam:
                total += abs(p)
        return total

    def run(self, state: TradingState):
        mem = self._load(state.traderData)

        # Day rollover.
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["day_idx"] += 1
            mem["last_mid"] = {}
            mem["last_trade_ts"] = {}
            mem["taker_entry_ts"] = {}
            mem["taker_dir"] = {}
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        for symbol, sym_lim in WHITELIST.items():
            if symbol not in state.order_depths:
                continue
            bid, ask = self._bba(state, symbol)
            if bid is None or ask is None:
                continue
            spread = ask - bid
            if spread <= 0:
                continue

            mid = 0.5 * (bid + ask)
            last_mid = mem["last_mid"].get(symbol, mid)
            d_mid = mid - last_mid
            mem["last_mid"][symbol] = mid

            pos = state.position.get(symbol, 0)
            buy_cap = max(0, sym_lim - pos)
            sell_cap = max(0, sym_lim + pos)

            fam = _family(symbol)
            fam_lim = FAMILY_LIMITS.get(fam, sym_lim * 3)
            fam_total = self._family_pos(fam, state.position)
            fam_room = max(0, fam_lim - fam_total)

            # ---------- Taker: flatten any open shock-fade leg ----------
            tk_entry = mem["taker_entry_ts"].get(symbol, -1)
            tk_dir = mem["taker_dir"].get(symbol, 0)
            if tk_entry >= 0 and tk_dir != 0:
                ticks_held = (state.timestamp - tk_entry) // 100
                if ticks_held >= TAKER_HOLD:
                    # Unwind whatever inventory direction the take created.
                    if tk_dir > 0 and pos > 0 and sell_cap > 0:
                        result[symbol].append(Order(symbol, bid, -min(pos, sell_cap)))
                    elif tk_dir < 0 and pos < 0 and buy_cap > 0:
                        result[symbol].append(Order(symbol, ask, min(-pos, buy_cap)))
                    mem["taker_entry_ts"][symbol] = -1
                    mem["taker_dir"][symbol] = 0

            # ---------- Core: passive market-making quotes ----------
            if MM_SPREAD_MIN <= spread <= MM_SPREAD_MAX and fam_room > 0:
                fair = mid - INV_SKEW * pos
                # quote one tick inside top-of-book on each side
                mm_bid_px = int(fair - MM_EDGE)
                mm_ask_px = int(fair + MM_EDGE)
                # never cross the live top-of-book
                mm_bid_px = min(mm_bid_px, ask - 1)
                mm_ask_px = max(mm_ask_px, bid + 1)
                if mm_bid_px >= mm_ask_px:
                    mm_ask_px = mm_bid_px + 1

                bq = min(MM_CLIP, buy_cap, fam_room)
                aq = min(MM_CLIP, sell_cap, fam_room)
                if bq > 0:
                    result[symbol].append(Order(symbol, mm_bid_px, bq))
                if aq > 0:
                    result[symbol].append(Order(symbol, mm_ask_px, -aq))

            # ---------- Overlay: aggressive shock fade on big jumps ----------
            last_take = mem["last_trade_ts"].get(symbol, -10**9)
            cooldown_ok = state.timestamp - last_take >= 100 * COOLDOWN_TICKS
            no_open_take = mem["taker_entry_ts"].get(symbol, -1) < 0

            if cooldown_ok and no_open_take and abs(d_mid) >= BIG_SHOCK:
                tk_clip = min(TAKE_CLIP, fam_room)
                if d_mid <= -BIG_SHOCK and buy_cap > 0:
                    q = min(tk_clip, buy_cap)
                    if q > 0:
                        result[symbol].append(Order(symbol, ask, q))
                        mem["last_trade_ts"][symbol] = state.timestamp
                        mem["taker_entry_ts"][symbol] = state.timestamp
                        mem["taker_dir"][symbol] = 1
                elif d_mid >= BIG_SHOCK and sell_cap > 0:
                    q = min(tk_clip, sell_cap)
                    if q > 0:
                        result[symbol].append(Order(symbol, bid, -q))
                        mem["last_trade_ts"][symbol] = state.timestamp
                        mem["taker_entry_ts"][symbol] = state.timestamp
                        mem["taker_dir"][symbol] = -1

        return dict(result), 0, self._save(mem)
