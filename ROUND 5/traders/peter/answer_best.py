import json
import math
from collections import defaultdict
from typing import Dict, List
from datamodel import Order, TradingState

# ANSWER_BEST.PY
# Combines:
#   - answer_oracle2.py shock-fade taker (best on day 2 + day 3 backtests):
#       per-product calibrated jump triggers, hold-N-ticks-then-exit.
#   - answer.py passive market maker + leader-lag skew (best on day 4):
#       quote inside spread, inventory-skew fair, GALAXY→SLEEP_POD lag bleed.
#   - answer_better.py improvements:
#       per-family position limits, microprice, EWMA fair, vol-aware skew,
#       family aggregate cap, opportunistic taker, self-cross guard,
#       regression-β leader-lag, spread-floor on MM.
# Layer order each tick: (1) exit aging fade trade, (2) detect new shock & take,
# (3) opportunistic micro-take vs fair, (4) passive MM around fair.

# ---------------- Position limits ----------------
DEFAULT_LIMIT = 20
FAMILY_LIMITS = {
    "PEBBLES": 45, "MICROCHIP": 40, "ROBOT": 35, "OXYGEN_SHAKE": 30,
    "PANEL": 30, "GALAXY_SOUNDS": 25, "TRANSLATOR": 25, "SLEEP_POD": 25,
    "UV_VISOR": 25, "SNACKPACK": 20,
}
FAMILY_PREFIXES = list(FAMILY_LIMITS.keys())

# ---------------- Leader-lag ----------------
LEADER = "GALAXY_SOUNDS_BLACK_HOLES"
LAG = "SLEEP_POD_POLYESTER"
LL_LOOKBACK = 100
LL_RECENT = 20
LL_GAIN = 0.15

# ---------------- Fair / vol ----------------
EWMA_ALPHA = 0.30
VOL_ALPHA = 0.10
INV_SKEW_BASE = 0.25
TAKE_EDGE_MULT = 1.0
MM_CLIP = 5
MAX_TAKE = 8

# ---------------- Shock-fade (from answer_oracle2) ----------------
HOLD_TICKS = 2     # ticks (each = 100ms) to hold the fade
SHOCK_PARAMS = {
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
SHOCK_QTY_BIG = 10
SHOCK_QTY_SMALL = 5


def family_of(sym: str) -> str:
    for p in FAMILY_PREFIXES:
        if sym.startswith(p): return p
    return sym


class Trader:
    def _empty(self) -> Dict:
        return {
            "last_ts": -1,
            "bh_hist": [],
            "poly_hist": [],
            "fair": {},
            "vol": {},
            "last_mid": {},
            "et": {},        # active fade entries: sym -> {ts, dir}
        }

    def _load(self, td: str) -> Dict:
        if not td: return self._empty()
        try:
            mem = json.loads(td)
            for k, v in self._empty().items(): mem.setdefault(k, v)
            return mem
        except Exception:
            return self._empty()

    def _save(self, mem: Dict) -> str:
        mem["bh_hist"] = mem["bh_hist"][-LL_LOOKBACK:]
        mem["poly_hist"] = mem["poly_hist"][-LL_LOOKBACK:]
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders: return None, None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys()), d

    def _microprice(self, d, bb: int, ba: int) -> float:
        bv = abs(d.buy_orders.get(bb, 0))
        av = abs(d.sell_orders.get(ba, 0))
        tot = bv + av
        if tot <= 0: return (bb + ba) / 2.0
        return (bb * av + ba * bv) / tot

    def _ll_skew(self, mem: Dict) -> float:
        bh = mem["bh_hist"]; poly = mem["poly_hist"]
        if len(bh) < LL_RECENT + 5 or len(poly) < LL_RECENT + 5: return 0.0
        mom = bh[-1] - bh[-LL_RECENT]
        n = min(len(bh), len(poly))
        bx = bh[-n:]; px = poly[-n:]
        bm = sum(bx) / n; pm = sum(px) / n
        cov = sum((bx[i] - bm) * (px[i] - pm) for i in range(n))
        bvar = sum((bx[i] - bm) ** 2 for i in range(n)) or 1e-9
        beta = max(-2.0, min(2.0, cov / bvar))
        return mom * beta * LL_GAIN

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem = self._empty()
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        # LL leader/lag tracking
        bb_l, ba_l, _ = self._bba(state, LEADER)
        bb_p, ba_p, _ = self._bba(state, LAG)
        if bb_l is not None: mem["bh_hist"].append((bb_l + ba_l) / 2.0)
        if bb_p is not None: mem["poly_hist"].append((bb_p + ba_p) / 2.0)
        ll_skew = self._ll_skew(mem)

        # Family-level positions
        fam_pos = defaultdict(int)
        for s, p in state.position.items():
            fam_pos[family_of(s)] += abs(p)

        for sym, depth in state.order_depths.items():
            bb, ba, d = self._bba(state, sym)
            if bb is None: continue
            spread = ba - bb
            mid = (bb + ba) / 2.0
            mp = self._microprice(d, bb, ba)
            pos = state.position.get(sym, 0)

            # Vol EWMA on mid jumps
            last_mid = mem["last_mid"].get(sym, mid)
            dmid = mid - last_mid
            inst_vol = abs(dmid)
            vol = mem["vol"].get(sym, 1.0)
            vol = (1 - VOL_ALPHA) * vol + VOL_ALPHA * inst_vol
            mem["vol"][sym] = max(vol, 0.5)
            mem["last_mid"][sym] = mid

            # Fair = EWMA(microprice)
            fair_prev = mem["fair"].get(sym, mp)
            fair = (1 - EWMA_ALPHA) * fair_prev + EWMA_ALPHA * mp
            mem["fair"][sym] = fair

            inv_skew = INV_SKEW_BASE * max(1.0, min(3.0, vol))
            f = fair - inv_skew * pos
            if sym == LAG: f += ll_skew

            fam = family_of(sym)
            fam_lim = FAMILY_LIMITS.get(fam, DEFAULT_LIMIT)
            sym_lim = fam_lim
            fam_room = max(0, fam_lim - fam_pos[fam])
            buy_room = min(sym_lim - pos, fam_room)
            sell_room = min(sym_lim + pos, fam_room)

            # ===== Layer 1: Exit aging fade =====
            entry = mem["et"].get(sym)
            if entry:
                if state.timestamp >= entry["ts"] + (HOLD_TICKS * 100):
                    if pos > 0: result[sym].append(Order(sym, bb, -pos))
                    elif pos < 0: result[sym].append(Order(sym, ba, -pos))
                    mem["et"].pop(sym, None)
                continue  # while holding fade, skip MM

            # ===== Layer 2: New shock detection =====
            cfg = SHOCK_PARAMS.get(sym)
            if cfg and pos == 0 and abs(dmid) >= cfg["trig"] and spread <= cfg["mx_spr"]:
                qty = SHOCK_QTY_BIG if abs(dmid) > cfg["trig"] * 1.5 else SHOCK_QTY_SMALL
                qty = min(qty, sym_lim, fam_room)
                if qty > 0:
                    if dmid > 0:  # spike up → fade short, hit bid
                        result[sym].append(Order(sym, bb, -qty))
                    else:         # drop → fade long, lift ask
                        result[sym].append(Order(sym, ba, qty))
                    mem["et"][sym] = {"ts": state.timestamp}
                    fam_pos[fam] += qty
                    continue

            # ===== Layer 3: Opportunistic micro-take vs fair =====
            take_edge = TAKE_EDGE_MULT * mem["vol"][sym]
            if bb > f + take_edge and sell_room > 0:
                qty = min(MAX_TAKE, sell_room, abs(d.buy_orders.get(bb, 0)))
                if qty > 0:
                    result[sym].append(Order(sym, bb, -qty))
                    sell_room -= qty
                    fam_pos[fam] += qty
            if ba < f - take_edge and buy_room > 0:
                qty = min(MAX_TAKE, buy_room, abs(d.sell_orders.get(ba, 0)))
                if qty > 0:
                    result[sym].append(Order(sym, ba, qty))
                    buy_room -= qty
                    fam_pos[fam] += qty

            # ===== Layer 4: Passive MM =====
            if spread < 2:
                continue  # no edge inside spread=1
            mm_bid = int(math.floor(f))
            mm_ask = mm_bid + 1
            if math.ceil(f) > mm_bid: mm_ask = int(math.ceil(f))
            mm_bid = min(mm_bid, ba - 1)
            mm_ask = max(mm_ask, bb + 1)
            if mm_bid >= mm_ask: mm_bid = mm_ask - 1

            clip = MM_CLIP
            if buy_room > 0:
                result[sym].append(Order(sym, mm_bid, min(clip, buy_room)))
            if sell_room > 0:
                result[sym].append(Order(sym, mm_ask, -min(clip, sell_room)))

        return dict(result), 0, self._save(mem)
