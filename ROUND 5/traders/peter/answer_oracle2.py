import json
import math
from collections import defaultdict
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

# ANSWER_ORACLE2.PY: Reactive Shock-Fade + Passive MM
# FIX: Replaces hardcoded timestamps with dynamic jump-detection logic.
# Baseline: answer.py (Passive Market Maker)
# Improvement: Integrated Taker layer for large mid-price shocks.

class Trader:
    # Calibrated Jump Triggers (Learned from microstructure, but reactive)
    # These define what a 'shock' looks like for each product.
    PARAMS = {
        "GALAXY_SOUNDS_BLACK_HOLES":       {"trig": 14.5, "mx_spr": 20},
        "GALAXY_SOUNDS_DARK_MATTER":       {"trig": 13.0, "mx_spr": 19},
        "GALAXY_SOUNDS_PLANETARY_RINGS":   {"trig": 13.5, "mx_spr": 19},
        "GALAXY_SOUNDS_SOLAR_FLAMES":      {"trig": 13.0, "mx_spr": 19},
        "GALAXY_SOUNDS_SOLAR_WINDS":       {"trig": 13.5, "mx_spr": 19},
        "MICROCHIP_CIRCLE":                {"trig": 10.0, "mx_spr": 13},
        "MICROCHIP_OVAL":                  {"trig": 12.5, "mx_spr": 12},
        "MICROCHIP_RECTANGLE":             {"trig": 14.5, "mx_spr": 13},
        "MICROCHIP_SQUARE":                {"trig": 29.0, "mx_spr": 19},
        "MICROCHIP_TRIANGLE":              {"trig": 13.0, "mx_spr": 14},
        "OXYGEN_SHAKE_CHOCOLATE":          {"trig": 10.5, "mx_spr": 17},
        "OXYGEN_SHAKE_EVENING_BREATH":     {"trig": 10.5, "mx_spr": 17},
        "OXYGEN_SHAKE_GARLIC":             {"trig": 14.0, "mx_spr": 20},
        "OXYGEN_SHAKE_MINT":               {"trig": 11.5, "mx_spr": 18},
        "OXYGEN_SHAKE_MORNING_BREATH":     {"trig": 11.5, "mx_spr": 18},
        "PANEL_1X2":                       {"trig": 10.5, "mx_spr": 16},
        "PANEL_1X4":                       {"trig": 10.0, "mx_spr": 13},
        "PANEL_2X2":                       {"trig": 11.0, "mx_spr": 13},
        "PANEL_2X4":                       {"trig": 13.5, "mx_spr": 15},
        "PANEL_4X4":                       {"trig": 12.5, "mx_spr": 15},
        "PEBBLES_L":                       {"trig": 18.0, "mx_spr": 19},
        "PEBBLES_M":                       {"trig": 18.0, "mx_spr": 19},
        "PEBBLES_S":                       {"trig": 17.5, "mx_spr": 17},
        "PEBBLES_XL":                      {"trig": 37.0, "mx_spr": 21},
        "PEBBLES_XS":                      {"trig": 18.0, "mx_spr": 15},
        "ROBOT_DISHES":                    {"trig": 12.5, "mx_spr": 13},
        "ROBOT_IRONING":                   {"trig":  9.5, "mx_spr": 11},
        "ROBOT_LAUNDRY":                   {"trig": 11.0, "mx_spr": 12},
        "ROBOT_MOPPING":                   {"trig": 14.0, "mx_spr": 14},
        "ROBOT_VACUUMING":                 {"trig": 10.0, "mx_spr": 12},
        "SLEEP_POD_COTTON":                {"trig": 14.5, "mx_spr": 16},
        "SLEEP_POD_LAMB_WOOL":             {"trig": 12.5, "mx_spr": 15},
        "SLEEP_POD_NYLON":                 {"trig": 11.5, "mx_spr": 14},
        "SLEEP_POD_POLYESTER":             {"trig": 15.5, "mx_spr": 17},
        "SLEEP_POD_SUEDE":                 {"trig": 14.5, "mx_spr": 16},
        "SNACKPACK_CHOCOLATE":             {"trig":  8.0, "mx_spr": 22},
        "SNACKPACK_PISTACHIO":             {"trig":  6.5, "mx_spr": 22},
        "SNACKPACK_RASPBERRY":             {"trig":  9.5, "mx_spr": 23},
        "SNACKPACK_STRAWBERRY":            {"trig": 10.0, "mx_spr": 24},
        "SNACKPACK_VANILLA":               {"trig":  8.0, "mx_spr": 23},
        "TRANSLATOR_ASTRO_BLACK":          {"trig": 11.0, "mx_spr": 14},
        "TRANSLATOR_ECLIPSE_CHARCOAL":     {"trig": 11.5, "mx_spr": 14},
        "TRANSLATOR_GRAPHITE_MIST":        {"trig": 13.0, "mx_spr": 15},
        "TRANSLATOR_SPACE_GRAY":           {"trig": 12.0, "mx_spr": 14},
        "TRANSLATOR_VOID_BLUE":            {"trig": 12.5, "mx_spr": 15},
        "UV_VISOR_AMBER":                  {"trig":  9.0, "mx_spr": 15},
        "UV_VISOR_MAGENTA":                {"trig": 13.0, "mx_spr": 20},
        "UV_VISOR_ORANGE":                 {"trig": 12.5, "mx_spr": 19},
        "UV_VISOR_RED":                    {"trig": 13.5, "mx_spr": 20},
        "UV_VISOR_YELLOW":                 {"trig": 14.5, "mx_spr": 21},
    }

    SYM_LIMIT = 10
    INV_SKEW = 0.25
    HOLD_TICKS = 2

    def _load(self, td: str) -> Dict:
        if not td: return self._empty()
        try:
            mem = json.loads(td)
            for k, v in self._empty().items(): mem.setdefault(k, v)
            return mem
        except: return self._empty()

    def _empty(self) -> Dict:
        return {"lm": {}, "et": {}, "ts": -1}

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
        
        result: Dict[str, List[Order]] = defaultdict(list)

        for sym in state.order_depths.keys():
            bid, ask = self._bba(state, sym)
            if bid is None: continue
            mid = (bid + ask) / 2.0
            pos = state.position.get(sym, 0)
            
            # 1. ALPHA: SHOCK DETECTION (Taker)
            last_mid = mem["lm"].get(sym, mid)
            dmid = mid - last_mid
            mem["lm"][sym] = mid
            
            entry = mem["et"].get(sym)
            if entry:
                # Active trade: Hold for N ticks then exit
                if state.timestamp >= entry["ts"] + (self.HOLD_TICKS * 100):
                    if pos > 0: result[sym].append(Order(sym, bid, -pos))
                    elif pos < 0: result[sym].append(Order(sym, ask, -pos))
                    mem["et"].pop(sym)
                continue # Skip MM layer while fading
            
            # Signal entry: If price 'jumps' more than product trigger
            if sym in self.PARAMS:
                cfg = self.PARAMS[sym]
                if abs(dmid) >= cfg["trig"] and (ask - bid) <= cfg["mx_spr"] and pos == 0:
                    qty = 10 if abs(dmid) > cfg["trig"] * 1.5 else 5
                    if dmid > 0: # Spike -> Sell (Hit Bid)
                        result[sym].append(Order(sym, bid, -qty))
                    else: # Drop -> Buy (Hit Ask)
                        result[sym].append(Order(sym, ask, qty))
                    mem["et"][sym] = {"ts": state.timestamp}
                    continue

            # 2. BASELINE: PASSIVE MM (Maker)
            # Quoting around mid with inventory skew
            fair = mid - (self.INV_SKEW * pos)
            mm_bid = min(int(round(fair - 1)), ask - 1)
            mm_ask = max(int(round(fair + 1)), bid + 1)
            
            if pos < self.SYM_LIMIT:
                result[sym].append(Order(sym, mm_bid, self.SYM_LIMIT - pos))
            if pos > -self.SYM_LIMIT:
                result[sym].append(Order(sym, mm_ask, -(self.SYM_LIMIT + pos)))

        return dict(result), 0, self._save(mem)
