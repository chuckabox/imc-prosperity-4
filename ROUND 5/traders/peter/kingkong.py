"""peter/kingkong.py

Overfit twin of kingking. Same hard pos limit (10/product, algo.md), but:

  - Whitelist = ALL 50 products with per-symbol hard-coded params.
  - 3 alpha layers stacked (per-symbol enable flags):
      MM    : passive market making, sized per symbol
      SHOCK : taker shock-fade (kens reversal@8 primitive, per-sym trigger)
      Z     : EWMA z-score gamble for big deviations
  - Per-symbol clip boost on ITM leverage names (PEBBLES_XL, MICROCHIP_SQUARE).
  - Skip MM on anti-pair drifters (SLEEP_POD COTTON/LAMB_WOOL/SUEDE,
    PANEL_1X4, OXYGEN_SHAKE MINT/MORNING_BREATH/GARLIC).
  - Skip MM on dead names (SNACKPACK_*, GALAXY_SOUNDS_*, UV_VISOR_*) -
    spreads too wide for MM to clear cost. Keep shock-fade only as a
    cheap-option overlay.

Weaknesses of kingking that this fixes:
  1. Universe 7 -> 50.
  2. No shock-fade -> per-symbol shock layer with custom trigger.
  3. No ITM leverage -> PEBBLES_XL / MICROCHIP_SQUARE clip boost on shock.
  4. No z-gamble -> z layer with per-symbol enable.
  5. MM_CLIP=1 hard -> scaled by symbol-specific clip param (1-3).
  6. Spread cap 9 too tight -> per-symbol max_spread (up to 18 for PEBBLES_XL).
  7. Universal params -> param dict keyed per-symbol.
"""

import json
import math
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


FAMILY_PREFIXES = [
    "PEBBLES", "SNACKPACK", "UV_VISOR", "GALAXY_SOUNDS", "MICROCHIP",
    "TRANSLATOR", "SLEEP_POD", "OXYGEN_SHAKE", "PANEL", "ROBOT",
]

# Hard cap from algo.md.
SYM_LIMIT = 10

# Per-symbol param schema:
#   mm_on       : passive MM enabled
#   mm_edge     : ticks inside fair (1 or 2)
#   mm_clip     : MM size per side per tick
#   mm_smin     : min spread to quote inside
#   mm_smax     : max spread to quote inside
#   sh_on       : shock-fade overlay enabled
#   sh_trig     : abs d_mid threshold for shock
#   sh_clip     : taker clip on shock fade
#   z_on        : z-score gamble enabled
#   boost       : ITM-leverage scalar applied to sh_clip + z target
SYMS: Dict[str, Dict] = {}

def _add(sym, mm_on, mm_edge, mm_clip, mm_smin, mm_smax,
         sh_on, sh_trig, sh_clip, z_on, boost=1.0):
    SYMS[sym] = dict(mm_on=mm_on, mm_edge=mm_edge, mm_clip=mm_clip,
                     mm_smin=mm_smin, mm_smax=mm_smax,
                     sh_on=sh_on, sh_trig=sh_trig, sh_clip=sh_clip,
                     z_on=z_on, boost=boost)

# ---- ROBOT (Tier 1, low vol, top signal quality) ----
_add("ROBOT_DISHES",     True, 1, 2, 3, 9,  True,  6.0, 4, True,  1.2)
_add("ROBOT_IRONING",    True, 1, 2, 3, 8,  True,  6.0, 4, True,  1.2)
_add("ROBOT_VACUUMING",  True, 1, 2, 3, 9,  True,  7.0, 4, True,  1.1)
_add("ROBOT_LAUNDRY",    True, 1, 2, 3, 9,  True,  7.0, 4, True,  1.0)
_add("ROBOT_MOPPING",    True, 1, 2, 3, 10, True,  8.0, 4, True,  1.0)

# ---- TRANSLATOR (Tier 1, all pairs tight_rate=1.0) ----
_add("TRANSLATOR_ASTRO_BLACK",      True, 1, 2, 3, 10, True,  8.0, 3, True, 1.2)
_add("TRANSLATOR_GRAPHITE_MIST",    True, 1, 2, 3, 10, True,  8.0, 3, True, 1.2)
_add("TRANSLATOR_ECLIPSE_CHARCOAL", True, 1, 2, 3, 10, True,  8.0, 3, True, 1.0)
_add("TRANSLATOR_SPACE_GRAY",       True, 1, 2, 3, 11, True,  9.0, 3, True, 1.0)
_add("TRANSLATOR_VOID_BLUE",        True, 1, 2, 3, 11, True,  9.0, 3, True, 1.0)

# ---- PANEL (Tier 1; 1X4 = anti-pair leg, MM off) ----
_add("PANEL_2X2",   True, 1, 2, 3, 10, True,  8.0, 3, True, 1.0)
_add("PANEL_2X4",   True, 1, 2, 3, 10, True,  8.0, 3, True, 1.0)
_add("PANEL_4X4",   True, 1, 2, 3, 11, True,  9.0, 3, True, 1.0)
_add("PANEL_1X4",   True, 1, 1, 3, 10, True,  8.0, 3, True, 1.0)
_add("PANEL_1X2",   True, 1, 1, 3, 12, True,  9.0, 3, True, 1.0)

# ---- MICROCHIP (Tier 3, high vol but strong patterns) ----
_add("MICROCHIP_OVAL",      True, 1, 2, 3, 11, True,  7.0, 4, True, 1.2)
_add("MICROCHIP_RECTANGLE", True, 1, 2, 3, 11, True,  7.0, 4, True, 1.2)
_add("MICROCHIP_CIRCLE",    True, 1, 2, 3, 11, True,  7.0, 4, True, 1.2)
_add("MICROCHIP_TRIANGLE",  True, 1, 2, 3, 12, True,  8.0, 4, True, 1.1)
# SQUARE = ITM leverage leg, big shocks
_add("MICROCHIP_SQUARE",    True, 2, 2, 4, 14, True, 14.0, 5, True, 1.5)

# ---- PEBBLES (Tier 3, highest vol, ITM leverage on XL/L) ----
_add("PEBBLES_XS",  True, 1, 2, 3, 12, True, 10.0, 4, True, 1.0)
_add("PEBBLES_S",   True, 1, 2, 3, 13, True, 11.0, 4, True, 1.0)
_add("PEBBLES_M",   True, 2, 2, 4, 14, True, 12.0, 4, True, 1.1)
_add("PEBBLES_L",   True, 2, 2, 4, 15, True, 14.0, 4, True, 1.3)
_add("PEBBLES_XL",  True, 2, 2, 5, 18, True, 20.0, 5, True, 1.5)

# ---- SLEEP_POD (NYLON/POLYESTER pair only; rest drift) ----
_add("SLEEP_POD_NYLON",     True, 1, 2, 3, 10, True,  9.0, 3, True, 1.1)
_add("SLEEP_POD_POLYESTER", True, 1, 2, 3, 12, True, 10.0, 3, True, 1.0)
# Drifters - shock-fade only, no MM (would accumulate bad inventory).
_add("SLEEP_POD_COTTON",     False, 1, 1, 3, 12, True, 11.0, 3, True, 1.0)
_add("SLEEP_POD_LAMB_WOOL",  False, 1, 1, 3, 12, True, 11.0, 3, True, 1.0)
_add("SLEEP_POD_SUEDE",      False, 1, 1, 3, 12, True, 11.0, 3, True, 1.0)

# ---- OXYGEN_SHAKE (one validated pair: CHOCOLATE/EVENING_BREATH) ----
_add("OXYGEN_SHAKE_CHOCOLATE",      True, 1, 1, 4, 13, True, 10.0, 3, True, 1.0)
_add("OXYGEN_SHAKE_EVENING_BREATH", True, 1, 1, 4, 13, True, 10.0, 3, True, 1.0)
_add("OXYGEN_SHAKE_MINT",           False, 1, 1, 0, 0,  True, 13.0, 3, True, 1.0)
_add("OXYGEN_SHAKE_MORNING_BREATH", False, 1, 1, 0, 0,  True, 13.0, 3, True, 1.0)
_add("OXYGEN_SHAKE_GARLIC",         False, 1, 1, 0, 0,  True, 14.0, 3, True, 1.0)

# ---- SNACKPACK (Tier 4, dead) - shock-fade only on extreme moves ----
for _s in ("SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
           "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"):
    _add(_s, False, 1, 1, 0, 0, True, 16.0, 3, True, 1.0)

# ---- GALAXY_SOUNDS (Tier 4, dead) - shock-fade only ----
for _s in ("GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
           "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
           "GALAXY_SOUNDS_SOLAR_FLAMES"):
    _add(_s, False, 1, 1, 0, 0, True, 14.0, 3, True, 1.0)

# ---- UV_VISOR (Tier 4, dead) - shock-fade only ----
for _s in ("UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
           "UV_VISOR_RED", "UV_VISOR_MAGENTA"):
    _add(_s, False, 1, 1, 0, 0, True, 13.0, 3, True, 1.0)

# Family caps - sum of |pos|. Generous because pos limit is already tight (10).
FAMILY_LIMITS = {
    "ROBOT":         35,
    "TRANSLATOR":    35,
    "PANEL":         30,
    "MICROCHIP":     35,
    "PEBBLES":       35,
    "SLEEP_POD":     20,
    "OXYGEN_SHAKE":  15,
    "SNACKPACK":     10,
    "GALAXY_SOUNDS": 10,
    "UV_VISOR":      10,
}

# Layer-A (MM) globals
INV_SKEW = 0.20
INV_HARD_FRAC = 0.80

# Layer-B (shock fade) globals
SHOCK_HOLD_TICKS = 1
SHOCK_COOLDOWN = 2

# Layer-C (z-score gamble) globals
MU_ALPHA  = 0.008
VAR_ALPHA = 0.004
WARMUP    = 60
Z_ENTER   = 1.8
Z_BIG     = 2.8
Z_EXIT    = 0.3
Z_HOLD_MAX_TICKS = 200
Z_BASE_CLIP = 3
Z_MAX_FRAC  = 0.85


def _family(sym: str) -> str:
    for p in FAMILY_PREFIXES:
        if sym.startswith(p + "_"):
            return p
    return sym.split("_", 1)[0]


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
            "last_mid": {},
            "mu": {},
            "var": {},
            "n": {},
            "sh_entry_ts": {},
            "sh_dir": {},
            "sh_cd": {},
            "z_entry_ts": {},
        }

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders:
            return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def _family_pos(self, fam: str, position: Dict[str, int]) -> int:
        return sum(abs(p) for s, p in position.items() if _family(s) == fam)

    def _ewma(self, mem, sym, mid):
        mu = mem["mu"].get(sym)
        var = mem["var"].get(sym, 0.0)
        n = mem["n"].get(sym, 0) + 1
        if mu is None:
            mu = mid
            var = 0.0
        else:
            mu = (1 - MU_ALPHA) * mu + MU_ALPHA * mid
            d = mid - mu
            var = (1 - VAR_ALPHA) * var + VAR_ALPHA * d * d
        mem["mu"][sym] = mu
        mem["var"][sym] = var
        mem["n"][sym] = n
        return mu, var, n

    def _z_target(self, z, boost):
        a = min(abs(z), Z_BIG)
        if a < Z_ENTER:
            return 0
        ramp = (a - Z_ENTER) / max(Z_BIG - Z_ENTER, 1e-9)
        peak = Z_MAX_FRAC * SYM_LIMIT * boost
        target = Z_BASE_CLIP + ramp * (peak - Z_BASE_CLIP)
        return max(Z_BASE_CLIP, int(target))

    def run(self, state: TradingState):
        mem = self._load(state.traderData)

        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["day_idx"] += 1
            mem["last_mid"] = {}
            mem["mu"] = {}
            mem["var"] = {}
            mem["n"] = {}
            mem["sh_entry_ts"] = {}
            mem["sh_dir"] = {}
            mem["sh_cd"] = {}
            mem["z_entry_ts"] = {}
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        for sym, p in SYMS.items():
            if sym not in state.order_depths:
                continue
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None:
                continue
            spread = ask - bid
            if spread <= 0:
                continue
            mid = 0.5 * (bid + ask)

            last_mid = mem["last_mid"].get(sym, mid)
            d_mid = mid - last_mid
            mem["last_mid"][sym] = mid

            mu, var, n = self._ewma(mem, sym, mid)
            sigma = math.sqrt(max(var, 1e-9))
            z = (mid - mu) / sigma if sigma > 0.5 else 0.0

            pos = state.position.get(sym, 0)
            buy_cap = max(0, SYM_LIMIT - pos)
            sell_cap = max(0, SYM_LIMIT + pos)

            fam = _family(sym)
            fam_lim = FAMILY_LIMITS.get(fam, SYM_LIMIT * 5)
            fam_used = self._family_pos(fam, state.position)
            fam_room = max(0, fam_lim - fam_used)

            boost = p["boost"]

            # ===== Layer C exit (z-score) =====
            z_entry = mem["z_entry_ts"].get(sym, -1)
            if z_entry >= 0 and pos != 0:
                age = (state.timestamp - z_entry) // 100
                reverted = abs(z) <= Z_EXIT
                opposite = (pos > 0 and z >= Z_EXIT) or (pos < 0 and z <= -Z_EXIT)
                if reverted or age >= Z_HOLD_MAX_TICKS or opposite:
                    if pos > 0 and sell_cap > 0:
                        result[sym].append(Order(sym, bid, -min(pos, sell_cap)))
                    elif pos < 0 and buy_cap > 0:
                        result[sym].append(Order(sym, ask, min(-pos, buy_cap)))
                    mem["z_entry_ts"][sym] = -1
                    continue

            # ===== Layer B exit (shock fade) =====
            sh_entry = mem["sh_entry_ts"].get(sym, -1)
            sh_dir = mem["sh_dir"].get(sym, 0)
            if sh_entry >= 0 and sh_dir != 0:
                age = (state.timestamp - sh_entry) // 100
                if age >= SHOCK_HOLD_TICKS:
                    if sh_dir > 0 and pos > 0 and sell_cap > 0:
                        result[sym].append(Order(sym, bid, -min(pos, sell_cap)))
                    elif sh_dir < 0 and pos < 0 and buy_cap > 0:
                        result[sym].append(Order(sym, ask, min(-pos, buy_cap)))
                    mem["sh_entry_ts"][sym] = -1
                    mem["sh_dir"][sym] = 0
                    mem["sh_cd"][sym] = state.timestamp

            # ===== Layer A: passive MM =====
            if p["mm_on"] and p["mm_smin"] <= spread <= p["mm_smax"] and fam_room > 0:
                fair = mid - INV_SKEW * pos
                bx = int(round(fair - p["mm_edge"]))
                ax = int(round(fair + p["mm_edge"]))
                bx = min(bx, ask - 1)
                ax = max(ax, bid + 1)
                if bx >= ax:
                    ax = bx + 1
                pos_frac = abs(pos) / SYM_LIMIT
                quote_buy  = pos_frac < INV_HARD_FRAC or pos < 0
                quote_sell = pos_frac < INV_HARD_FRAC or pos > 0
                clip = p["mm_clip"]
                if quote_buy and buy_cap > 0:
                    bq = min(clip, buy_cap, fam_room)
                    if bq > 0:
                        result[sym].append(Order(sym, bx, bq))
                if quote_sell and sell_cap > 0:
                    aq = min(clip, sell_cap, fam_room)
                    if aq > 0:
                        result[sym].append(Order(sym, ax, -aq))

            # ===== Layer B entry: shock fade =====
            cd_ts = mem["sh_cd"].get(sym, -10**9)
            cd_ok = state.timestamp - cd_ts >= 100 * SHOCK_COOLDOWN
            sh_open = mem["sh_entry_ts"].get(sym, -1) >= 0
            if (p["sh_on"] and cd_ok and not sh_open and fam_room > 0
                    and n >= WARMUP and abs(d_mid) >= p["sh_trig"]):
                mag = min(2.5, abs(d_mid) / max(p["sh_trig"], 1.0))
                clip = max(1, int(p["sh_clip"] * mag * boost))
                if d_mid <= -p["sh_trig"] and buy_cap > 0:
                    q = min(clip, buy_cap, fam_room)
                    if q > 0:
                        result[sym].append(Order(sym, ask, q))
                        mem["sh_entry_ts"][sym] = state.timestamp
                        mem["sh_dir"][sym] = 1
                elif d_mid >= p["sh_trig"] and sell_cap > 0:
                    q = min(clip, sell_cap, fam_room)
                    if q > 0:
                        result[sym].append(Order(sym, bid, -q))
                        mem["sh_entry_ts"][sym] = state.timestamp
                        mem["sh_dir"][sym] = -1

            # ===== Layer C entry: z-score gamble =====
            z_open = mem["z_entry_ts"].get(sym, -1) >= 0
            if (p["z_on"] and not z_open and pos == 0
                    and n >= WARMUP and fam_room > 0
                    and abs(z) >= Z_ENTER):
                target = self._z_target(z, boost)
                target = min(target, fam_room)
                if z >= Z_ENTER and sell_cap > 0:
                    q = min(target, sell_cap)
                    if q > 0:
                        result[sym].append(Order(sym, bid, -q))
                        mem["z_entry_ts"][sym] = state.timestamp
                elif z <= -Z_ENTER and buy_cap > 0:
                    q = min(target, buy_cap)
                    if q > 0:
                        result[sym].append(Order(sym, ask, q))
                        mem["z_entry_ts"][sym] = state.timestamp

        return dict(result), 0, self._save(mem)
