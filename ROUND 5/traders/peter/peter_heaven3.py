import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState

# peter_heaven3.py — full doc-alpha audit applied. All passive (no taker
# overlays — both pair-taker and shock-fade bled prior backtests).
#
# ALPHA INVENTORY (each marked with source doc and how applied):
#   A. Inventory skew                           v5a baseline
#   B. Leader-Lag skew (GALAXY→POLYESTER)       v5a, recent-mom × β
#   C. Family-residual pull                     charts_family_et (universal)
#   D. Microprice anchor                        book imbalance
#   E. Self mean-revert pull                    charts_per_item
#   F. Pair-convergence fair pull (NEW)         analyse/Alpha-1, top_pairs csv
#   G. ITM-leverage amplification (NEW)         analyse/Alpha-3, discord clue
#   H. Anti-pair exclusion (NEW)                analyse/anti-pair list
#   I. Volatility-weighted clip (NEW)           ken_findings #2
#   J. Tier-aware clip & spread caps            volatility.md / round5_alpha_selection
#   K. Family spread gates                      round5_execution_playbook
#   L. Day rollover state reset                 backtest_consistency_contract
#   M. Bleeder mini-clip                        empirical 3/3-day data
#
# Algo.md respected: per-symbol |pos|≤10 hard. All 50 products quote.

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
MICRO_BLEND = 0.40

# Self mean-revert
SELF_EWMA = 0.02
SELF_GAIN = 0.20
SELF_CAP = 2.0

# Pair convergence pull (passive)
PAIR_EWMA_MU = 0.02
PAIR_EWMA_VAR = 0.01
PAIR_GAIN = 0.20
PAIR_CAP = 2.5

# ITM-leverage amplification (cheap leg → expression leg)
ITM_GAIN = 0.50          # fraction of cheap-leg residual pull copied
ITM_CAP = 2.5

# Volatility-weighted clip — scales with |signal| relative to spread
VOL_CLIP_LOW = 0.5       # min multiplier when signal weak
VOL_CLIP_HIGH = 1.5      # max multiplier when signal strong

FAMILY_PREFIXES = [
    "GALAXY_SOUNDS", "SLEEP_POD", "OXYGEN_SHAKE", "UV_VISOR",
    "PEBBLES", "MICROCHIP", "TRANSLATOR", "PANEL", "ROBOT", "SNACKPACK",
]

FAMILY_SPREAD_CAPS = {
    "ROBOT": 9, "TRANSLATOR": 11, "PANEL": 11, "MICROCHIP": 12,
    "SLEEP_POD": 12, "OXYGEN_SHAKE": 14, "PEBBLES": 14,
    "UV_VISOR": 16, "GALAXY_SOUNDS": 16, "SNACKPACK": 20,
}
DEFAULT_SPREAD_CAP = 14

# Top-quality whitelist pairs (analyse/round5_alphas.md, score >= 3000, tight_rate=1.0)
PAIRS: List[Tuple[str, str]] = [
    ("TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_GRAPHITE_MIST"),
    ("MICROCHIP_CIRCLE",       "MICROCHIP_OVAL"),
    ("ROBOT_DISHES",           "ROBOT_VACUUMING"),
    ("TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST"),
    ("ROBOT_LAUNDRY",          "ROBOT_VACUUMING"),
    ("TRANSLATOR_GRAPHITE_MIST", "TRANSLATOR_VOID_BLUE"),
    ("ROBOT_LAUNDRY",          "ROBOT_MOPPING"),
    ("MICROCHIP_CIRCLE",       "MICROCHIP_RECTANGLE"),
    ("PANEL_2X2",              "PANEL_2X4"),
    ("TRANSLATOR_GRAPHITE_MIST", "TRANSLATOR_SPACE_GRAY"),
    ("MICROCHIP_RECTANGLE",    "MICROCHIP_TRIANGLE"),
    ("TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_VOID_BLUE"),
    ("SLEEP_POD_NYLON",        "SLEEP_POD_POLYESTER"),
]

# ITM expression mapping: cheap signal-leg(s) -> high-notional expression leg
ITM_EXPRESS: Dict[str, str] = {
    "PEBBLES_XS": "PEBBLES_XL",
    "PEBBLES_S":  "PEBBLES_XL",
    "MICROCHIP_OVAL":      "MICROCHIP_SQUARE",
    "MICROCHIP_CIRCLE":    "MICROCHIP_SQUARE",
    "MICROCHIP_RECTANGLE": "MICROCHIP_SQUARE",
    "TRANSLATOR_ASTRO_BLACK":   "TRANSLATOR_VOID_BLUE",
    "TRANSLATOR_GRAPHITE_MIST": "TRANSLATOR_VOID_BLUE",
    "SLEEP_POD_NYLON":  "SLEEP_POD_POLYESTER",
    "PANEL_2X2":        "PANEL_2X4",
    "OXYGEN_SHAKE_CHOCOLATE": "OXYGEN_SHAKE_EVENING_BREATH",
}

# Anti-pairs: same-family but structurally divergent (don't apply pair pull,
# don't include in family mean — they pollute the residual).
ANTIPAIR_EXCLUDE_FROM_FAMMEAN = {
    "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_COTTON",   # drift apart from NYLON
    "PANEL_1X4",                                  # structural diverger
    "PEBBLES_XL",                                 # ITM, drifts from cheap legs
}

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
BLEEDERS = {"SLEEP_POD_LAMB_WOOL", "PEBBLES_M", "OXYGEN_SHAKE_MINT"}

CLIP_TIER_A = 5
CLIP_TIER_B = 4
CLIP_TIER_C = 2
CLIP_BLEEDER = 1


def family_of(sym: str) -> str:
    for p in FAMILY_PREFIXES:
        if sym.startswith(p): return p
    return sym


def base_clip(sym: str) -> int:
    if sym in BLEEDERS: return CLIP_BLEEDER
    if sym in TIER_A: return CLIP_TIER_A
    if sym in TIER_B: return CLIP_TIER_B
    return CLIP_TIER_C


class Trader:
    def _empty(self) -> Dict:
        return {
            "last_ts": -1,
            "bh_hist": [], "poly_hist": [],
            "rmu": {}, "rv": {},      # family-residual EWMA
            "smu": {}, "sv": {},      # self-mid EWMA
            "pmu": {}, "pv": {},      # pair-spread EWMA per pair_key
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

        # --- Snapshot mids and depths ---
        mids: Dict[str, float] = {}
        depths: Dict[str, Tuple[int, int, object]] = {}
        for sym in state.order_depths.keys():
            bb, ba, d = self._bba(state, sym)
            if bb is None: continue
            mids[sym] = (bb + ba) / 2.0
            depths[sym] = (bb, ba, d)

        # --- Family means (excluding bleeders + structural divergers) ---
        fam_sum = defaultdict(float); fam_cnt = defaultdict(int)
        for sym, mid in mids.items():
            if sym in BLEEDERS or sym in ANTIPAIR_EXCLUDE_FROM_FAMMEAN: continue
            fam = family_of(sym)
            fam_sum[fam] += mid
            fam_cnt[fam] += 1

        # --- Per-symbol pulls ---
        resid_pull: Dict[str, float] = defaultdict(float)
        self_pull: Dict[str, float] = defaultdict(float)
        signal_strength: Dict[str, float] = defaultdict(float)  # for clip scaling

        for sym, mid in mids.items():
            # C. Family-residual pull
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
                    resid_pull[sym] += pull
                    signal_strength[sym] += abs(pull)

            # E. Self mean-revert
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
                self_pull[sym] += spull
                signal_strength[sym] += abs(spull)

        # --- F. Pair-convergence fair pull (passive) ---
        for sym_a, sym_b in PAIRS:
            if sym_a not in mids or sym_b not in mids: continue
            s = mids[sym_a] - mids[sym_b]
            pk = f"{sym_a}|{sym_b}"
            mu_prev = mem["pmu"].get(pk, s)
            v_prev = mem["pv"].get(pk, 1.0)
            new_mu = (1 - PAIR_EWMA_MU) * mu_prev + PAIR_EWMA_MU * s
            dev = s - mu_prev
            new_v = (1 - PAIR_EWMA_VAR) * v_prev + PAIR_EWMA_VAR * (dev * dev)
            mem["pmu"][pk] = new_mu
            mem["pv"][pk] = new_v
            if v_prev < 1.0: continue
            # Pull each leg toward convergence: if A is rich, pull A down, B up
            d_to_mean = s - new_mu
            sigma = max(0.5, new_v ** 0.5)
            z = d_to_mean / sigma
            pull_a = -PAIR_GAIN * d_to_mean * 0.5
            pull_b = +PAIR_GAIN * d_to_mean * 0.5
            if pull_a > PAIR_CAP: pull_a = PAIR_CAP
            elif pull_a < -PAIR_CAP: pull_a = -PAIR_CAP
            if pull_b > PAIR_CAP: pull_b = PAIR_CAP
            elif pull_b < -PAIR_CAP: pull_b = -PAIR_CAP
            resid_pull[sym_a] += pull_a
            resid_pull[sym_b] += pull_b
            signal_strength[sym_a] += abs(pull_a)
            signal_strength[sym_b] += abs(pull_b)

        # --- G. ITM leverage: amplify expression leg by cheap-leg residual signal ---
        itm_pull: Dict[str, float] = defaultdict(float)
        for cheap_leg, expr_leg in ITM_EXPRESS.items():
            if expr_leg not in mids: continue
            cheap_pull = resid_pull.get(cheap_leg, 0.0)
            if abs(cheap_pull) < 0.5: continue   # noise floor
            amp = ITM_GAIN * cheap_pull
            if amp > ITM_CAP: amp = ITM_CAP
            elif amp < -ITM_CAP: amp = -ITM_CAP
            itm_pull[expr_leg] += amp

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

            # Compose fair from layered alphas
            base = (1 - MICRO_BLEND) * mid + MICRO_BLEND * mp
            fair = base - (INV_SKEW * pos)
            if sym == LAG: fair += ll_skew
            fair += resid_pull.get(sym, 0.0)
            fair += self_pull.get(sym, 0.0)
            fair += itm_pull.get(sym, 0.0)

            if spread >= 2:
                mm_bid = min(int(round(fair - 1)), ask - 1)
                mm_ask = max(int(round(fair + 1)), bid + 1)
            else:
                mm_bid = bid
                mm_ask = ask

            if mm_bid >= ask: mm_bid = ask - 1
            if mm_ask <= bid: mm_ask = bid + 1
            if mm_bid >= mm_ask: continue

            # I. Volatility-weighted clip — scale by signal strength
            bc = base_clip(sym)
            sig = signal_strength.get(sym, 0.0)
            mult = VOL_CLIP_LOW + (VOL_CLIP_HIGH - VOL_CLIP_LOW) * min(1.0, sig / 3.0)
            clip = max(1, int(round(bc * mult)))

            if pos < LIMIT:
                result[sym].append(Order(sym, mm_bid, min(clip, LIMIT - pos)))
            if pos > -LIMIT:
                result[sym].append(Order(sym, mm_ask, -min(clip, LIMIT + pos)))

        return dict(result), 0, self._save(mem)
