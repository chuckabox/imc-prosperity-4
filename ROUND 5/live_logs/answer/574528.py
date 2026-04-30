import json
import math
from collections import defaultdict
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

# ANSWER.PY: 100% Passive Market Maker with Alpha Skewing
LIMIT = 10
MM_CLIP = 5
INV_SKEW = 0.25 # Move fair price by this per unit of inventory
LEADER = "GALAXY_SOUNDS_BLACK_HOLES"
LAG = "SLEEP_POD_POLYESTER"
LL_LOOKBACK = 100

class Trader:
    def _load(self, td: str) -> Dict:
        if not td: return self._empty()
        try:
            mem = json.loads(td)
            for k, v in self._empty().items(): mem.setdefault(k, v)
            return mem
        except: return self._empty()

    def _empty(self) -> Dict:
        return {
            "last_ts": -1,
            "bh_hist": [],
            "poly_hist": [],
        }

    def _save(self, mem: Dict) -> str:
        mem["bh_hist"] = mem["bh_hist"][-LL_LOOKBACK:]
        mem["poly_hist"] = mem["poly_hist"][-LL_LOOKBACK:]
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders: return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def _get_corr_sign(self, x: List[float], y: List[float]) -> float:
        if len(x) < 50 or len(y) < 50: return 1.0
        n = min(len(x), len(y))
        xm, ym = sum(x[-n:])/n, sum(y[-n:])/n
        cov = sum((x[-i]-xm)*(y[-i]-ym) for i in range(1, n+1))
        return 1.0 if cov >= 0 else -1.0

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]: mem = self._empty()
        mem["last_ts"] = state.timestamp
        
        result: Dict[str, List[Order]] = defaultdict(list)
        
        # 1. Alpha tracking (Leader-Lag)
        bh_bid, bh_ask = self._bba(state, LEADER)
        poly_bid, poly_ask = self._bba(state, LAG)
        
        if bh_bid and bh_ask: mem["bh_hist"].append((bh_bid + bh_ask) / 2.0)
        if poly_bid and poly_ask: mem["poly_hist"].append((poly_bid + poly_ask) / 2.0)
        
        ll_skew = 0.0
        if len(mem["bh_hist"]) >= LL_LOOKBACK:
            move = mem["bh_hist"][-1] - mem["bh_hist"][0]
            sign = self._get_corr_sign(mem["bh_hist"], mem["poly_hist"])
            ll_skew = move * sign * 0.1 # Skew fair price by 10% of leader move

        # 2. Universal Passive Market Making
        for sym in state.order_depths.keys():
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None: continue
            
            mid = (bid + ask) / 2.0
            pos = state.position.get(sym, 0)
            
            # Fair price calculation
            fair = mid - (INV_SKEW * pos)
            
            # Apply Leader-Lag skew only to the LAG product
            if sym == LAG:
                fair += ll_skew
                
            # Quote 1 tick inside the spread (Maker)
            # If spread is 1, we can't quote inside. Quote at bid/ask.
            mm_bid = min(int(round(fair - 1)), ask - 1)
            mm_ask = max(int(round(fair + 1)), bid + 1)
            
            if pos < LIMIT:
                result[sym].append(Order(sym, mm_bid, min(MM_CLIP, LIMIT - pos)))
            if pos > -LIMIT:
                result[sym].append(Order(sym, mm_ask, -min(MM_CLIP, LIMIT + pos)))

        return dict(result), 0, self._save(mem)