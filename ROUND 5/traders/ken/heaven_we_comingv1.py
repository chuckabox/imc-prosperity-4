import json
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from datamodel import Order, TradingState


class Trader:
    """
    Round 5 v1 trader:
    - Core alpha: one-tick shock fade.
    - Universe: quality-filtered whitelist from Round 5 docs.
    - Risk: strict per-symbol limit 10 (challenge hard rule) + soft family caps.
    - Execution: spread-gated entries, deterministic one-tick exits.
    """

    SYMBOL_LIMIT = 10
    HOLD_TICKS = 1
    SHOCK_BASE = 8.0
    SHOCK_SPREAD_MULT = 1.25
    EDGE_BUFFER = 1.0

    FAMILY_CAPS = {
        "ROBOT": 25,
        "TRANSLATOR": 25,
        "PANEL": 15,
        "MICROCHIP": 15,
        "PEBBLES": 10,
        "SLEEP_POD": 10,
    }

    # symbol -> (quality_score, max_entry_spread)
    WHITELIST: Dict[str, Tuple[float, int]] = {
        # Tier A (always on)
        "ROBOT_DISHES": (0.254, 7),
        "ROBOT_IRONING": (0.213, 6),
        "ROBOT_VACUUMING": (0.173, 7),
        "ROBOT_LAUNDRY": (0.159, 7),
        "ROBOT_MOPPING": (0.156, 8),
        "TRANSLATOR_ASTRO_BLACK": (0.151, 8),
        "TRANSLATOR_ECLIPSE_CHARCOAL": (0.135, 9),
        "TRANSLATOR_GRAPHITE_MIST": (0.134, 9),
        "TRANSLATOR_SPACE_GRAY": (0.132, 9),
        "TRANSLATOR_VOID_BLUE": (0.113, 10),
        "PANEL_2X2": (0.135, 9),
        "PANEL_2X4": (0.110, 10),
        "PANEL_4X4": (0.132, 9),
        # Tier B (conditional)
        "MICROCHIP_OVAL": (0.165, 8),
        "MICROCHIP_RECTANGLE": (0.162, 8),
        "MICROCHIP_CIRCLE": (0.152, 8),
        "MICROCHIP_TRIANGLE": (0.142, 9),
        "MICROCHIP_SQUARE": (0.084, 11),
        "PEBBLES_XL": (0.030, 14),
        "SLEEP_POD_NYLON": (0.131, 9),
    }

    def _empty_state(self) -> Dict:
        return {
            "last_ts": -1,
            "last_mid": {},
            "entry_ts": {},
            "cooldown_until": {},
        }

    def _load(self, data: str) -> Dict:
        if not data:
            return self._empty_state()
        try:
            out = json.loads(data)
        except Exception:
            return self._empty_state()
        base = self._empty_state()
        for k, v in base.items():
            out.setdefault(k, v)
        return out

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _family(self, symbol: str) -> str:
        return symbol.split("_", 1)[0]

    def _best_bid_ask(self, state: TradingState, symbol: str) -> Tuple[Optional[int], Optional[int]]:
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def _family_abs_exposure(self, position: Dict[str, int], family: str) -> int:
        total = 0
        for sym, pos in position.items():
            if self._family(sym) == family:
                total += abs(pos)
        return total

    def _caps(self, symbol: str, position: Dict[str, int]) -> Tuple[int, int]:
        pos = position.get(symbol, 0)
        buy_cap = max(0, self.SYMBOL_LIMIT - pos)
        sell_cap = max(0, self.SYMBOL_LIMIT + pos)
        return buy_cap, sell_cap

    def _size_from_signal(self, symbol: str, spread: int, d_mid: float) -> int:
        quality, _ = self.WHITELIST[symbol]
        trigger = max(self.SHOCK_BASE, self.SHOCK_SPREAD_MULT * spread)
        mag_scale = min(2.0, abs(d_mid) / max(trigger, 1.0))
        q_scale = max(0.6, min(1.8, quality / 0.15))
        base = 3
        return max(1, min(self.SYMBOL_LIMIT, int(base * mag_scale * q_scale)))

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem = self._empty_state()
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        for symbol in sorted(state.order_depths.keys()):
            if symbol not in self.WHITELIST:
                continue

            bid, ask = self._best_bid_ask(state, symbol)
            if bid is None or ask is None:
                continue

            spread = max(1, ask - bid)
            quality, spread_cap = self.WHITELIST[symbol]
            pos = state.position.get(symbol, 0)
            buy_cap, sell_cap = self._caps(symbol, state.position)

            mid = 0.5 * (bid + ask)
            last_mid = mem["last_mid"].get(symbol, mid)
            d_mid = mid - last_mid
            mem["last_mid"][symbol] = mid

            # Exit on next tick for deterministic behavior.
            entry_ts = mem["entry_ts"].get(symbol, -1)
            if pos != 0 and entry_ts >= 0:
                held_ticks = (state.timestamp - entry_ts) // 100
                if held_ticks >= self.HOLD_TICKS:
                    if pos > 0 and sell_cap > 0:
                        result[symbol].append(Order(symbol, bid, -min(pos, sell_cap)))
                    elif pos < 0 and buy_cap > 0:
                        result[symbol].append(Order(symbol, ask, min(-pos, buy_cap)))
                    mem["entry_ts"][symbol] = -1
                    mem["cooldown_until"][symbol] = state.timestamp + 100
                continue

            # Entry filters
            if pos != 0:
                continue
            if spread > spread_cap:
                continue
            if state.timestamp < mem["cooldown_until"].get(symbol, -1):
                continue

            trigger = max(self.SHOCK_BASE, self.SHOCK_SPREAD_MULT * spread)
            if abs(d_mid) < trigger:
                continue

            # Taker entry only when expected reversion clears cost buffer.
            if abs(d_mid) < (spread + self.EDGE_BUFFER):
                continue

            family = self._family(symbol)
            fam_cap = self.FAMILY_CAPS.get(family)
            if fam_cap is not None:
                fam_abs = self._family_abs_exposure(state.position, family)
                if fam_abs >= fam_cap:
                    continue
                fam_room = max(0, fam_cap - fam_abs)
            else:
                fam_room = self.SYMBOL_LIMIT

            size = self._size_from_signal(symbol, spread, d_mid)
            size = max(1, min(size, fam_room))

            if d_mid <= -trigger and buy_cap > 0:
                qty = min(size, buy_cap)
                if qty > 0:
                    result[symbol].append(Order(symbol, ask, qty))
                    mem["entry_ts"][symbol] = state.timestamp
            elif d_mid >= trigger and sell_cap > 0:
                qty = min(size, sell_cap)
                if qty > 0:
                    result[symbol].append(Order(symbol, bid, -qty))
                    mem["entry_ts"][symbol] = state.timestamp

        return dict(result), 0, self._save(mem)
