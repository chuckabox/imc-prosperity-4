import json
from collections import defaultdict
from typing import Dict, List

from datamodel import Order, TradingState

# peter_heaven2.py — base = peter_heaven.py.
# algo.md: per-symbol |pos| <= 10. No constraint to skip products. So trade
# all 50; rely on alpha quality and clip sizing to keep losers small.
#
# Layered passive alphas (every layer is FAIR-PRICE adjustment, no taker):
#   A. Family-residual pull  — from family_et charts. e_t (sym - family_mean)
#      mean-reverts ±3z across all 10 families. Pulls fair toward expected
#      residual. (kept from peter_heaven.py)
#   B. Microprice anchor     — fair blends mid + microprice (book imbalance).
#      Captures direction implied by L1 volumes before market moves.
#   C. Self mean-revert pull — per-symbol EWMA of mid; when mid deviates,
#      pull fair toward the EWMA mean. Per-item charts show every symbol's
#      mid range-bounded over 100k ticks → reversion is universal.
#   D. Leader-Lag skew       — GALAXY_SOUNDS_BLACK_HOLES → SLEEP_POD_POLYESTER
#      kept from v5a (recent-momentum × β-clamped).
#
# Tier-aware sizing (NOT skipping anymore):
#   - Tier A (proven low spread, high quality): clip 5
#   - Tier B (event-driven, wider spread):       clip 3
#   - Tier C (Snackpack / wide UV / Galaxy etc): clip 2
#   - Empirical bleeders (3/3 days neg in last run): clip 1
# All 50 products quote when their spread fits the family cap.
#
# No taker overlays (pair-conv + shock-fade bled 2026-04-30 backtest).

LIMIT = 10
INV_SKEW = 0.30
LEADER = "GALAXY_SOUNDS_BLACK_HOLES"
LAG = "SLEEP_POD_POLYESTER"
LL_LOOKBACK = 100
LL_RECENT = 20
LL_MULT = 0.10
LL_SKEW_CAP = 3.0

# Family-residual EWMA
RESID_EWMA_MU = 0.02
RESID_EWMA_VAR = 0.01
RESID_GAIN = 0.30
RESID_CAP = 3.0

# Microprice blend
MICRO_BLEND = 0.40           # fair = (1-blend)*mid + blend*microprice

# Self mean-revert
SELF_EWMA = 0.02             # ~50 ticks
SELF_GAIN = 0.20
SELF_CAP = 2.0

FAMILY_PREFIXES = [
    "GALAXY_SOUNDS", "SLEEP_POD", "OXYGEN_SHAKE", "UV_VISOR",
    "PEBBLES", "MICROCHIP", "TRANSLATOR", "PANEL", "ROBOT", "SNACKPACK",
]

# Spread caps loosened so all 50 actually quote on average ticks.
FAMILY_SPREAD_CAPS = {
    "ROBOT": 9,
    "TRANSLATOR": 11,
    "PANEL": 11,
    "MICROCHIP": 12,
    "SLEEP_POD": 12,
    "OXYGEN_SHAKE": 14,
    "PEBBLES": 14,
    "UV_VISOR": 16,
    "GALAXY_SOUNDS": 16,
    "SNACKPACK": 20,
}
DEFAULT_SPREAD_CAP = 14

# Tier sets (for clip sizing)
TIER_A = {
    "ROBOT_DISHES", "ROBOT_IRONING", "ROBOT_VACUUMING", "ROBOT_LAUNDRY", "ROBOT_MOPPING",
    "TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
    "TRANSLATOR_SPACE_GRAY", "TRANSLATOR_VOID_BLUE",
    "PANEL_2X2", "PANEL_2X4", "PANEL_4X4", "PANEL_1X4",
}
TIER_B = {
    "MICROCHIP_OVAL", "MICROCHIP_RECTANGLE", "MICROCHIP_CIRCLE", "MICROCHIP_TRIANGLE",
    "MICROCHIP_SQUARE", "PEBBLES_S", "PEBBLES_XS", "PEBBLES_L", "PEBBLES_XL",
    "OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_EVENING_BREATH",
    "SLEEP_POD_NYLON", "SLEEP_POD_POLYESTER", "SLEEP_POD_SUEDE", "SLEEP_POD_COTTON",
    "PANEL_1X2",
}
# Empirical bleeders — quote tiny clip
BLEEDERS = {"SLEEP_POD_LAMB_WOOL", "PEBBLES_M", "OXYGEN_SHAKE_MINT"}
# Tier C (everything else: SNACKPACK, GALAXY non-leader, UV_VISOR_*, PEBBLES_XL,
# OXYGEN_SHAKE_GARLIC/MORNING_BREATH) — implicit; clip 2.

CLIP_TIER_A = 5
CLIP_TIER_B = 4
CLIP_TIER_C = 2
CLIP_BLEEDER = 1


def family_of(sym: str) -> str:
    for p in FAMILY_PREFIXES:
        if sym.startswith(p): return p
    return sym


def clip_for(sym: str) -> int:
    if sym in BLEEDERS: return CLIP_BLEEDER
    if sym in TIER_A: return CLIP_TIER_A
    if sym in TIER_B: return CLIP_TIER_B
    return CLIP_TIER_C


class Trader:
    def _empty(self) -> Dict:
        return {
            "last_ts": -1,
            "bh_hist": [], "poly_hist": [],
            "rmu": {}, "rv": {},      # family-residual EWMA per sym
            "smu": {}, "sv": {},      # self-mid EWMA per sym
        }

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
            return None, None, None
        bb = max(d.buy_orders.keys()); ba = min(d.sell_orders.keys())
        return bb, ba, d

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
        beta = cov / bvar
        if beta > 2.0: beta = 2.0
        elif beta < -2.0: beta = -2.0
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

        # --- Leader-Lag bookkeeping ---
        bb_l, ba_l, _ = self._bba(state, LEADER)
        bb_p, ba_p, _ = self._bba(state, LAG)
        if bb_l is not None: mem["bh_hist"].append((bb_l + ba_l) / 2.0)
        if bb_p is not None: mem["poly_hist"].append((bb_p + ba_p) / 2.0)
        ll_skew = self._ll_skew(mem)

        # --- Snapshot mids + family means (excluding bleeders so they don't bias) ---
        mids: Dict[str, float] = {}
        depths = {}
        for sym in state.order_depths.keys():
            bb, ba, d = self._bba(state, sym)
            if bb is None: continue
            mids[sym] = (bb + ba) / 2.0
            depths[sym] = (bb, ba, d)
        fam_sum = defaultdict(float)
        fam_cnt = defaultdict(int)
        for sym, mid in mids.items():
            if sym in BLEEDERS: continue  # divergent, biases mean
            fam = family_of(sym)
            fam_sum[fam] += mid
            fam_cnt[fam] += 1

        # --- Per-symbol pulls (family residual + self mean-revert) ---
        resid_pull: Dict[str, float] = {}
        self_pull: Dict[str, float] = {}
        for sym, mid in mids.items():
            # Family-residual pull
            fam = family_of(sym)
            if fam_cnt[fam] >= 3:
                fam_mean = fam_sum[fam] / fam_cnt[fam]
                resid = mid - fam_mean
                mu_prev = mem["rmu"].get(sym, resid)
                v_prev = mem["rv"].get(sym, 1.0)
                new_mu = (1 - RESID_EWMA_MU) * mu_prev + RESID_EWMA_MU * resid
                dev = resid - mu_prev
                new_v = (1 - RESID_EWMA_VAR) * v_prev + RESID_EWMA_VAR * (dev * dev)
                mem["rmu"][sym] = new_mu
                mem["rv"][sym] = new_v
                if v_prev >= 1.0:
                    pull = -RESID_GAIN * (resid - new_mu)
                    if pull > RESID_CAP: pull = RESID_CAP
                    elif pull < -RESID_CAP: pull = -RESID_CAP
                    resid_pull[sym] = pull

            # Self mean-revert pull
            smu_prev = mem["smu"].get(sym, mid)
            sv_prev = mem["sv"].get(sym, 1.0)
            new_smu = (1 - SELF_EWMA) * smu_prev + SELF_EWMA * mid
            sdev = mid - smu_prev
            new_sv = (1 - SELF_EWMA) * sv_prev + SELF_EWMA * (sdev * sdev)
            mem["smu"][sym] = new_smu
            mem["sv"][sym] = new_sv
            if sv_prev >= 1.0:
                spull = -SELF_GAIN * (mid - new_smu)
                if spull > SELF_CAP: spull = SELF_CAP
                elif spull < -SELF_CAP: spull = -SELF_CAP
                self_pull[sym] = spull

        # --- Passive MM on all 50 ---
        for sym in state.order_depths.keys():
            tup = depths.get(sym)
            if tup is None: continue
            bid, ask, d = tup
            spread = ask - bid
            if spread <= 0 or spread > self._spread_cap(sym): continue

            mid = mids[sym]
            mp = self._microprice(d, bid, ask)
            pos = state.position.get(sym, 0)

            # Compose fair from layers
            base = (1 - MICRO_BLEND) * mid + MICRO_BLEND * mp
            fair = base - (INV_SKEW * pos)
            if sym == LAG: fair += ll_skew
            fair += resid_pull.get(sym, 0.0)
            fair += self_pull.get(sym, 0.0)

            if spread >= 2:
                mm_bid = min(int(round(fair - 1)), ask - 1)
                mm_ask = max(int(round(fair + 1)), bid + 1)
            else:
                mm_bid = bid
                mm_ask = ask

            if mm_bid >= ask: mm_bid = ask - 1
            if mm_ask <= bid: mm_ask = bid + 1
            if mm_bid >= mm_ask: continue

            clip = clip_for(sym)
            if pos < LIMIT:
                result[sym].append(Order(sym, mm_bid, min(clip, LIMIT - pos)))
            if pos > -LIMIT:
                result[sym].append(Order(sym, mm_ask, -min(clip, LIMIT + pos)))

        return dict(result), 0, self._save(mem)
