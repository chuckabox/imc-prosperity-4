import json
import math
from collections import defaultdict
from typing import Dict, List
from datamodel import Order, TradingState

# ANSWER_WINNER.PY
# Baseline = answer.py (best so far): universal passive MM with inv-skew + LL skew on LAG.
# Additive layer = shock-fade taker on a strict Tier-A whitelist, gated by spread.
# Why these alphas:
#   - ken_round5_alpha_sweep.md: robust winner is `reversal` thr=8, hold=1-3.
#   - volatility.md: ROBOT/TRANSLATOR/PANEL are Tier 1 (low spread, high signal quality).
#   - round5_alpha_selection.md: hard symbol cap 10 (algo.md), recommended family caps.
#   - round5_execution_playbook.md: dynamic trigger max(8, k*spread), default hold=1.
# Constraints:
#   - |pos[sym]| <= 10 (algo.md hard cap)
#   - keep answer.py MM exactly as-is so we never regress below it.

LIMIT = 10
MM_CLIP = 5
INV_SKEW = 0.25
LEADER = "GALAXY_SOUNDS_BLACK_HOLES"
LAG = "SLEEP_POD_POLYESTER"
LL_LOOKBACK = 100
LL_GAIN = 0.1

# Tier A — proven low-cost, high-signal symbols (volatility.md final whitelist).
TIER_A = {
    "ROBOT_DISHES", "ROBOT_IRONING", "ROBOT_VACUUMING", "ROBOT_LAUNDRY", "ROBOT_MOPPING",
    "TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
    "TRANSLATOR_SPACE_GRAY", "TRANSLATOR_VOID_BLUE",
    "PANEL_2X2", "PANEL_2X4", "PANEL_4X4",
}
# Tier B event-only — bigger moves, stricter gate.
TIER_B = {
    "MICROCHIP_OVAL", "MICROCHIP_RECTANGLE", "MICROCHIP_CIRCLE", "MICROCHIP_TRIANGLE",
}

# Shock-fade per-tier params (alpha sweep robust winner: thr=8, hold=1).
SHOCK_TRIG_BASE = 8.0
SHOCK_K_SPREAD = 1.2          # dynamic trigger = max(BASE, K*spread)
SHOCK_SPREAD_MAX_A = 9        # Tier A spread gate
SHOCK_SPREAD_MAX_B = 11       # Tier B stricter
SHOCK_CLIP_A = 4
SHOCK_CLIP_B = 3
HOLD_TICKS = 1                 # close after 1 tick (100ms)

FAMILY_PREFIXES = ["PEBBLES", "SNACKPACK", "UV_VISOR", "GALAXY_SOUNDS", "MICROCHIP",
                   "TRANSLATOR", "SLEEP_POD", "OXYGEN_SHAKE", "PANEL", "ROBOT"]
# Soft family caps (sum of |pos| per family) — gate fade entries only, not MM.
FAMILY_CAPS = {"ROBOT": 25, "TRANSLATOR": 25, "PANEL": 15, "MICROCHIP": 15}


def family_of(sym: str) -> str:
    for p in FAMILY_PREFIXES:
        if sym.startswith(p): return p
    return sym


class Trader:
    def _load(self, td: str) -> Dict:
        if not td: return self._empty()
        try:
            mem = json.loads(td)
            for k, v in self._empty().items(): mem.setdefault(k, v)
            return mem
        except Exception:
            return self._empty()

    def _empty(self) -> Dict:
        return {
            "last_ts": -1,
            "bh_hist": [],
            "poly_hist": [],
            "lm": {},        # last mid per sym (shock detection)
            "et": {},        # active fade entries: sym -> {ts}
        }

    def _save(self, mem: Dict) -> str:
        mem["bh_hist"] = mem["bh_hist"][-LL_LOOKBACK:]
        mem["poly_hist"] = mem["poly_hist"][-LL_LOOKBACK:]
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders: return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def _corr_sign(self, x: List[float], y: List[float]) -> float:
        if len(x) < 50 or len(y) < 50: return 1.0
        n = min(len(x), len(y))
        xm, ym = sum(x[-n:]) / n, sum(y[-n:]) / n
        cov = sum((x[-i] - xm) * (y[-i] - ym) for i in range(1, n + 1))
        return 1.0 if cov >= 0 else -1.0

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem = self._empty()
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        # 1. Leader-Lag tracking (unchanged from answer.py)
        bh_bid, bh_ask = self._bba(state, LEADER)
        poly_bid, poly_ask = self._bba(state, LAG)
        if bh_bid and bh_ask: mem["bh_hist"].append((bh_bid + bh_ask) / 2.0)
        if poly_bid and poly_ask: mem["poly_hist"].append((poly_bid + poly_ask) / 2.0)

        ll_skew = 0.0
        if len(mem["bh_hist"]) >= LL_LOOKBACK:
            move = mem["bh_hist"][-1] - mem["bh_hist"][0]
            sign = self._corr_sign(mem["bh_hist"], mem["poly_hist"])
            ll_skew = move * sign * LL_GAIN

        # Family aggregate positions (for fade gate only)
        fam_pos = defaultdict(int)
        for s, p in state.position.items():
            fam_pos[family_of(s)] += abs(p)

        # Symbols currently exiting fade (we'll skip MM for these this tick)
        exiting_fade = set()

        # 2. Shock-fade overlay (Tier A + Tier B only)
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
                    exiting_fade.add(sym)
                else:
                    exiting_fade.add(sym)  # still holding, skip MM
                continue

            # Entry: only Tier A or Tier B, only when flat
            if pos != 0: continue
            if sym not in TIER_A and sym not in TIER_B: continue

            spread_max = SHOCK_SPREAD_MAX_A if sym in TIER_A else SHOCK_SPREAD_MAX_B
            clip = SHOCK_CLIP_A if sym in TIER_A else SHOCK_CLIP_B
            if spread > spread_max: continue

            trigger = max(SHOCK_TRIG_BASE, SHOCK_K_SPREAD * spread)
            if abs(dmid) < trigger: continue

            # Family cap gate
            fam = family_of(sym)
            cap = FAMILY_CAPS.get(fam, 999)
            if fam_pos[fam] + clip > cap: continue

            if dmid > 0:  # spike up → fade short, hit bid
                result[sym].append(Order(sym, bid, -clip))
            else:         # drop → fade long, lift ask
                result[sym].append(Order(sym, ask, clip))
            mem["et"][sym] = {"ts": state.timestamp}
            fam_pos[fam] += clip
            exiting_fade.add(sym)  # don't double-quote MM this tick

        # 3. Universal Passive MM (unchanged from answer.py)
        for sym in state.order_depths.keys():
            if sym in exiting_fade: continue  # avoid conflict with active fade trade
            bid, ask = self._bba(state, sym)
            if bid is None: continue
            mid = (bid + ask) / 2.0
            pos = state.position.get(sym, 0)

            fair = mid - (INV_SKEW * pos)
            if sym == LAG: fair += ll_skew

            mm_bid = min(int(round(fair - 1)), ask - 1)
            mm_ask = max(int(round(fair + 1)), bid + 1)

            if pos < LIMIT:
                result[sym].append(Order(sym, mm_bid, min(MM_CLIP, LIMIT - pos)))
            if pos > -LIMIT:
                result[sym].append(Order(sym, mm_ask, -min(MM_CLIP, LIMIT + pos)))

        return dict(result), 0, self._save(mem)
