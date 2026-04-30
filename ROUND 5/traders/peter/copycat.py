"""peter/copycat.py

Reverse-engineered from competitor file
`submissions/round5_lag_self_group_ratio_top_exec_server_test_v7.py` which
hit ~2.8M total over R5 days 2-4 with even per-product PnL (~15-30k each
across all 50 products, including SNACKPACK / GALAXY_SOUNDS / UV_VISOR).

Filename decodes the strategy:
  lag         -> use lagged group mid as predictor
  self        -> per-symbol mid
  group_ratio -> ratio (self_mid / group_mid) tracked per symbol
  top_exec    -> take liquidity at best ask/bid (no MM)

Mechanism:
  1. Build family group mid = mean of available family member mids each tick.
  2. Track rolling EWMA of `ratio_t = mid_self / group_mid` per symbol.
  3. Predicted self mid for tick t = group_mid_{t-1} * ratio_ewma.
  4. Residual = mid_self_t - predicted_self_t.
  5. Z-score residual against rolling EWMA std.
  6. When |z| >= Z_ENTER, take liquidity against the divergence.
  7. Exit when |z| <= Z_EXIT or hold time exceeded.

Trade ALL 50 products. Pos limit 10/symbol per algo.md.
"""

import json
import math
from collections import defaultdict
from typing import Dict, List

from datamodel import Order, TradingState


FAMILY_PREFIXES = [
    "PEBBLES", "SNACKPACK", "UV_VISOR", "GALAXY_SOUNDS", "MICROCHIP",
    "TRANSLATOR", "SLEEP_POD", "OXYGEN_SHAKE", "PANEL", "ROBOT",
]

# Hard cap from algo.md.
SYM_LIMIT = 10

# Family members for group mid calculation.
FAMILY_MEMBERS = {
    "PEBBLES":      ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"],
    "SNACKPACK":    ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
                     "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"],
    "UV_VISOR":     ["UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
                     "UV_VISOR_RED", "UV_VISOR_MAGENTA"],
    "GALAXY_SOUNDS":["GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
                     "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
                     "GALAXY_SOUNDS_SOLAR_FLAMES"],
    "MICROCHIP":    ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
                     "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE"],
    "TRANSLATOR":   ["TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
                     "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
                     "TRANSLATOR_VOID_BLUE"],
    "SLEEP_POD":    ["SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
                     "SLEEP_POD_NYLON", "SLEEP_POD_COTTON"],
    "OXYGEN_SHAKE": ["OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
                     "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_GARLIC"],
    "PANEL":        ["PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"],
    "ROBOT":        ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
                     "ROBOT_LAUNDRY", "ROBOT_IRONING"],
}

# ----- EWMA params -----
RATIO_ALPHA = 0.005   # ~200-tick effective for ratio mean
GROUP_ALPHA = 0.05    # group mid changes faster (mean of 5 names) - faster track
ERR_VAR_ALPHA = 0.01  # residual variance EWMA
WARMUP = 80

# ----- Trading params -----
Z_ENTER = 1.5         # |z| threshold for entry
Z_BIG   = 2.5         # at this z, push to MAX_FRAC of pos limit
Z_EXIT  = 0.30        # close when reverted
HOLD_MAX_TICKS = 80   # safety time-stop

BASE_CLIP   = 3       # min trade size on entry
MAX_FRAC    = 0.95    # at z >= Z_BIG, target this fraction of pos limit


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
            "ratio": {},          # symbol -> EWMA ratio (mid_self / group_mid)
            "group_mid": {},      # family -> EWMA group mid (lagged use)
            "group_mid_prev": {}, # family -> previous tick's group mid (the "lag")
            "err_var": {},        # symbol -> EWMA variance of residual
            "n": {},              # symbol -> sample count
            "entry_ts": {},       # symbol -> ts of position entry
        }

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders:
            return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def _target_size(self, z: float) -> int:
        a = min(abs(z), Z_BIG)
        if a < Z_ENTER:
            return 0
        ramp = (a - Z_ENTER) / max(Z_BIG - Z_ENTER, 1e-9)
        peak = MAX_FRAC * SYM_LIMIT
        target = BASE_CLIP + ramp * (peak - BASE_CLIP)
        return max(BASE_CLIP, int(round(target)))

    def run(self, state: TradingState):
        mem = self._load(state.traderData)

        # Day rollover.
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["day_idx"] += 1
            mem["ratio"] = {}
            mem["group_mid"] = {}
            mem["group_mid_prev"] = {}
            mem["err_var"] = {}
            mem["n"] = {}
            mem["entry_ts"] = {}
        mem["last_ts"] = state.timestamp

        # ----- Step 1: compute mids per symbol, group mid per family -----
        mids: Dict[str, float] = {}
        for sym in state.order_depths:
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None:
                continue
            mids[sym] = 0.5 * (bid + ask)

        group_mid_now: Dict[str, float] = {}
        for fam, members in FAMILY_MEMBERS.items():
            vals = [mids[m] for m in members if m in mids]
            if vals:
                group_mid_now[fam] = sum(vals) / len(vals)

        # ----- Step 2: per-symbol prediction + residual -----
        # We use group_mid_PREV (lagged) as the predictor input. That's the "lag" piece.
        result: Dict[str, List[Order]] = defaultdict(list)

        for sym, mid in mids.items():
            fam = _family(sym)
            if fam not in group_mid_now:
                continue
            gm_now = group_mid_now[fam]
            gm_prev = mem["group_mid_prev"].get(fam, gm_now)

            # Update ratio EWMA against current group mid.
            ratio = mem["ratio"].get(sym)
            if ratio is None:
                ratio = mid / gm_now if gm_now > 0 else 1.0
            else:
                instant = mid / gm_now if gm_now > 0 else ratio
                ratio = (1 - RATIO_ALPHA) * ratio + RATIO_ALPHA * instant
            mem["ratio"][sym] = ratio

            # Predicted self-mid uses LAGGED group mid * ratio.
            predicted = gm_prev * ratio if gm_prev > 0 else mid
            err = mid - predicted

            # Update residual variance EWMA.
            var = mem["err_var"].get(sym, 0.0)
            var = (1 - ERR_VAR_ALPHA) * var + ERR_VAR_ALPHA * err * err
            mem["err_var"][sym] = var

            n = mem["n"].get(sym, 0) + 1
            mem["n"][sym] = n

            sigma = math.sqrt(max(var, 1e-9))
            z = err / sigma if sigma > 0.5 else 0.0

            bid, ask = self._bba(state, sym)
            if bid is None or ask is None:
                continue

            pos = state.position.get(sym, 0)
            buy_cap = max(0, SYM_LIMIT - pos)
            sell_cap = max(0, SYM_LIMIT + pos)
            entry_ts = mem["entry_ts"].get(sym, -1)

            # ----- Exit -----
            if pos != 0:
                age = (state.timestamp - entry_ts) // 100 if entry_ts >= 0 else 0
                reverted = abs(z) <= Z_EXIT
                # Aggressive: also exit if z flips sign past zero.
                opposite = (pos > 0 and z >= Z_EXIT) or (pos < 0 and z <= -Z_EXIT)
                if reverted or age >= HOLD_MAX_TICKS or opposite:
                    if pos > 0 and sell_cap > 0:
                        result[sym].append(Order(sym, bid, -min(pos, sell_cap)))
                    elif pos < 0 and buy_cap > 0:
                        result[sym].append(Order(sym, ask, min(-pos, buy_cap)))
                    mem["entry_ts"][sym] = -1
                continue

            # ----- Entry -----
            if n < WARMUP:
                continue
            if abs(z) < Z_ENTER:
                continue

            target = self._target_size(z)

            # err > 0 means mid is HIGHER than predicted -> sell (top exec).
            # err < 0 means mid is LOWER than predicted -> buy (top exec).
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

        # ----- Step 3: roll group_mid_prev forward for next tick -----
        # group_mid EWMA tracks slow drift; group_mid_prev is the actual lag.
        for fam, gm in group_mid_now.items():
            mem["group_mid_prev"][fam] = gm
            old = mem["group_mid"].get(fam, gm)
            mem["group_mid"][fam] = (1 - GROUP_ALPHA) * old + GROUP_ALPHA * gm

        return dict(result), 0, self._save(mem)
