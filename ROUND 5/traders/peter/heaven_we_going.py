import json
from collections import defaultdict
from typing import Dict, List

from datamodel import Order, TradingState

# heaven_we_going.py — improvements over ken/heaven_we_comingv5a.py:
#   1. Fix _family() bug: split("_",1)[0] mis-keys SLEEP_POD/OXYGEN_SHAKE/
#      GALAXY_SOUNDS/UV_VISOR. Use prefix-table lookup so spread caps actually apply.
#   2. Skip MM on Tier C symbols (volatility.md: SNACKPACK / GALAXY_SOUNDS /
#      UV_VISOR except AMBER+ORANGE). Negative or unreachable signal under cost.
#   3. Add Tier-A/B shock-fade overlay (ken_round5_alpha_sweep.md: reversal
#      thr=8 hold=1 is the robust winner across day 2/3/4). Pure MM misses it.
#   4. Stronger LL skew: short-window (20 tick) momentum + magnitude-aware β,
#      clamped same as v5a.
#   5. Tier-A MM clip bumped to 5 (was 4) — these are the cleanest names.
# Untouched (don't break what works): LIMIT=10, INV_SKEW=0.30, LL_SKEW_CAP=3.0,
#   spread-cap thresholds, passive-MM quote shape, return tuple.

LIMIT = 10
MM_CLIP_DEFAULT = 4
MM_CLIP_TIER_A = 5
INV_SKEW = 0.30
LEADER = "GALAXY_SOUNDS_BLACK_HOLES"
LAG = "SLEEP_POD_POLYESTER"
LL_LOOKBACK = 100
LL_RECENT = 20
LL_MULT = 0.10
LL_SKEW_CAP = 3.0

FAMILY_PREFIXES = [
    "GALAXY_SOUNDS", "SLEEP_POD", "OXYGEN_SHAKE", "UV_VISOR",
    "PEBBLES", "MICROCHIP", "TRANSLATOR", "PANEL", "ROBOT", "SNACKPACK",
]

FAMILY_SPREAD_CAPS = {
    "ROBOT": 8,
    "TRANSLATOR": 10,
    "PANEL": 10,
    "MICROCHIP": 10,
    "SLEEP_POD": 11,
    "OXYGEN_SHAKE": 12,
    "PEBBLES": 12,
    "UV_VISOR": 12,
    "GALAXY_SOUNDS": 12,
    "SNACKPACK": 12,
}
DEFAULT_SPREAD_CAP = 12

# Tier C — skip MM entirely (volatility.md). Allow LEADER through for LL signal,
# allow UV_VISOR_AMBER + UV_VISOR_ORANGE (only marginally tradable visors).
TIER_C_SKIP = set()
for s in ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
          "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"]:
    TIER_C_SKIP.add(s)
for s in ["GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_PLANETARY_RINGS",
          "GALAXY_SOUNDS_SOLAR_FLAMES", "GALAXY_SOUNDS_SOLAR_WINDS"]:
    TIER_C_SKIP.add(s)  # keep BLACK_HOLES (LEADER) for LL tracking
for s in ["UV_VISOR_YELLOW", "UV_VISOR_RED", "UV_VISOR_MAGENTA"]:
    TIER_C_SKIP.add(s)
# Also skip PEBBLES_XL (signal_quality = -0.031 per item_over_time summary).
TIER_C_SKIP.add("PEBBLES_XL")

# Tier A — strongest signal-quality whitelist (volatility.md final 13).
TIER_A = {
    "ROBOT_DISHES", "ROBOT_IRONING", "ROBOT_VACUUMING", "ROBOT_LAUNDRY", "ROBOT_MOPPING",
    "TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
    "TRANSLATOR_SPACE_GRAY", "TRANSLATOR_VOID_BLUE",
    "PANEL_2X2", "PANEL_2X4", "PANEL_4X4",
}
# Tier B — event-only shock fade (round5_alpha_selection.md).
TIER_B = {"MICROCHIP_OVAL", "MICROCHIP_RECTANGLE", "MICROCHIP_CIRCLE", "MICROCHIP_TRIANGLE"}

# Shock-fade params (alpha sweep robust winner: thr=8, hold=1).
SHOCK_TRIG_BASE = 8.0
SHOCK_K_SPREAD = 1.2          # dynamic trigger = max(BASE, K*spread)
SHOCK_SPREAD_MAX_A = 9
SHOCK_SPREAD_MAX_B = 11
SHOCK_CLIP_A = 4
SHOCK_CLIP_B = 3
HOLD_TICKS = 1                # close after 1 tick (100ms)

# Family soft caps (sum |pos|) — gate fade entries only.
FAMILY_CAPS_FADE = {"ROBOT": 25, "TRANSLATOR": 25, "PANEL": 15, "MICROCHIP": 15}


def family_of(sym: str) -> str:
    for p in FAMILY_PREFIXES:
        if sym.startswith(p): return p
    return sym


class Trader:
    def _empty(self) -> Dict:
        return {"last_ts": -1, "bh_hist": [], "poly_hist": [], "lm": {}, "et": {}}

    def _load(self, td: str) -> Dict:
        if not td: return self._empty()
        try:
            mem = json.loads(td)
        except Exception:
            return self._empty()
        for k, v in self._empty().items():
            mem.setdefault(k, v)
        return mem

    def _save(self, mem: Dict) -> str:
        mem["bh_hist"] = mem["bh_hist"][-LL_LOOKBACK:]
        mem["poly_hist"] = mem["poly_hist"][-LL_LOOKBACK:]
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders:
            return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def _ll_skew(self, mem: Dict) -> float:
        bh = mem["bh_hist"]; poly = mem["poly_hist"]
        if len(bh) < LL_RECENT + 5 or len(poly) < LL_RECENT + 5: return 0.0
        # short-window momentum (more responsive than endpoint diff)
        mom = bh[-1] - bh[-LL_RECENT]
        # magnitude-aware regression β over full window
        n = min(len(bh), len(poly))
        bx = bh[-n:]; px = poly[-n:]
        bm = sum(bx) / n; pm = sum(px) / n
        cov = sum((bx[i] - bm) * (px[i] - pm) for i in range(n))
        bvar = sum((bx[i] - bm) ** 2 for i in range(n)) or 1e-9
        beta = max(-2.0, min(2.0, cov / bvar))
        skew = mom * beta * LL_MULT
        if skew > LL_SKEW_CAP: skew = LL_SKEW_CAP
        elif skew < -LL_SKEW_CAP: skew = -LL_SKEW_CAP
        return skew

    def _spread_cap(self, sym: str) -> int:
        return FAMILY_SPREAD_CAPS.get(family_of(sym), DEFAULT_SPREAD_CAP)

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem = self._empty()
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        # Leader-Lag tracking
        bh_bid, bh_ask = self._bba(state, LEADER)
        poly_bid, poly_ask = self._bba(state, LAG)
        if bh_bid is not None and bh_ask is not None:
            mem["bh_hist"].append((bh_bid + bh_ask) / 2.0)
        if poly_bid is not None and poly_ask is not None:
            mem["poly_hist"].append((poly_bid + poly_ask) / 2.0)
        ll_skew = self._ll_skew(mem)

        # Family aggregate positions (fade gate only)
        fam_pos = defaultdict(int)
        for s, p in state.position.items():
            fam_pos[family_of(s)] += abs(p)

        skip_mm_this_tick = set()

        # ---- Shock-fade overlay: Tier A + Tier B only ----
        for sym in list(state.order_depths.keys()):
            bid, ask = self._bba(state, sym)
            if bid is None: continue
            mid = (bid + ask) / 2.0
            spread = ask - bid
            pos = state.position.get(sym, 0)

            last_mid = mem["lm"].get(sym, mid)
            dmid = mid - last_mid
            mem["lm"][sym] = mid

            # Exit aging fade
            entry = mem["et"].get(sym)
            if entry:
                if state.timestamp >= entry["ts"] + (HOLD_TICKS * 100):
                    if pos > 0: result[sym].append(Order(sym, bid, -pos))
                    elif pos < 0: result[sym].append(Order(sym, ask, -pos))
                    mem["et"].pop(sym, None)
                skip_mm_this_tick.add(sym)
                continue

            # Entry conditions
            if pos != 0: continue
            if sym not in TIER_A and sym not in TIER_B: continue
            spread_max = SHOCK_SPREAD_MAX_A if sym in TIER_A else SHOCK_SPREAD_MAX_B
            clip = SHOCK_CLIP_A if sym in TIER_A else SHOCK_CLIP_B
            if spread > spread_max: continue
            trigger = max(SHOCK_TRIG_BASE, SHOCK_K_SPREAD * spread)
            if abs(dmid) < trigger: continue

            fam = family_of(sym)
            cap = FAMILY_CAPS_FADE.get(fam, 999)
            if fam_pos[fam] + clip > cap: continue

            if dmid > 0:  # spike up → fade short
                result[sym].append(Order(sym, bid, -clip))
            else:         # drop → fade long
                result[sym].append(Order(sym, ask, clip))
            mem["et"][sym] = {"ts": state.timestamp}
            fam_pos[fam] += clip
            skip_mm_this_tick.add(sym)

        # ---- Passive MM (v5a core, with Tier C skip + tier-aware clip) ----
        for sym in state.order_depths.keys():
            if sym in skip_mm_this_tick: continue
            if sym in TIER_C_SKIP: continue
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None: continue
            spread = ask - bid
            if spread <= 0 or spread > self._spread_cap(sym): continue

            mid = (bid + ask) / 2.0
            pos = state.position.get(sym, 0)
            fair = mid - (INV_SKEW * pos)
            if sym == LAG:
                fair += ll_skew

            if spread >= 2:
                mm_bid = min(int(round(fair - 1)), ask - 1)
                mm_ask = max(int(round(fair + 1)), bid + 1)
            else:
                mm_bid = bid
                mm_ask = ask

            if mm_bid >= ask: mm_bid = ask - 1
            if mm_ask <= bid: mm_ask = bid + 1
            if mm_bid >= mm_ask: continue

            clip = MM_CLIP_TIER_A if sym in TIER_A else MM_CLIP_DEFAULT
            if pos < LIMIT:
                result[sym].append(Order(sym, mm_bid, min(clip, LIMIT - pos)))
            if pos > -LIMIT:
                result[sym].append(Order(sym, mm_ask, -min(clip, LIMIT + pos)))

        return dict(result), 0, self._save(mem)
