"""peter/trader2.py

Round 5 strategy v2. Trader1 lost ~73k by stacking pair-convergence and an
"expression leg" amplifier on top of the shock-fade primitive: each pair-leg
trade crossed two spreads to capture ~0.5-2 ticks of pair mean drift, and the
expression leg added an unhedged directional bet that paid spread again.

Per ken_round5_alpha_sweep.md the only robust all-days-positive alpha is
`reversal threshold=8 hold=1..3` (single-symbol one-tick shock fade). Per
ken_round5_execution_sweep.md that primitive needs to be **stacked** with a
product whitelist + spread cap + sizing filter to clear spread costs.

trader2 keeps only the validated primitive and stacks those filters on top:
  - Whitelist of high signal-quality symbols (top of
    docs/item_over_time/summary/top_symbols_by_signal_quality.csv)
    plus PEBBLES_XL and MICROCHIP_SQUARE (highest realised vol per ken's
    findings, big absolute reversion even though spread is wide).
  - Per-symbol shock trigger = max(SHOCK_BASE, k * spread) with k tuned by
    signal quality (better signal -> trigger closer to spread).
  - Spread cap: never enter when spread > MAX_ENTRY_SPREAD.
  - Hold = 1 tick (the only knob in the robust-winners table that was
    positive on all 3 days).
  - Per-family hard caps + per-symbol clip scaled by shock magnitude AND by
    the published signal_quality_score (best names get larger clips).
"""

import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


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

# (symbol -> (signal_quality, max_entry_spread))
# Quality is from docs/item_over_time/summary/top_symbols_by_signal_quality.csv.
# max_entry_spread is set just above the symbol's median spread in that table:
# we only enter when current spread already sits at or below the median, which
# is the regime the published quality score was measured in.
WHITELIST: Dict[str, Tuple[float, int]] = {
    # Top quality names - cheap spreads, strong reversion.
    "ROBOT_DISHES":               (0.254, 7),
    "ROBOT_IRONING":              (0.213, 6),
    "ROBOT_VACUUMING":            (0.173, 7),
    "MICROCHIP_OVAL":             (0.165, 8),
    "MICROCHIP_RECTANGLE":        (0.162, 8),
    "ROBOT_LAUNDRY":              (0.159, 7),
    "ROBOT_MOPPING":              (0.156, 8),
    "MICROCHIP_CIRCLE":           (0.152, 8),
    "TRANSLATOR_ASTRO_BLACK":     (0.151, 8),
    "PANEL_1X4":                  (0.148, 8),
    "MICROCHIP_TRIANGLE":         (0.142, 9),
    "PEBBLES_XS":                 (0.140, 9),
    "PANEL_2X2":                  (0.135, 9),
    "TRANSLATOR_ECLIPSE_CHARCOAL":(0.135, 9),
    "TRANSLATOR_GRAPHITE_MIST":   (0.134, 9),
    "PANEL_4X4":                  (0.132, 9),
    "TRANSLATOR_SPACE_GRAY":      (0.132, 9),
    "SLEEP_POD_NYLON":            (0.131, 9),
    # High realised vol - lower per-tick edge on the dashboard but ken's manual
    # candidates show large absolute reversions, so include with stricter
    # spread gate so we only act when their book is unusually tight.
    "MICROCHIP_SQUARE":           (0.084, 12),
    "PEBBLES_XL":                 (0.030, 14),
}

# Global guardrails (ken_round5_execution_sweep.md best config: hold=1, spread_max=8).
SHOCK_BASE = 8.0
SHOCK_SPREAD_MULT = 1.30   # require shock >= 1.3 * spread on top of SHOCK_BASE
HOLD_TICKS = 1             # exit on the very next tick

BASE_CLIP = 4              # smaller than trader1 - shock fade is a thin trade
MAX_CLIP = 12              # hard cap per entry

# Per-symbol clip scale: higher quality -> larger size.
QUALITY_REF = 0.15


def _family(symbol: str) -> str:
    for prefix in FAMILY_PREFIXES:
        if symbol.startswith(prefix + "_"):
            return prefix
    return symbol.split("_", 1)[0]


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
            "last_mid": {},
            "entry_ts": {},
        }

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _best_bid_ask(self, state: TradingState, symbol: str):
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def _caps(self, symbol: str, position: Dict[str, int]):
        fam = _family(symbol)
        lim = FAMILY_LIMITS.get(fam, DEFAULT_LIMIT)
        pos = position.get(symbol, 0)
        return lim, max(0, lim - pos), max(0, lim + pos)

    def run(self, state: TradingState):
        mem = self._load(state.traderData)

        # Day rollover (timestamps reset to 0).
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["day_idx"] += 1
            mem["last_mid"] = {}
            mem["entry_ts"] = {}
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        for symbol in state.order_depths.keys():
            if symbol not in WHITELIST:
                continue
            quality, sym_spread_cap = WHITELIST[symbol]

            bid, ask = self._best_bid_ask(state, symbol)
            if bid is None or ask is None:
                continue
            spread = max(1, ask - bid)
            mid = 0.5 * (bid + ask)

            last = mem["last_mid"].get(symbol, mid)
            d_mid = mid - last
            mem["last_mid"][symbol] = mid

            pos = state.position.get(symbol, 0)
            entry_ts = mem["entry_ts"].get(symbol, -1)
            _, buy_cap, sell_cap = self._caps(symbol, state.position)

            # ---- Exit leg: hold = 1 tick ----
            if pos != 0 and entry_ts >= 0:
                ticks_held = (state.timestamp - entry_ts) // 100
                if ticks_held >= HOLD_TICKS:
                    if pos > 0 and sell_cap > 0:
                        result[symbol].append(Order(symbol, bid, -min(pos, sell_cap)))
                    elif pos < 0 and buy_cap > 0:
                        result[symbol].append(Order(symbol, ask, min(-pos, buy_cap)))
                    mem["entry_ts"][symbol] = -1
                continue

            # ---- Entry filters ----
            if pos != 0:
                continue                                    # already in a trade
            if spread > sym_spread_cap:
                continue                                    # only trade in the tight regime
            trigger = max(SHOCK_BASE, SHOCK_SPREAD_MULT * spread)
            if abs(d_mid) < trigger:
                continue                                    # not a real shock

            # Net expected edge = expected reversion - round-trip spread.
            # Skip when |d_mid| is barely above spread cost.
            if abs(d_mid) < spread + 1.0:
                continue

            # Clip scales with shock magnitude AND with published signal quality.
            magnitude_scale = min(2.0, abs(d_mid) / max(trigger, 1.0))
            quality_scale = max(0.5, min(2.0, quality / QUALITY_REF))
            clip = max(1, int(BASE_CLIP * magnitude_scale * quality_scale))
            clip = min(clip, MAX_CLIP)

            if d_mid <= -trigger and buy_cap > 0:
                qty = min(clip, buy_cap)
                if qty > 0:
                    result[symbol].append(Order(symbol, ask, qty))
                    mem["entry_ts"][symbol] = state.timestamp
            elif d_mid >= trigger and sell_cap > 0:
                qty = min(clip, sell_cap)
                if qty > 0:
                    result[symbol].append(Order(symbol, bid, -qty))
                    mem["entry_ts"][symbol] = state.timestamp

        return dict(result), 0, self._save(mem)
