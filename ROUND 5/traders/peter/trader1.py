"""peter/trader1.py

Round 5 strategy stacking three alphas derived from the dashboards in
`ROUND 5/docs/pair_dashboards` and `ROUND 5/docs/item_over_time`:

  Alpha 1 - tight-spread pair convergence on a 19-pair whitelist
  Alpha 2 - per-symbol residual reversion on an 18-symbol whitelist
  Alpha 3 - ITM-leg sizing: when a family signal triggers, also express via
            the high-notional variant of that family

Full reasoning lives in `ROUND 5/traders/peter/analyse/round5_alphas.md`.
"""

import json
import math
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


PAIR_WHITELIST: List[Tuple[str, str, float]] = [
    ("TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_GRAPHITE_MIST", 12970.0),
    ("MICROCHIP_OVAL", "MICROCHIP_SQUARE", 9018.5),
    ("SLEEP_POD_NYLON", "SLEEP_POD_POLYESTER", 7436.0),
    ("MICROCHIP_CIRCLE", "MICROCHIP_OVAL", 7360.7),
    ("ROBOT_DISHES", "ROBOT_VACUUMING", 7303.3),
    ("TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST", 7161.2),
    ("ROBOT_LAUNDRY", "ROBOT_VACUUMING", 6672.2),
    ("TRANSLATOR_GRAPHITE_MIST", "TRANSLATOR_VOID_BLUE", 5500.5),
    ("ROBOT_LAUNDRY", "ROBOT_MOPPING", 5311.7),
    ("MICROCHIP_CIRCLE", "MICROCHIP_RECTANGLE", 5087.0),
    ("PANEL_2X2", "PANEL_2X4", 4443.1),
    ("MICROCHIP_RECTANGLE", "MICROCHIP_SQUARE", 4236.7),
    ("OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_EVENING_BREATH", 4199.4),
    ("TRANSLATOR_GRAPHITE_MIST", "TRANSLATOR_SPACE_GRAY", 3737.2),
    ("MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE", 3300.6),
    ("TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_VOID_BLUE", 3267.1),
    ("PANEL_1X2", "PANEL_2X4", 3205.8),
    ("SLEEP_POD_NYLON", "SLEEP_POD_SUEDE", 2251.6),
    ("MICROCHIP_CIRCLE", "MICROCHIP_TRIANGLE", 1663.2),
]

SINGLE_WHITELIST: Dict[str, float] = {
    "ROBOT_DISHES": 0.254,
    "ROBOT_IRONING": 0.213,
    "ROBOT_VACUUMING": 0.173,
    "MICROCHIP_OVAL": 0.165,
    "MICROCHIP_RECTANGLE": 0.162,
    "ROBOT_LAUNDRY": 0.159,
    "ROBOT_MOPPING": 0.156,
    "MICROCHIP_CIRCLE": 0.152,
    "TRANSLATOR_ASTRO_BLACK": 0.151,
    "PANEL_1X4": 0.148,
    "MICROCHIP_TRIANGLE": 0.142,
    "PEBBLES_XS": 0.140,
    "PANEL_2X2": 0.135,
    "TRANSLATOR_ECLIPSE_CHARCOAL": 0.135,
    "TRANSLATOR_GRAPHITE_MIST": 0.134,
    "PANEL_4X4": 0.132,
    "TRANSLATOR_SPACE_GRAY": 0.132,
    "SLEEP_POD_NYLON": 0.131,
}

# Alpha 3: family signal-leg -> high-notional expression-leg.
EXPRESSION_LEG: Dict[str, str] = {
    "PEBBLES": "PEBBLES_XL",
    "MICROCHIP": "MICROCHIP_SQUARE",
    "TRANSLATOR": "TRANSLATOR_VOID_BLUE",
    "SLEEP_POD": "SLEEP_POD_POLYESTER",
    "PANEL": "PANEL_2X4",
    "OXYGEN_SHAKE": "OXYGEN_SHAKE_EVENING_BREATH",
}

FAMILY_PREFIXES = [
    "PEBBLES", "SNACKPACK", "UV_VISOR", "GALAXY_SOUNDS", "MICROCHIP",
    "TRANSLATOR", "SLEEP_POD", "OXYGEN_SHAKE", "PANEL", "ROBOT",
]

FAMILY_LIMITS = {
    "PEBBLES": 45, "MICROCHIP": 40, "ROBOT": 35, "OXYGEN_SHAKE": 30,
    "PANEL": 30, "GALAXY_SOUNDS": 25, "TRANSLATOR": 25, "SLEEP_POD": 25,
    "UV_VISOR": 25, "SNACKPACK": 20,
}

DEFAULT_LIMIT = 20

# Pair-trade knobs
TIGHT_SPREAD_MAX = 12
PAIR_EWMA_ALPHA = 0.02     # ~50-tick effective window for mu
PAIR_VAR_ALPHA = 0.01      # slower variance estimate
Z_ENTER = 1.5
Z_EXIT = 0.3
PAIR_MAX_HOLD = 25
PAIR_BASE_CLIP = 5
PAIR_TOP_CLIP = 10         # for top-5 quality pairs
PAIR_TOP_RANK = 5

# Single-leg shock-fade knobs
SHOCK_BASE = 8.0
SHOCK_SPREAD_MULT = 1.2
SINGLE_BASE_CLIP = 5
SINGLE_HOLD_DEFAULT = 1

# Alpha 3 scaling
EXPRESSION_LEG_FRAC = 0.6  # of the cheap-leg clip, also pushed onto the expression leg

# Per-family simultaneous-pair cap
MAX_PAIRS_PER_FAMILY = 2


def _family(symbol: str) -> str:
    for prefix in FAMILY_PREFIXES:
        if symbol.startswith(prefix + "_"):
            return prefix
    return symbol.split("_", 1)[0]


def _pair_key(a: str, b: str) -> str:
    return f"{a}|{b}"


class Trader:
    def _load(self, td: str) -> Dict:
        if not td:
            return self._empty_state()
        try:
            mem = json.loads(td)
        except Exception:
            return self._empty_state()
        for k, v in self._empty_state().items():
            mem.setdefault(k, v)
        return mem

    def _empty_state(self) -> Dict:
        return {
            "last_ts": -1,
            "day_idx": 0,
            "last_mid": {},          # symbol -> mid (for shock detection)
            "pair_mu": {},           # pair_key -> EWMA mean of s = mid_a - mid_b
            "pair_var": {},          # pair_key -> EWMA variance
            "pair_seen": {},         # pair_key -> int sample count
            "pair_pos_dir": {},      # pair_key -> +1 (long A, short B), -1, or 0
            "pair_entry_ts": {},     # pair_key -> entry timestamp
            "single_entry_ts": {},   # symbol -> entry timestamp (Alpha 2 hold)
        }

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _best_bid_ask(self, state: TradingState, symbol: str):
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def _mid_and_spread(self, state: TradingState, symbol: str):
        bid, ask = self._best_bid_ask(state, symbol)
        if bid is None or ask is None:
            return None, None, None, None
        return 0.5 * (bid + ask), max(1, ask - bid), bid, ask

    def _caps(self, symbol: str, position: Dict[str, int]):
        fam = _family(symbol)
        lim = FAMILY_LIMITS.get(fam, DEFAULT_LIMIT)
        pos = position.get(symbol, 0)
        return lim, max(0, lim - pos), max(0, lim + pos)

    # ---------- Alpha 1: pair convergence ----------
    def _update_pair_stats(self, mem: Dict, key: str, s: float):
        mu = mem["pair_mu"].get(key)
        var = mem["pair_var"].get(key, 0.0)
        seen = mem["pair_seen"].get(key, 0) + 1
        if mu is None:
            mu_new = s
            var_new = 0.0
        else:
            mu_new = (1 - PAIR_EWMA_ALPHA) * mu + PAIR_EWMA_ALPHA * s
            diff = s - mu_new
            var_new = (1 - PAIR_VAR_ALPHA) * var + PAIR_VAR_ALPHA * diff * diff
        mem["pair_mu"][key] = mu_new
        mem["pair_var"][key] = var_new
        mem["pair_seen"][key] = seen
        return mu_new, var_new, seen

    def _run_pairs(self, state: TradingState, mem: Dict, mids, spreads, result):
        family_pair_count: Dict[str, int] = defaultdict(int)
        # Sort whitelist so highest-quality pairs get capacity first.
        ranked = list(enumerate(PAIR_WHITELIST))
        for rank, (a, b, score) in ranked:
            if a not in mids or b not in mids:
                continue
            spr_a = spreads[a]
            spr_b = spreads[b]
            mid_a = mids[a]
            mid_b = mids[b]
            s = mid_a - mid_b
            key = _pair_key(a, b)
            mu, var, seen = self._update_pair_stats(mem, key, s)
            sigma = math.sqrt(max(var, 1e-9))

            fam = _family(a)
            cur_dir = mem["pair_pos_dir"].get(key, 0)
            entry_ts = mem["pair_entry_ts"].get(key, -1)

            # Need enough samples before trusting the z-score.
            if seen < 30:
                continue

            both_tight = spr_a <= TIGHT_SPREAD_MAX and spr_b <= TIGHT_SPREAD_MAX
            z = (s - mu) / sigma if sigma > 0 else 0.0

            # Exit conditions first.
            if cur_dir != 0:
                age = state.timestamp - entry_ts
                if abs(z) <= Z_EXIT or age >= PAIR_MAX_HOLD * 100 or not both_tight:
                    self._unwind_pair(state, result, a, b, cur_dir)
                    mem["pair_pos_dir"][key] = 0
                    mem["pair_entry_ts"][key] = -1
                continue

            if not both_tight:
                continue
            if family_pair_count[fam] >= MAX_PAIRS_PER_FAMILY:
                continue
            if abs(z) < Z_ENTER:
                continue

            clip = PAIR_TOP_CLIP if rank < PAIR_TOP_RANK else PAIR_BASE_CLIP
            direction = -1 if z > 0 else 1   # mean revert: short A / long B if z>0

            placed = self._open_pair(state, result, a, b, direction, clip)
            if placed:
                mem["pair_pos_dir"][key] = direction
                mem["pair_entry_ts"][key] = state.timestamp
                family_pair_count[fam] += 1
                # Alpha 3: amplify via expression leg of the family.
                self._apply_expression_leg(state, result, fam, direction, clip)

    def _open_pair(self, state: TradingState, result, a: str, b: str, direction: int, clip: int) -> bool:
        bid_a, ask_a = self._best_bid_ask(state, a)
        bid_b, ask_b = self._best_bid_ask(state, b)
        if bid_a is None or bid_b is None:
            return False
        _, buy_a, sell_a = self._caps(a, state.position)
        _, buy_b, sell_b = self._caps(b, state.position)
        if direction == 1:    # long A, short B
            qa = min(clip, buy_a)
            qb = min(clip, sell_b)
            q = min(qa, qb)
            if q <= 0:
                return False
            result[a].append(Order(a, ask_a, q))
            result[b].append(Order(b, bid_b, -q))
            return True
        if direction == -1:   # short A, long B
            qa = min(clip, sell_a)
            qb = min(clip, buy_b)
            q = min(qa, qb)
            if q <= 0:
                return False
            result[a].append(Order(a, bid_a, -q))
            result[b].append(Order(b, ask_b, q))
            return True
        return False

    def _unwind_pair(self, state: TradingState, result, a: str, b: str, direction: int):
        for sym in (a, b):
            pos = state.position.get(sym, 0)
            if pos == 0:
                continue
            bid, ask = self._best_bid_ask(state, sym)
            if bid is None or ask is None:
                continue
            _, buy_cap, sell_cap = self._caps(sym, state.position)
            if pos > 0 and sell_cap > 0:
                result[sym].append(Order(sym, bid, -min(pos, sell_cap)))
            elif pos < 0 and buy_cap > 0:
                result[sym].append(Order(sym, ask, min(-pos, buy_cap)))

    def _apply_expression_leg(self, state: TradingState, result, family: str, direction: int, clip: int):
        leg = EXPRESSION_LEG.get(family)
        if not leg:
            return
        bid, ask = self._best_bid_ask(state, leg)
        if bid is None or ask is None:
            return
        _, buy_cap, sell_cap = self._caps(leg, state.position)
        q = max(1, int(clip * EXPRESSION_LEG_FRAC))
        # direction == +1 means long the cheap leg / short the rich leg in family;
        # the expression leg behaves like the cheap leg + leverage.
        if direction == 1 and buy_cap > 0:
            result[leg].append(Order(leg, ask, min(q, buy_cap)))
        elif direction == -1 and sell_cap > 0:
            result[leg].append(Order(leg, bid, -min(q, sell_cap)))

    # ---------- Alpha 2: single-leg shock fade ----------
    def _run_singles(self, state: TradingState, mem: Dict, mids, spreads, result):
        for symbol in SINGLE_WHITELIST:
            if symbol not in mids:
                continue
            mid = mids[symbol]
            spread = spreads[symbol]
            bid, ask = self._best_bid_ask(state, symbol)
            if bid is None or ask is None:
                continue
            last = mem["last_mid"].get(symbol, mid)
            d_mid = mid - last

            pos = state.position.get(symbol, 0)
            entry_ts = mem["single_entry_ts"].get(symbol, -1)
            _, buy_cap, sell_cap = self._caps(symbol, state.position)

            # Exit one-tick shock-fade.
            if pos != 0 and entry_ts >= 0 and state.timestamp > entry_ts:
                if pos > 0 and sell_cap > 0:
                    result[symbol].append(Order(symbol, bid, -min(pos, sell_cap)))
                elif pos < 0 and buy_cap > 0:
                    result[symbol].append(Order(symbol, ask, min(-pos, buy_cap)))
                mem["single_entry_ts"][symbol] = -1
                continue

            # Entry only when flat (do not stack with pair leg).
            if pos != 0:
                continue
            trigger = max(SHOCK_BASE, SHOCK_SPREAD_MULT * spread)
            if abs(d_mid) < trigger:
                continue
            scale = min(2.0, abs(d_mid) / max(trigger, 1.0))
            qty = max(1, int(SINGLE_BASE_CLIP * scale))
            if d_mid <= -trigger and buy_cap > 0:
                result[symbol].append(Order(symbol, ask, min(qty, buy_cap)))
                mem["single_entry_ts"][symbol] = state.timestamp
            elif d_mid >= trigger and sell_cap > 0:
                result[symbol].append(Order(symbol, bid, -min(qty, sell_cap)))
                mem["single_entry_ts"][symbol] = state.timestamp

    # ---------- entry point ----------
    def run(self, state: TradingState):
        mem = self._load(state.traderData)

        # Day-rollover reset (timestamps wrap to 0 at the start of each new day).
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["day_idx"] += 1
            mem["last_mid"] = {}
            mem["pair_mu"] = {}
            mem["pair_var"] = {}
            mem["pair_seen"] = {}
            mem["pair_pos_dir"] = {}
            mem["pair_entry_ts"] = {}
            mem["single_entry_ts"] = {}
        mem["last_ts"] = state.timestamp

        mids: Dict[str, float] = {}
        spreads: Dict[str, int] = {}
        for symbol in state.order_depths.keys():
            mid, spread, _, _ = self._mid_and_spread(state, symbol)
            if mid is None:
                continue
            mids[symbol] = mid
            spreads[symbol] = spread

        result: Dict[str, List[Order]] = defaultdict(list)

        # Alpha 1 (pair convergence) + Alpha 3 (expression leg) first - they
        # take precedence and lock up family capacity.
        self._run_pairs(state, mem, mids, spreads, result)

        # Alpha 2 (single-leg shock fade) opportunistically uses what is left.
        self._run_singles(state, mem, mids, spreads, result)

        # Update last_mid memory after both alphas have read it.
        for sym, mid in mids.items():
            mem["last_mid"][sym] = mid

        return dict(result), 0, self._save(mem)
