import json
from collections import defaultdict
from typing import Dict, List

from datamodel import Order, TradingState

# v5b: v5a + stricter position-limit-aware quoting.
# Keeps hard per-product cap at 10 and avoids two-sided quoting near limits.
LIMIT = 10
BASE_MM_CLIP = 4
INV_SKEW = 0.30
LEADER = "GALAXY_SOUNDS_BLACK_HOLES"
LAG = "SLEEP_POD_POLYESTER"
LL_LOOKBACK = 100
LL_MULT = 0.10
LL_SKEW_CAP = 3.0

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
NEAR_LIMIT = 8


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

    def _get_corr_sign(self, x: List[float], y: List[float]) -> float:
        if len(x) < 50 or len(y) < 50:
            return 1.0
        n = min(len(x), len(y))
        xm = sum(x[-n:]) / n
        ym = sum(y[-n:]) / n
        cov = sum((x[-i] - xm) * (y[-i] - ym) for i in range(1, n + 1))
        return 1.0 if cov >= 0 else -1.0

    def _family(self, sym: str) -> str:
        return sym.split("_", 1)[0]

    def _spread_cap(self, sym: str) -> int:
        return FAMILY_SPREAD_CAPS.get(self._family(sym), DEFAULT_SPREAD_CAP)

    def _clip_for_spread(self, spread: int, cap: int) -> int:
        if spread >= cap:
            return 2
        if spread == cap - 1:
            return 3
        return BASE_MM_CLIP

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

        ll_skew = 0.0
        if len(mem["bh_hist"]) >= LL_LOOKBACK:
            move = mem["bh_hist"][-1] - mem["bh_hist"][0]
            sign = self._get_corr_sign(mem["bh_hist"], mem["poly_hist"])
            ll_skew = move * sign * LL_MULT
            if ll_skew > LL_SKEW_CAP:
                ll_skew = LL_SKEW_CAP
            elif ll_skew < -LL_SKEW_CAP:
                ll_skew = -LL_SKEW_CAP

        for sym in state.order_depths.keys():
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None:
                continue
            spread = ask - bid
            cap = self._spread_cap(sym)
            if spread <= 0 or spread > cap:
                continue

            pos = state.position.get(sym, 0)
            buy_cap = max(0, LIMIT - pos)
            sell_cap = max(0, LIMIT + pos)
            if buy_cap == 0 and sell_cap == 0:
                continue

            mid = (bid + ask) / 2.0
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

            clip = self._clip_for_spread(spread, cap)

            # One-sided risk reduction near position limits.
            if pos >= NEAR_LIMIT:
                buy_qty = 0
                sell_qty = min(clip, sell_cap)
            elif pos <= -NEAR_LIMIT:
                buy_qty = min(clip, buy_cap)
                sell_qty = 0
            else:
                buy_qty = min(clip, buy_cap)
                sell_qty = min(clip, sell_cap)

            if buy_qty > 0:
                result[sym].append(Order(sym, mm_bid, buy_qty))
            if sell_qty > 0:
                result[sym].append(Order(sym, mm_ask, -sell_qty))

        return dict(result), 0, self._save(mem)
