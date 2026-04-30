"""peter/trader100.py

Overfit / max-PnL build. Stack every alpha hard. No safety guards beyond
position limits.

Three alphas running simultaneously per symbol:

  Layer A - passive MM (earn-spread floor)
    Quote 1 tick inside mid on every whitelisted symbol with spread in
    [3, 14]. Inv skew aggressive (0.18). MM_EDGE=1. MM_CLIP=3.

  Layer B - shock fade (kens primitive, but trigger lowered)
    On |d_mid| >= max(SHOCK_BASE_per_symbol, 1.1 * spread), take liquidity
    against the move. Scaled clip by shock magnitude. Hold 1 tick.

  Layer C - z-score gamble (mean reversion at scale)
    EWMA mu/var per symbol. When |z| >= 1.5, slam against move. At
    |z| >= 2.5, push to 90% of position limit. ITM expression leg
    (PEBBLES_XL, MICROCHIP_SQUARE) gets boosted clip.

Per-symbol custom params - clip multiplier, shock base, MM edge - tuned
roughly from the alpha doc tables.
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

# (sym_limit, mm_edge, shock_base, clip_boost)
# clip_boost > 1 = bigger size on ITM leverage names + best signal quality.
SYM_PARAMS: Dict[str, Tuple[int, int, float, float]] = {
    # ITM leverage names - max size, big shock thresholds.
    "PEBBLES_XL":                 (60, 2, 18.0, 2.0),
    "PEBBLES_L":                  (50, 2, 14.0, 1.5),
    "MICROCHIP_SQUARE":           (60, 2, 16.0, 2.0),
    # Top signal-quality MM names - tight spreads, frequent fills.
    "ROBOT_DISHES":               (40, 1,  6.0, 1.6),
    "ROBOT_IRONING":              (40, 1,  6.0, 1.5),
    "ROBOT_VACUUMING":            (40, 1,  6.0, 1.5),
    "ROBOT_LAUNDRY":              (35, 1,  6.0, 1.4),
    "ROBOT_MOPPING":              (35, 1,  7.0, 1.3),
    # MICROCHIP family - good signal, moderate vol.
    "MICROCHIP_OVAL":             (40, 1,  7.0, 1.5),
    "MICROCHIP_RECTANGLE":        (40, 1,  7.0, 1.5),
    "MICROCHIP_CIRCLE":           (40, 1,  7.0, 1.5),
    "MICROCHIP_TRIANGLE":         (35, 1,  8.0, 1.3),
    # TRANSLATOR family - all pairs tight_rate=1.0.
    "TRANSLATOR_ASTRO_BLACK":     (35, 1,  8.0, 1.3),
    "TRANSLATOR_ECLIPSE_CHARCOAL":(35, 1,  8.0, 1.3),
    "TRANSLATOR_GRAPHITE_MIST":   (35, 1,  8.0, 1.3),
    "TRANSLATOR_SPACE_GRAY":      (30, 1,  8.0, 1.2),
    "TRANSLATOR_VOID_BLUE":       (30, 1,  8.0, 1.3),
    # PANEL family.
    "PANEL_1X4":                  (30, 1,  7.0, 1.3),
    "PANEL_2X2":                  (30, 1,  8.0, 1.2),
    "PANEL_2X4":                  (30, 1,  8.0, 1.2),
    "PANEL_4X4":                  (30, 1,  8.0, 1.2),
    # SLEEP_POD - one validated pair (NYLON/POLYESTER).
    "SLEEP_POD_NYLON":            (30, 1,  9.0, 1.2),
    "SLEEP_POD_POLYESTER":        (25, 1,  9.0, 1.1),
    # PEBBLES low/cheap legs - signal source for ITM bets.
    "PEBBLES_XS":                 (30, 1,  9.0, 1.3),
    "PEBBLES_M":                  (35, 2, 10.0, 1.3),
    "PEBBLES_S":                  (35, 2, 10.0, 1.3),
    # OXYGEN_SHAKE - one decent pair (CHOCOLATE/EVENING_BREATH).
    "OXYGEN_SHAKE_CHOCOLATE":     (25, 2, 10.0, 1.0),
    "OXYGEN_SHAKE_EVENING_BREATH":(25, 2, 10.0, 1.0),
}

# Family caps - generous to allow stacking.
FAMILY_LIMITS = {
    "PEBBLES":      130,
    "MICROCHIP":    130,
    "ROBOT":        110,
    "TRANSLATOR":   90,
    "PANEL":        80,
    "SLEEP_POD":    50,
    "OXYGEN_SHAKE": 40,
}

# ----- Layer A: MM -----
MM_CLIP = 3
MM_SPREAD_MIN = 3
MM_SPREAD_MAX = 14
INV_SKEW = 0.18
INV_HARD_FRAC = 0.90

# ----- Layer B: shock fade -----
SHOCK_SPREAD_MULT = 1.1     # ken used 1.2; we lower to fire more often
SHOCK_BASE_CLIP = 5
SHOCK_MAX_CLIP = 18
SHOCK_HOLD_TICKS = 1
SHOCK_COOLDOWN = 2

# ----- Layer C: z-score gamble -----
MU_ALPHA  = 0.008
VAR_ALPHA = 0.004
WARMUP    = 60
Z_ENTER   = 1.5
Z_BIG     = 2.5
Z_EXIT    = 0.25
Z_HOLD_MAX_TICKS = 250
Z_BASE_CLIP = 5
Z_MAX_FRAC = 0.90


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
            "shock_entry_ts": {},   # symbol -> ts of shock take
            "shock_dir": {},        # symbol -> +1/-1
            "shock_cooldown_ts": {},
            "z_entry_ts": {},       # symbol -> ts of z-bet entry
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

    def _update_stats(self, mem: Dict, sym: str, mid: float):
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

    def _z_target(self, z: float, sym_lim: int, boost: float) -> int:
        a = min(abs(z), Z_BIG)
        if a < Z_ENTER:
            return 0
        ramp = (a - Z_ENTER) / max(Z_BIG - Z_ENTER, 1e-9)
        peak = Z_MAX_FRAC * sym_lim * boost
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
            mem["shock_entry_ts"] = {}
            mem["shock_dir"] = {}
            mem["shock_cooldown_ts"] = {}
            mem["z_entry_ts"] = {}
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        for sym, params in SYM_PARAMS.items():
            sym_lim, sym_mm_edge, sym_shock_base, clip_boost = params
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

            mu, var, n = self._update_stats(mem, sym, mid)
            sigma = math.sqrt(max(var, 1e-9))
            z = (mid - mu) / sigma if sigma > 0.5 else 0.0

            pos = state.position.get(sym, 0)
            buy_cap = max(0, sym_lim - pos)
            sell_cap = max(0, sym_lim + pos)

            fam = _family(sym)
            fam_lim = FAMILY_LIMITS.get(fam, sym_lim * 3)
            fam_used = self._family_pos(fam, state.position)
            fam_room = max(0, fam_lim - fam_used)

            # ============ Layer C exit ============
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

            # ============ Layer B exit (shock fade) ============
            sh_entry = mem["shock_entry_ts"].get(sym, -1)
            sh_dir = mem["shock_dir"].get(sym, 0)
            if sh_entry >= 0 and sh_dir != 0:
                age = (state.timestamp - sh_entry) // 100
                if age >= SHOCK_HOLD_TICKS:
                    if sh_dir > 0 and pos > 0 and sell_cap > 0:
                        result[sym].append(Order(sym, bid, -min(pos, sell_cap)))
                    elif sh_dir < 0 and pos < 0 and buy_cap > 0:
                        result[sym].append(Order(sym, ask, min(-pos, buy_cap)))
                    mem["shock_entry_ts"][sym] = -1
                    mem["shock_dir"][sym] = 0
                    mem["shock_cooldown_ts"][sym] = state.timestamp

            # ============ Layer A: passive MM ============
            if MM_SPREAD_MIN <= spread <= MM_SPREAD_MAX and fam_room > 0:
                fair = mid - INV_SKEW * pos
                mm_bid_px = int(round(fair - sym_mm_edge))
                mm_ask_px = int(round(fair + sym_mm_edge))
                mm_bid_px = min(mm_bid_px, ask - 1)
                mm_ask_px = max(mm_ask_px, bid + 1)
                if mm_bid_px >= mm_ask_px:
                    mm_ask_px = mm_bid_px + 1

                pos_frac = abs(pos) / sym_lim if sym_lim else 0
                quote_buy  = pos_frac < INV_HARD_FRAC or pos < 0
                quote_sell = pos_frac < INV_HARD_FRAC or pos > 0

                clip = max(1, int(MM_CLIP * clip_boost))
                if quote_buy and buy_cap > 0:
                    bq = min(clip, buy_cap, fam_room)
                    if bq > 0:
                        result[sym].append(Order(sym, mm_bid_px, bq))
                if quote_sell and sell_cap > 0:
                    aq = min(clip, sell_cap, fam_room)
                    if aq > 0:
                        result[sym].append(Order(sym, mm_ask_px, -aq))

            # ============ Layer B entry: shock fade ============
            cd_ts = mem["shock_cooldown_ts"].get(sym, -10**9)
            cd_ok = state.timestamp - cd_ts >= 100 * SHOCK_COOLDOWN
            sh_open = mem["shock_entry_ts"].get(sym, -1) >= 0
            if cd_ok and not sh_open and fam_room > 0 and n >= WARMUP:
                trigger = max(sym_shock_base, SHOCK_SPREAD_MULT * spread)
                if abs(d_mid) >= trigger:
                    mag = min(3.0, abs(d_mid) / trigger)
                    sh_clip = min(SHOCK_MAX_CLIP, int(SHOCK_BASE_CLIP * mag * clip_boost))
                    if d_mid <= -trigger and buy_cap > 0:
                        q = min(sh_clip, buy_cap, fam_room)
                        if q > 0:
                            result[sym].append(Order(sym, ask, q))
                            mem["shock_entry_ts"][sym] = state.timestamp
                            mem["shock_dir"][sym] = 1
                    elif d_mid >= trigger and sell_cap > 0:
                        q = min(sh_clip, sell_cap, fam_room)
                        if q > 0:
                            result[sym].append(Order(sym, bid, -q))
                            mem["shock_entry_ts"][sym] = state.timestamp
                            mem["shock_dir"][sym] = -1

            # ============ Layer C entry: z-score gamble ============
            z_open = mem["z_entry_ts"].get(sym, -1) >= 0
            if not z_open and pos == 0 and n >= WARMUP and fam_room > 0:
                if abs(z) >= Z_ENTER:
                    target = self._z_target(z, sym_lim, clip_boost)
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
