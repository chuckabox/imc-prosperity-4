import json
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from datamodel import Order, TradingState


class Trader:
    """
    heaven_we_comingv4:
    - Keep v3 passive MM + inventory skew core.
    - Add selected day4-positive symbols from answer.py (controlled breadth).
    - Maintain strict per-symbol limit 10 and spread gates.
    """

    LIMIT = 10
    MM_CLIP = 2
    INV_SKEW = 0.20

    LEADER = "ROBOT_DISHES"
    LAG = "TRANSLATOR_ASTRO_BLACK"
    LL_LOOKBACK = 80
    LL_MULT = 0.05

    # symbol -> max spread allowed to quote
    SYMBOLS: Dict[str, int] = {
        # v3 core
        "ROBOT_DISHES": 7,
        "ROBOT_IRONING": 6,
        "ROBOT_VACUUMING": 7,
        "ROBOT_LAUNDRY": 7,
        "ROBOT_MOPPING": 8,
        "TRANSLATOR_ASTRO_BLACK": 8,
        "TRANSLATOR_ECLIPSE_CHARCOAL": 8,
        "TRANSLATOR_VOID_BLUE": 9,
        "PANEL_2X2": 9,
        "PANEL_2X4": 10,
        "MICROCHIP_OVAL": 8,
        "MICROCHIP_RECTANGLE": 8,
        # controlled expansion from answer day4 positives
        "PANEL_1X4": 9,
        "OXYGEN_SHAKE_CHOCOLATE": 12,
        "OXYGEN_SHAKE_EVENING_BREATH": 12,
        "SLEEP_POD_POLYESTER": 11,
        "SLEEP_POD_NYLON": 10,
        "PEBBLES_S": 12,
        "PEBBLES_XL": 15,
        "UV_VISOR_AMBER": 11,
    }

    def _empty(self) -> Dict:
        return {
            "last_ts": -1,
            "leader_hist": [],
            "lag_hist": [],
        }

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
        mem["leader_hist"] = mem["leader_hist"][-self.LL_LOOKBACK:]
        mem["lag_hist"] = mem["lag_hist"][-self.LL_LOOKBACK:]
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str) -> Tuple[Optional[int], Optional[int]]:
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders:
            return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def _corr_sign(self, x: List[float], y: List[float]) -> float:
        if len(x) < 40 or len(y) < 40:
            return 1.0
        n = min(len(x), len(y))
        xm = sum(x[-n:]) / n
        ym = sum(y[-n:]) / n
        cov = sum((x[-i] - xm) * (y[-i] - ym) for i in range(1, n + 1))
        return 1.0 if cov >= 0 else -1.0

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem = self._empty()
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)

        l_bid, l_ask = self._bba(state, self.LEADER)
        g_bid, g_ask = self._bba(state, self.LAG)
        if l_bid is not None and l_ask is not None:
            mem["leader_hist"].append((l_bid + l_ask) / 2.0)
        if g_bid is not None and g_ask is not None:
            mem["lag_hist"].append((g_bid + g_ask) / 2.0)

        ll_skew = 0.0
        if len(mem["leader_hist"]) >= self.LL_LOOKBACK:
            move = mem["leader_hist"][-1] - mem["leader_hist"][0]
            sign = self._corr_sign(mem["leader_hist"], mem["lag_hist"])
            ll_skew = move * sign * self.LL_MULT

        for sym in sorted(self.SYMBOLS.keys()):
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None:
                continue

            spread = ask - bid
            if spread <= 0 or spread > self.SYMBOLS[sym]:
                continue

            pos = state.position.get(sym, 0)
            mid = (bid + ask) / 2.0
            fair = mid - (self.INV_SKEW * pos)
            if sym == self.LAG:
                fair += ll_skew

            if spread >= 2:
                q_bid = min(int(round(fair - 1)), ask - 1)
                q_ask = max(int(round(fair + 1)), bid + 1)
            else:
                q_bid = bid
                q_ask = ask

            if q_bid >= ask:
                q_bid = ask - 1
            if q_ask <= bid:
                q_ask = bid + 1
            if q_bid >= q_ask:
                continue

            if pos < self.LIMIT:
                qty = min(self.MM_CLIP, self.LIMIT - pos)
                if qty > 0:
                    result[sym].append(Order(sym, q_bid, qty))
            if pos > -self.LIMIT:
                qty = min(self.MM_CLIP, self.LIMIT + pos)
                if qty > 0:
                    result[sym].append(Order(sym, q_ask, -qty))

        return dict(result), 0, self._save(mem)
