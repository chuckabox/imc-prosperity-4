"""peter/trader4.py

Gamble mode. Pure mean reversion via rolling z-score. Match discord hint:
"hard coded values for mean reversion and use ITM options as leveraged positions".

Logic:
  - Per symbol, EWMA mean + var (slow, ~300 tick effective).
  - z = (mid - mu) / sigma.
  - When |z| >= Z_ENTER, slam against the move at top-of-book.
  - Size scales linearly with |z|, capped at family limit.
  - Hold until |z| <= Z_EXIT or HOLD_MAX ticks.
  - Heavy clip on ITM/high-notional names (PEBBLES_XL, MICROCHIP_SQUARE,
    PEBBLES_L) - same residual signal, larger absolute pnl per unit.

No MM. No shock-fade. Pure directional bet on mean reversion.
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

# Tradeable universe + per-symbol position limit.
# ITM/high-notional names get bigger limits (the leverage leg of the bet).
WHITELIST: Dict[str, int] = {
    # Heavy ITM bets - big notional, leverage the family signal.
    "PEBBLES_XL":                 30,
    "PEBBLES_L":                  25,
    "MICROCHIP_SQUARE":           30,
    "MICROCHIP_OVAL":             20,
    "MICROCHIP_RECTANGLE":        20,
    "MICROCHIP_CIRCLE":           20,
    "MICROCHIP_TRIANGLE":         15,
    # Lower-notional but strong reversion - solid base.
    "ROBOT_DISHES":               20,
    "ROBOT_IRONING":              20,
    "ROBOT_VACUUMING":            20,
    "ROBOT_LAUNDRY":              18,
    "ROBOT_MOPPING":              18,
    "TRANSLATOR_ASTRO_BLACK":     16,
    "TRANSLATOR_ECLIPSE_CHARCOAL":16,
    "TRANSLATOR_GRAPHITE_MIST":   16,
    "TRANSLATOR_VOID_BLUE":       16,
    "TRANSLATOR_SPACE_GRAY":      16,
    "PANEL_1X4":                  18,
    "PANEL_2X2":                  16,
    "PANEL_2X4":                  16,
    "PANEL_4X4":                  16,
    "SLEEP_POD_NYLON":            16,
    "SLEEP_POD_POLYESTER":        14,
    "PEBBLES_XS":                 16,
    "PEBBLES_M":                  18,
    "PEBBLES_S":                  18,
    "OXYGEN_SHAKE_CHOCOLATE":     14,
    "OXYGEN_SHAKE_EVENING_BREATH":14,
}

# Family caps - prevent one family eating whole book.
FAMILY_LIMITS = {
    "PEBBLES":      80,
    "MICROCHIP":    80,
    "ROBOT":        70,
    "TRANSLATOR":   60,
    "PANEL":        50,
    "SLEEP_POD":    25,
    "OXYGEN_SHAKE": 25,
}

# EWMA tracking - slow window so z reflects real deviation, not noise.
MU_ALPHA  = 0.0067    # ~150-tick effective for mean
VAR_ALPHA = 0.0033    # ~300-tick effective for variance
WARMUP    = 80        # need this many samples before we trust z

# Bet thresholds.
Z_ENTER       = 2.0   # gamble when |z| >= 2.0 (top ~5% deviations)
Z_BIG         = 3.0   # max-size bet when |z| >= 3.0
Z_EXIT        = 0.3   # close when reverted
HOLD_MAX_TICKS = 200  # hard time-stop

# Sizing - clip scales linearly between Z_ENTER and Z_BIG.
BASE_CLIP = 6
MAX_SIZE_FRAC = 0.85  # at z >= Z_BIG, target this fraction of position limit


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
            "mu": {},          # symbol -> EWMA mean of mid
            "var": {},         # symbol -> EWMA variance
            "n": {},           # symbol -> sample count
            "entry_ts": {},    # symbol -> ts of bet entry
        }

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, symbol: str):
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

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

    def _target_size(self, z: float, sym_lim: int) -> int:
        # Linear ramp from BASE_CLIP at Z_ENTER to MAX_SIZE_FRAC*sym_lim at Z_BIG.
        z_abs = min(abs(z), Z_BIG)
        if z_abs < Z_ENTER:
            return 0
        ramp = (z_abs - Z_ENTER) / max(Z_BIG - Z_ENTER, 1e-9)
        target = BASE_CLIP + ramp * (MAX_SIZE_FRAC * sym_lim - BASE_CLIP)
        return max(BASE_CLIP, int(target))

    def run(self, state: TradingState):
        mem = self._load(state.traderData)

        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["day_idx"] += 1
            mem["mu"] = {}
            mem["var"] = {}
            mem["n"] = {}
            mem["entry_ts"] = {}
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        for sym, sym_lim in WHITELIST.items():
            if sym not in state.order_depths:
                continue
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None:
                continue
            spread = ask - bid
            if spread <= 0:
                continue

            mid = 0.5 * (bid + ask)
            mu, var, n = self._update_stats(mem, sym, mid)

            if n < WARMUP:
                continue

            sigma = math.sqrt(max(var, 1e-9))
            if sigma < 1.0:
                continue
            z = (mid - mu) / sigma

            pos = state.position.get(sym, 0)
            buy_cap = max(0, sym_lim - pos)
            sell_cap = max(0, sym_lim + pos)

            fam = _family(sym)
            fam_lim = FAMILY_LIMITS.get(fam, sym_lim * 3)
            fam_used = self._family_pos(fam, state.position)
            fam_room = max(0, fam_lim - fam_used)

            entry_ts = mem["entry_ts"].get(sym, -1)

            # ---------- Exit ----------
            if pos != 0:
                age = (state.timestamp - entry_ts) // 100 if entry_ts >= 0 else 0
                reverted = abs(z) <= Z_EXIT
                # Also exit if z flips to opposite side (we were wrong, cut).
                opposite = (pos > 0 and z >= Z_EXIT) or (pos < 0 and z <= -Z_EXIT)
                if reverted or age >= HOLD_MAX_TICKS or opposite:
                    if pos > 0 and sell_cap > 0:
                        result[sym].append(Order(sym, bid, -min(pos, sell_cap)))
                    elif pos < 0 and buy_cap > 0:
                        result[sym].append(Order(sym, ask, min(-pos, buy_cap)))
                    mem["entry_ts"][sym] = -1
                continue

            # ---------- Entry ----------
            if abs(z) < Z_ENTER:
                continue
            if fam_room <= 0:
                continue

            target = self._target_size(z, sym_lim)
            target = min(target, fam_room)

            if z >= Z_ENTER and sell_cap > 0:
                q = min(target, sell_cap)
                if q > 0:
                    result[sym].append(Order(sym, bid, -q))
                    mem["entry_ts"][sym] = state.timestamp
            elif z <= -Z_ENTER and buy_cap > 0:
                q = min(target, buy_cap)
                if q > 0:
                    result[sym].append(Order(sym, ask, q))
                    mem["entry_ts"][sym] = state.timestamp

        return dict(result), 0, self._save(mem)
