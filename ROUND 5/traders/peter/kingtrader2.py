import json
import math
from collections import defaultdict
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

# KINGTRADER2: Adaptive Leader-Lag + Dish King
LIMIT = 10
TAKE_CLIP = 10
LEADER = "GALAXY_SOUNDS_BLACK_HOLES"
LAG = "SLEEP_POD_POLYESTER"
LL_LOOKBACK = 100
LL_CORR_WINDOW = 500 # Window to detect if corr is + or -

class Trader:
    def _load(self, td: str) -> Dict:
        if not td: return self._empty()
        try:
            mem = json.loads(td)
            for k, v in self._empty().items():
                mem.setdefault(k, v)
            return mem
        except:
            return self._empty()

    def _empty(self) -> Dict:
        return {
            "last_ts": -1,
            "bh_hist": [],
            "poly_hist": [],
            "last_mid": {},
        }

    def _save(self, mem: Dict) -> str:
        # Keep histories within limits
        mem["bh_hist"] = mem["bh_hist"][-LL_CORR_WINDOW:]
        mem["poly_hist"] = mem["poly_hist"][-LL_CORR_WINDOW:]
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders:
            return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def _get_corr(self, x: List[float], y: List[float]) -> float:
        if len(x) < 100 or len(y) < 100: return 1.0 # Default positive
        # Simple sign of covariance for speed/space
        n = min(len(x), len(y), 200)
        xs = x[-n:]
        ys = y[-n:]
        x_mean = sum(xs) / n
        y_mean = sum(ys) / n
        cov = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
        return 1.0 if cov >= 0 else -1.0

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem = self._empty()
        mem["last_ts"] = state.timestamp
        
        result: Dict[str, List[Order]] = defaultdict(list)
        
        # Track Leader and Lag
        bh_bid, bh_ask = self._bba(state, LEADER)
        poly_bid, poly_ask = self._bba(state, LAG)
        
        if bh_bid and bh_ask:
            bh_mid = (bh_bid + bh_ask) / 2.0
            mem["bh_hist"].append(bh_mid)
        if poly_bid and poly_ask:
            poly_mid = (poly_bid + poly_ask) / 2.0
            mem["poly_hist"].append(poly_mid)

        # 1. Leader-Lag Strategy (Adaptive)
        if len(mem["bh_hist"]) > LL_LOOKBACK and poly_bid and poly_ask:
            bh_move = mem["bh_hist"][-1] - mem["bh_hist"][-LL_LOOKBACK]
            corr_sign = self._get_corr(mem["bh_hist"], mem["poly_hist"])
            
            signal = bh_move * corr_sign
            lag_pos = state.position.get(LAG, 0)
            
            if signal > 4.0 and lag_pos < LIMIT:
                result[LAG].append(Order(LAG, poly_ask, LIMIT - lag_pos))
            elif signal < -4.0 and lag_pos > -LIMIT:
                result[LAG].append(Order(LAG, poly_bid, - (LIMIT + lag_pos)))

        # 2. Dish King MM
        sym = "ROBOT_DISHES"
        if sym in state.order_depths:
            bid, ask = self._bba(state, sym)
            if bid and ask:
                mid = (bid + ask) / 2.0
                pos = state.position.get(sym, 0)
                fair = mid - (0.2 * pos)
                result[sym].append(Order(sym, min(int(round(fair - 1)), ask - 1), 5))
                result[sym].append(Order(sym, max(int(round(fair + 1)), bid + 1), -5))

        return dict(result), 0, self._save(mem)
