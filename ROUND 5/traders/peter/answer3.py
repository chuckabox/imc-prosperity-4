import json
import math
from collections import defaultdict
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

# ANSWER3.PY: Universal MM (from answer2) + dual-Z mean-reversion skew.
#
# Improvement over answer2:
#   - Replaces the static pair-alpha skew with a per-symbol mean-reversion
#     alpha derived from TWO z-scores:
#         z_fast over a short window (acute overshoot)
#         z_slow over a long window (structural overshoot)
#     The two Zs combine into a fair-value adjustment that pulls quotes
#     toward the mean when both agree on direction.
#   - Inventory skew kept but tuned per family.
#   - Wider quoting under high |z| (we don't want to lean into the spike;
#     wait for revert).

LIMIT = 10
MM_CLIP = 10
INV_SKEW_BASE = 0.20
MID_HISTORY = 200

WINDOW_FAST = 20
WINDOW_SLOW = 80

# How aggressively the dual-Z fair adjustment pulls quotes toward the mean.
# Tuned: too small loses to drift; too big crosses the book.
Z_ALPHA_FAST = 0.10
Z_ALPHA_SLOW = 0.0
# Skip Z-fade entirely when |z_slow| exceeds this — strong regime, not noise.
Z_SLOW_REGIME_CUTOFF = 2.0
# Only apply Z-fade when |z_fast| is in this band; outside the band it's
# either noise (too small to matter) or a regime we shouldn't fight.
Z_FAST_MIN = 0.8
Z_FAST_MAX = 2.5

# When |z_fast| crosses this, widen the offside quote (don't lean into the
# spike) and tighten the with-side (offer revert at a better price).
Z_WIDEN_THRESH = 1.6
Z_WIDEN_TICKS = 1


class Trader:
    def _empty(self) -> Dict:
        return {"last_ts": -1, "mids": {}}

    def _load(self, td: str) -> Dict:
        if not td:
            return self._empty()
        try:
            mem = json.loads(td)
            for k, v in self._empty().items():
                mem.setdefault(k, v)
            return mem
        except Exception:
            return self._empty()

    def _save(self, mem: Dict) -> str:
        for sym, hist in list(mem["mids"].items()):
            if len(hist) > MID_HISTORY:
                mem["mids"][sym] = hist[-MID_HISTORY:]
        return json.dumps(mem, separators=(",", ":"))

    @staticmethod
    def _bba(state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders:
            return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    @staticmethod
    def _mean_std(xs: List[float]) -> Tuple[float, float]:
        n = len(xs)
        if n < 2:
            return (xs[0] if xs else 0.0), 0.0
        m = sum(xs) / n
        var = sum((x - m) ** 2 for x in xs) / n
        return m, math.sqrt(var)

    def _dual_z(self, hist: List[float], mid: float) -> Tuple[float, float, float]:
        """Return (z_fast, z_slow, sigma_fast). 0 if not enough data."""
        if len(hist) < WINDOW_FAST:
            return 0.0, 0.0, 0.0
        m_f, s_f = self._mean_std(hist[-WINDOW_FAST:])
        if s_f < 0.5:
            z_f = 0.0
        else:
            z_f = (mid - m_f) / s_f

        if len(hist) < WINDOW_SLOW:
            return z_f, 0.0, s_f
        m_s, s_s = self._mean_std(hist[-WINDOW_SLOW:])
        if s_s < 0.5:
            z_s = 0.0
        else:
            z_s = (mid - m_s) / s_s
        return z_f, z_s, s_f

    @staticmethod
    def _family_skew(sym: str) -> float:
        if "PEBBLES" in sym:
            return 1.5
        if "MICROCHIP" in sym:
            return 1.2
        if "ROBOT" in sym:
            return 0.8
        return 1.0

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem = self._empty()
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        for sym in state.order_depths.keys():
            bid, ask = self._bba(state, sym)
            if bid is None:
                continue
            spread = ask - bid
            if spread < 1:
                continue

            mid = 0.5 * (bid + ask)
            hist = mem["mids"].setdefault(sym, [])
            hist.append(mid)
            if len(hist) > MID_HISTORY:
                del hist[: len(hist) - MID_HISTORY]

            pos = state.position.get(sym, 0)
            family = self._family_skew(sym)

            # Dual-Z mean-reversion fair adjustment.
            z_fast, z_slow, sigma_fast = self._dual_z(hist, mid)
            # Skip Z-fade when long-window deviation is regime-level — that's
            # a trend, not a mean-reversion opportunity.
            if abs(z_slow) > Z_SLOW_REGIME_CUTOFF or sigma_fast == 0:
                z_pull = 0.0
            elif z_fast * z_slow > 0:
                # Both agree on direction → fade.
                z_pull = -(Z_ALPHA_FAST * z_fast + Z_ALPHA_SLOW * z_slow) * sigma_fast
            else:
                # Diverge → fast only, weaker.
                z_pull = -(Z_ALPHA_FAST * 0.5 * z_fast) * sigma_fast

            inv_skew = -(INV_SKEW_BASE * family * pos)

            fair = mid + z_pull + inv_skew

            # Adaptive width: when |z_fast| is large, widen on the side facing
            # the move (don't get run over) and tighten on the revert side.
            extra_bid = 0
            extra_ask = 0
            if abs(z_fast) >= Z_WIDEN_THRESH:
                if z_fast > 0:
                    # price overshot up -> widen bid, tighten ask
                    extra_bid = Z_WIDEN_TICKS
                else:
                    # price undershot -> widen ask, tighten bid
                    extra_ask = Z_WIDEN_TICKS

            mm_bid = min(int(round(fair - 1 - extra_bid)), ask - 1)
            mm_ask = max(int(round(fair + 1 + extra_ask)), bid + 1)

            if mm_bid >= mm_ask:
                continue

            if pos < LIMIT:
                qty = min(MM_CLIP, LIMIT - pos)
                if qty > 0:
                    result[sym].append(Order(sym, mm_bid, qty))
            if pos > -LIMIT:
                qty = min(MM_CLIP, LIMIT + pos)
                if qty > 0:
                    result[sym].append(Order(sym, mm_ask, -qty))

        return dict(result), 0, self._save(mem)
