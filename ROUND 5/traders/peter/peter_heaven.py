import json
from collections import defaultdict
from typing import Dict, List

from datamodel import Order, TradingState

# peter_heaven.py — base = we_will_win.py (passive MM core from v5a +
# _family() bug fix + Tier-C/empirical skip + recent-mom×β LL skew).
#
# New alpha layer (charts_family_et evidence): family-residual fair adjustment.
# Every family panel shows e_t = (sym_mid - family_mid_mean) is stationary,
# zero-mean, oscillating ±3 z-score across day 2/3/4. The reversion is
# universal. Instead of taking on this signal (would cost spread on each
# entry), we BIAS the passive MM fair price toward where the residual should
# be — pulling quotes inward when sym is rich vs family, outward when cheap.
# Purely passive, no extra crossing cost.
#
# Concrete:
#   family_mid_mean[fam]  = average of mids of in-family symbols this tick
#   resid[sym]            = sym_mid - family_mid_mean[fam]
#   mu_resid[sym], var    = EWMA over ~200 ticks
#   pull[sym]             = -RESID_GAIN * (resid - mu_resid), clipped ±RESID_CAP
#   fair                  = mid - INV_SKEW*pos + pull
# Skipped: SKIP_MM symbols (don't pollute family mean either — drop from
# family_mid_mean since they'd skew it). Single-member "family" gets pull=0.
#
# Also kept: pair-convergence + shock-fade overlays remain OUT (both burned
# money in the 2026-04-30 backtest run).

LIMIT = 10
MM_CLIP = 4
INV_SKEW = 0.30
LEADER = "GALAXY_SOUNDS_BLACK_HOLES"
LAG = "SLEEP_POD_POLYESTER"
LL_LOOKBACK = 100
LL_RECENT = 20
LL_MULT = 0.10
LL_SKEW_CAP = 3.0

# Residual-fade fair adjustment
RESID_EWMA_MU = 0.02     # ~50-tick effective μ
RESID_EWMA_VAR = 0.01    # slower variance
RESID_GAIN = 0.30        # how much to pull fair toward expected residual
RESID_CAP = 3.0          # max absolute pull (price units) — bounded like LL

FAMILY_PREFIXES = [
    "GALAXY_SOUNDS", "SLEEP_POD", "OXYGEN_SHAKE", "UV_VISOR",
    "PEBBLES", "MICROCHIP", "TRANSLATOR", "PANEL", "ROBOT", "SNACKPACK",
]

FAMILY_SPREAD_CAPS = {
    "ROBOT": 8, "TRANSLATOR": 10, "PANEL": 10, "MICROCHIP": 10,
    "SLEEP_POD": 11, "OXYGEN_SHAKE": 12, "PEBBLES": 12, "UV_VISOR": 12,
    "GALAXY_SOUNDS": 12, "SNACKPACK": 12,
}
DEFAULT_SPREAD_CAP = 12

SKIP_MM = {
    # Tier C — no edge after cost
    "SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
    "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY",
    "GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_PLANETARY_RINGS",
    "GALAXY_SOUNDS_SOLAR_FLAMES", "GALAXY_SOUNDS_SOLAR_WINDS",
    "UV_VISOR_YELLOW", "UV_VISOR_RED", "UV_VISOR_MAGENTA",
    "PEBBLES_XL",
    # Empirical bleeders — 3/3 days negative
    "SLEEP_POD_LAMB_WOOL",
    "PEBBLES_M",
    "OXYGEN_SHAKE_MINT",
}


def family_of(sym: str) -> str:
    for p in FAMILY_PREFIXES:
        if sym.startswith(p): return p
    return sym


class Trader:
    def _empty(self) -> Dict:
        return {
            "last_ts": -1,
            "bh_hist": [], "poly_hist": [],
            "rmu": {},   # EWMA mean of residual per sym
            "rv": {},    # EWMA variance of residual per sym (kept for warmup gate)
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
            return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

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

        # --- Leader-Lag ---
        bh_bid, bh_ask = self._bba(state, LEADER)
        poly_bid, poly_ask = self._bba(state, LAG)
        if bh_bid is not None and bh_ask is not None:
            mem["bh_hist"].append((bh_bid + bh_ask) / 2.0)
        if poly_bid is not None and poly_ask is not None:
            mem["poly_hist"].append((poly_bid + poly_ask) / 2.0)
        ll_skew = self._ll_skew(mem)

        # --- Snapshot mids per symbol (and by family) ---
        # Exclude SKIP_MM symbols from family-mean (they may be structurally divergent
        # like PEBBLES_XL, SLEEP_POD_LAMB_WOOL — would bias the mean).
        mids: Dict[str, float] = {}
        for sym in state.order_depths.keys():
            bid, ask = self._bba(state, sym)
            if bid is None: continue
            mids[sym] = (bid + ask) / 2.0
        fam_mid_sum = defaultdict(float)
        fam_mid_cnt = defaultdict(int)
        for sym, mid in mids.items():
            if sym in SKIP_MM: continue
            fam = family_of(sym)
            fam_mid_sum[fam] += mid
            fam_mid_cnt[fam] += 1

        # --- Update residual EWMA per traded symbol ---
        resid_pull: Dict[str, float] = {}
        for sym, mid in mids.items():
            if sym in SKIP_MM: continue
            fam = family_of(sym)
            if fam_mid_cnt[fam] < 3:  # need enough peers for stable family mean
                continue
            fam_mean = fam_mid_sum[fam] / fam_mid_cnt[fam]
            resid = mid - fam_mean

            mu_prev = mem["rmu"].get(sym, resid)
            v_prev = mem["rv"].get(sym, 1.0)
            new_mu = (1 - RESID_EWMA_MU) * mu_prev + RESID_EWMA_MU * resid
            dev = resid - mu_prev
            new_v = (1 - RESID_EWMA_VAR) * v_prev + RESID_EWMA_VAR * (dev * dev)
            mem["rmu"][sym] = new_mu
            mem["rv"][sym] = new_v

            # Need warmup before using pull
            if v_prev < 1.0:
                continue
            pull = -RESID_GAIN * (resid - new_mu)
            if pull > RESID_CAP: pull = RESID_CAP
            elif pull < -RESID_CAP: pull = -RESID_CAP
            resid_pull[sym] = pull

        # --- Passive MM (v5a core, residual-pull added to fair) ---
        for sym in state.order_depths.keys():
            if sym in SKIP_MM: continue
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None: continue
            spread = ask - bid
            if spread <= 0 or spread > self._spread_cap(sym): continue

            mid = (bid + ask) / 2.0
            pos = state.position.get(sym, 0)
            fair = mid - (INV_SKEW * pos)
            if sym == LAG:
                fair += ll_skew
            fair += resid_pull.get(sym, 0.0)

            if spread >= 2:
                mm_bid = min(int(round(fair - 1)), ask - 1)
                mm_ask = max(int(round(fair + 1)), bid + 1)
            else:
                mm_bid = bid
                mm_ask = ask

            if mm_bid >= ask: mm_bid = ask - 1
            if mm_ask <= bid: mm_ask = bid + 1
            if mm_bid >= mm_ask: continue

            if pos < LIMIT:
                result[sym].append(Order(sym, mm_bid, min(MM_CLIP, LIMIT - pos)))
            if pos > -LIMIT:
                result[sym].append(Order(sym, mm_ask, -min(MM_CLIP, LIMIT + pos)))

        return dict(result), 0, self._save(mem)
