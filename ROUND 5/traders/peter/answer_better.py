import json
import math
from collections import defaultdict
from typing import Dict, List
from datamodel import Order, TradingState

# ANSWER_BETTER.PY — improvements over answer.py:
#   1. Per-family position limits (real caps 20-45, not flat 10).
#   2. Microprice fair anchor (book-imbalance aware).
#   3. EWMA-smoothed fair to dampen noise.
#   4. Volatility-aware inventory skew + quote width.
#   5. Aggressive taking when book crosses fair ± edge.
#   6. Family-level aggregate position cap (concentration risk).
#   7. Stronger LL signal: short-window momentum, magnitude-weighted corr.
#   8. Self-cross guard + spread-floor (skip queue-join when spread=1).
#   9. Clip auto-shrinks near limits, no overshoot.

DEFAULT_LIMIT = 20
FAMILY_LIMITS = {
    "PEBBLES": 45, "MICROCHIP": 40, "ROBOT": 35, "OXYGEN_SHAKE": 30,
    "PANEL": 30, "GALAXY_SOUNDS": 25, "TRANSLATOR": 25, "SLEEP_POD": 25,
    "UV_VISOR": 25, "SNACKPACK": 20,
}
FAMILY_PREFIXES = list(FAMILY_LIMITS.keys())

LEADER = "GALAXY_SOUNDS_BLACK_HOLES"
LAG = "SLEEP_POD_POLYESTER"
LL_LOOKBACK = 100
LL_RECENT = 20            # short window for momentum
LL_GAIN = 0.15            # scale of LL skew

EWMA_ALPHA = 0.30          # fair-mid smoothing
VOL_ALPHA = 0.10           # vol estimate smoothing
INV_SKEW_BASE = 0.25
TAKE_EDGE_MULT = 1.0       # take when book beyond fair by this * vol
MM_CLIP = 5
MAX_TAKE = 8


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
            "fair": {},     # sym -> ewma fair
            "vol": {},      # sym -> ewma abs(mid - last_mid)
            "last_mid": {},
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
        bb, ba = max(d.buy_orders.keys()), min(d.sell_orders.keys())
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
        # recent momentum on leader
        mom = bh[-1] - bh[-LL_RECENT]
        # magnitude-weighted corr over full window
        n = min(len(bh), len(poly))
        bx = bh[-n:]; px = poly[-n:]
        bm = sum(bx) / n; pm = sum(px) / n
        cov = sum((bx[i] - bm) * (px[i] - pm) for i in range(n))
        bvar = sum((bx[i] - bm) ** 2 for i in range(n)) or 1e-9
        beta = cov / bvar  # leader→lag regression slope
        # cap beta to sane band so a noisy fit doesn't blow up the skew
        beta = max(-2.0, min(2.0, beta))
        return mom * beta * LL_GAIN

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem = self._empty()
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        # Track LL history
        bb_l, ba_l, _ = self._bba(state, LEADER)
        bb_p, ba_p, _ = self._bba(state, LAG)
        if bb_l is not None: mem["bh_hist"].append((bb_l + ba_l) / 2.0)
        if bb_p is not None: mem["poly_hist"].append((bb_p + ba_p) / 2.0)
        ll_skew = self._ll_skew(mem)

        # Aggregate family positions for cap
        fam_pos = defaultdict(int)
        for s, p in state.position.items():
            fam_pos[family_of(s)] += abs(p)

        for sym, depth in state.order_depths.items():
            bb, ba, d = self._bba(state, sym)
            if bb is None: continue
            spread = ba - bb
            mid = (bb + ba) / 2.0
            mp = self._microprice(d, bb, ba)

            # Volatility EWMA on mid changes
            last_mid = mem["last_mid"].get(sym, mid)
            inst_vol = abs(mid - last_mid)
            vol = mem["vol"].get(sym, 1.0)
            vol = (1 - VOL_ALPHA) * vol + VOL_ALPHA * inst_vol
            mem["vol"][sym] = max(vol, 0.5)
            mem["last_mid"][sym] = mid

            # EWMA fair anchored on microprice
            fair_prev = mem["fair"].get(sym, mp)
            fair = (1 - EWMA_ALPHA) * fair_prev + EWMA_ALPHA * mp
            mem["fair"][sym] = fair

            # Volatility-aware inventory skew: high vol → flatten faster
            inv_skew = INV_SKEW_BASE * max(1.0, min(3.0, vol))
            pos = state.position.get(sym, 0)
            f = fair - inv_skew * pos
            if sym == LAG: f += ll_skew

            # Position room
            fam = family_of(sym)
            fam_lim = FAMILY_LIMITS.get(fam, DEFAULT_LIMIT)
            sym_lim = fam_lim  # use family limit as per-symbol cap too
            fam_room = max(0, fam_lim - fam_pos[fam])
            buy_room = min(sym_lim - pos, fam_room)
            sell_room = min(sym_lim + pos, fam_room)

            # ---- TAKE: cross stale orders beyond fair ± edge ----
            take_edge = TAKE_EDGE_MULT * mem["vol"][sym]
            # someone bidding above fair → sell into them
            if bb > f + take_edge and sell_room > 0:
                qty = min(MAX_TAKE, sell_room, abs(d.buy_orders.get(bb, 0)))
                if qty > 0:
                    result[sym].append(Order(sym, bb, -qty))
                    sell_room -= qty
                    fam_pos[fam] += qty
            # someone offering below fair → buy from them
            if ba < f - take_edge and buy_room > 0:
                qty = min(MAX_TAKE, buy_room, abs(d.sell_orders.get(ba, 0)))
                if qty > 0:
                    result[sym].append(Order(sym, ba, qty))
                    buy_room -= qty
                    fam_pos[fam] += qty

            # ---- MAKE: passive quotes ----
            # Skip queue-joining when spread=1 (no edge, only adverse-fill risk)
            if spread < 2:
                continue

            mm_bid = int(math.floor(f))
            mm_ask = mm_bid + 1
            if math.ceil(f) > mm_bid: mm_ask = int(math.ceil(f))
            # ensure inside-spread (1 tick inside touch)
            mm_bid = min(mm_bid, ba - 1)
            mm_ask = max(mm_ask, bb + 1)
            # self-cross guard
            if mm_bid >= mm_ask:
                mm_bid = mm_ask - 1

            clip = MM_CLIP
            if buy_room > 0:
                result[sym].append(Order(sym, mm_bid, min(clip, buy_room)))
            if sell_room > 0:
                result[sym].append(Order(sym, mm_ask, -min(clip, sell_room)))

        return dict(result), 0, self._save(mem)
