import json
from collections import defaultdict
from typing import Dict, List

from datamodel import Order, TradingState

# heaven_we_comingv100.py — v5a + only the additions that survived backtest.
# Prior overlays (pair-convergence, shock-fade) were net-negative in the
# 2026-04-30 day 2/3/4 run, so excluded. Each kept change is justified by
# either a genuine code bug or 3/3-day empirical evidence.
#
# Changes vs ken/heaven_we_comingv5a.py:
#   1. _family() bug fix: split("_",1)[0] returns "SLEEP" / "OXYGEN" /
#      "GALAXY" / "UV" — wrong for SLEEP_POD, OXYGEN_SHAKE, GALAXY_SOUNDS,
#      UV_VISOR. Prefix-table lookup so spread caps actually apply.
#   2. SKIP_MM set:
#      - Tier C from docs (volatility.md, top_symbols csv): SNACKPACK,
#        GALAXY_SOUNDS non-LEADER, UV_VISOR_{RED,MAGENTA,YELLOW},
#        PEBBLES_XL.
#      - Empirical bleeders (3/3 days negative independent of overlays):
#        SLEEP_POD_LAMB_WOOL, PEBBLES_M, OXYGEN_SHAKE_MINT.
#   3. Leader-lag skew uses recent-window (20-tick) momentum × regression β
#      (clamped to ±2). More responsive than v5a's bh[-1]-bh[0]; magnitude
#      still bounded by LL_SKEW_CAP=3 so it cannot blow up.
# Untouched: LIMIT=10, MM_CLIP=4, INV_SKEW=0.30, FAMILY_SPREAD_CAPS values,
#   passive-MM quote shape, day-rollover reset, return tuple.

LIMIT = 10
MM_CLIP = 4
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

SKIP_MM = {
    # Tier C — no edge after cost (docs)
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
        return {"last_ts": -1, "bh_hist": [], "poly_hist": []}

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
        bh = mem["bh_hist"]
        poly = mem["poly_hist"]
        if len(bh) < LL_RECENT + 5 or len(poly) < LL_RECENT + 5:
            return 0.0
        mom = bh[-1] - bh[-LL_RECENT]
        n = min(len(bh), len(poly))
        bx = bh[-n:]
        px = poly[-n:]
        bm = sum(bx) / n
        pm = sum(px) / n
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

        bh_bid, bh_ask = self._bba(state, LEADER)
        poly_bid, poly_ask = self._bba(state, LAG)
        if bh_bid is not None and bh_ask is not None:
            mem["bh_hist"].append((bh_bid + bh_ask) / 2.0)
        if poly_bid is not None and poly_ask is not None:
            mem["poly_hist"].append((poly_bid + poly_ask) / 2.0)
        ll_skew = self._ll_skew(mem)

        for sym in state.order_depths.keys():
            if sym in SKIP_MM:
                continue
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None:
                continue
            spread = ask - bid
            if spread <= 0 or spread > self._spread_cap(sym):
                continue

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

            if mm_bid >= ask:
                mm_bid = ask - 1
            if mm_ask <= bid:
                mm_ask = bid + 1
            if mm_bid >= mm_ask:
                continue

            if pos < LIMIT:
                result[sym].append(Order(sym, mm_bid, min(MM_CLIP, LIMIT - pos)))
            if pos > -LIMIT:
                result[sym].append(Order(sym, mm_ask, -min(MM_CLIP, LIMIT + pos)))

        return dict(result), 0, self._save(mem)
