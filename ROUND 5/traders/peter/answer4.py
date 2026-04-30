import json
import math
from collections import defaultdict
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

# ANSWER4.PY: Corrected Lead-Lag Group Ratio Strategy
# Target: ~2.8M Profit
# Logic: Self lags Group. Trade Self based on Group's previous move.
# Tuning: Fast exit (1-tick) to minimize drift risk.

SYM_LIMIT = 10
WARMUP = 100

# EWMA Parameters
RATIO_ALPHA = 0.005
VAR_ALPHA   = 0.01
GROUP_ALPHA = 0.05

# Trading Parameters
Z_ENTER = 1.8
Z_EXIT  = 0.2
HOLD_TICKS = 1

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

MEMBER_TO_FAM = {}
for fam, members in FAMILY_MEMBERS.items():
    for m in members: MEMBER_TO_FAM[m] = fam

class Trader:
    def _load(self, td: str) -> Dict:
        if not td: return self._empty()
        try:
            mem = json.loads(td)
            if "r" not in mem: return self._empty()
            return mem
        except: return self._empty()

    def _empty(self) -> Dict:
        return {"r": {}, "v": {}, "gp": {}, "et": {}, "n": {}, "ts": -1}

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders: return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["ts"] >= 0 and state.timestamp < mem["ts"]: mem = self._empty()
        mem["ts"] = state.timestamp
        
        mids = {}
        bbas = {}
        for sym in state.order_depths:
            bid, ask = self._bba(state, sym)
            if bid is not None: 
                mids[sym] = (bid + ask) / 2.0
                bbas[sym] = (bid, ask)

        gm_now = {}
        for fam, members in FAMILY_MEMBERS.items():
            vals = [mids[m] for m in members if m in mids]
            if vals: gm_now[fam] = sum(vals) / len(vals)

        result: Dict[str, List[Order]] = defaultdict(list)

        for sym, mid in mids.items():
            fam = MEMBER_TO_FAM.get(sym)
            if not fam or fam not in gm_now: continue

            g_now = gm_now[fam]
            g_prev = mem["gp"].get(fam, g_now)
            
            # Predict mid_t using LAGGED Group Mid and LAGGED Ratio
            ratio = mem["r"].get(sym, mid / g_now if g_now > 0 else 1.0)
            pred = g_prev * ratio
            err = mid - pred
            
            # Update Variance (Rolling sigma)
            var = mem["v"].get(sym, 1.0)
            var = (1 - VAR_ALPHA) * var + VAR_ALPHA * (err * err)
            mem["v"][sym] = var
            
            # Update Ratio for next tick
            mem["r"][sym] = (1 - RATIO_ALPHA) * ratio + RATIO_ALPHA * (mid / g_now if g_now > 0 else ratio)
            
            n = mem["n"].get(sym, 0) + 1
            mem["n"][sym] = n
            
            pos = state.position.get(sym, 0)
            bid, ask = bbas[sym]
            entry_ts = mem["et"].get(sym, -1)

            # EXIT: Hold for 1 tick to capture the converging jump
            if pos != 0:
                age = (state.timestamp - entry_ts) // 100
                if age >= HOLD_TICKS:
                    if pos > 0: result[sym].append(Order(sym, bid, -pos))
                    else: result[sym].append(Order(sym, ask, -pos))
                    mem["et"][sym] = -1
                continue

            # ENTRY: Residual Shock
            if n > WARMUP:
                sigma = math.sqrt(max(var, 1e-9))
                z = err / sigma if sigma > 0.1 else 0.0
                
                # Signal must cover the spread and be statistically rare
                if abs(z) > Z_ENTER and abs(err) > (ask - bid) * 1.1:
                    if z > 0: # Overpriced -> Sell (Hit Bid)
                        result[sym].append(Order(sym, bid, -SYM_LIMIT))
                    else: # Underpriced -> Buy (Hit Ask)
                        result[sym].append(Order(sym, ask, SYM_LIMIT))
                    mem["et"][sym] = state.timestamp

        # Update memories
        for fam, g in gm_now.items(): mem["gp"][fam] = g

        return dict(result), 0, self._save(mem)
