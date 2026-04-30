import json
import math
from collections import defaultdict
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

# KINGTRADER3: Sid's Sweet Spot + Peter's Dishes + Adaptive Leader-Lag
POS_LIMIT = 10
TAKE_CLIP = 5
LL_LOOKBACK = 100
LL_CORR_WINDOW = 500

class Trader:
    # Sid's & Peter's optimized targets
    PARAMS = {
        "MICROCHIP_RECTANGLE": {"trigger": 16.0, "big_shock": 24.0, "max_spread": 9},
        "MICROCHIP_TRIANGLE":  {"trigger": 13.0, "big_shock": 22.0, "max_spread": 12},
        "PEBBLES_S":           {"trigger": 15.0, "big_shock": 25.0, "max_spread": 12},
        "PEBBLES_M":           {"trigger": 15.0, "big_shock": 25.0, "max_spread": 13},
        "PEBBLES_L":           {"trigger": 14.0, "big_shock": 24.0, "max_spread": 13},
        "ROBOT_DISHES":        {"mm": True, "skew": 0.25, "edge": 1},
        "SLEEP_POD_POLYESTER": {"ll": True, "leader": "GALAXY_SOUNDS_BLACK_HOLES"},
    }

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
            "last_mid": {},
            "entries": {},
            "bh_hist": [],
            "poly_hist": [],
        }

    def _save(self, mem: Dict) -> str:
        # Keep histories within limits
        mem["bh_hist"] = mem["bh_hist"][-LL_CORR_WINDOW:]
        mem["poly_hist"] = mem["poly_hist"][-LL_CORR_WINDOW:]
        return json.dumps(mem, separators=(",", ":"))

    def _best_bid_ask(self, state: TradingState, sym: str) -> Tuple[int, int]:
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders: return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def _get_corr_sign(self, x: List[float], y: List[float]) -> float:
        if len(x) < 100 or len(y) < 100: return 1.0
        n = min(len(x), len(y), 200)
        xs, ys = x[-n:], y[-n:]
        xm, ym = sum(xs)/n, sum(ys)/n
        cov = sum((xs[i]-xm)*(ys[i]-ym) for i in range(n))
        return 1.0 if cov >= 0 else -1.0

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]: mem = self._empty()
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)
        
        # Track LL history
        for sym in ["GALAXY_SOUNDS_BLACK_HOLES", "SLEEP_POD_POLYESTER"]:
            bid, ask = self._best_bid_ask(state, sym)
            if bid and ask:
                mid = (bid + ask) / 2.0
                hist_key = "bh_hist" if "BLACK" in sym else "poly_hist"
                mem[hist_key].append(mid)

        for sym, cfg in self.PARAMS.items():
            bid, ask = self._best_bid_ask(state, sym)
            if bid is None or ask is None: continue
            mid = (bid + ask) / 2.0
            pos = state.position.get(sym, 0)
            
            # --- EXIT: Sid's 1-tick hold logic ---
            ent = mem["entries"].get(sym)
            if ent:
                if state.timestamp > ent["ts"]:
                    if pos > 0: result[sym].append(Order(sym, bid, -pos))
                    elif pos < 0: result[sym].append(Order(sym, ask, -pos))
                    mem["entries"].pop(sym, None)
                continue

            # --- ENTRY: Strategy Selection ---
            
            # 1. Leader-Lag (Adaptive)
            if cfg.get("ll"):
                leader = cfg["leader"]
                if len(mem["bh_hist"]) > LL_LOOKBACK and len(mem["poly_hist"]) > 0:
                    bh_move = mem["bh_hist"][-1] - mem["bh_hist"][-LL_LOOKBACK]
                    sign = self._get_corr_sign(mem["bh_hist"], mem["poly_hist"])
                    signal = bh_move * sign
                    if abs(signal) > 5.0 and pos == 0:
                        if signal > 0: result[sym].append(Order(sym, ask, POS_LIMIT))
                        else: result[sym].append(Order(sym, bid, -POS_LIMIT))
                        mem["entries"][sym] = {"ts": state.timestamp}
                continue

            # 2. Market Making (Dishes)
            if cfg.get("mm"):
                fair = mid - (cfg["skew"] * pos)
                result[sym].append(Order(sym, min(int(round(fair - cfg["edge"])), ask - 1), 5))
                result[sym].append(Order(sym, max(int(round(fair + cfg["edge"])), bid + 1), -5))
                continue

            # 3. Shock Fade (Sid's Sweet Spot)
            last_mid = mem["last_mid"].get(sym, mid)
            d_mid = mid - last_mid
            mem["last_mid"][sym] = mid
            
            if pos == 0 and abs(d_mid) >= cfg["trigger"] and (ask - bid) <= cfg["max_spread"]:
                qty = min(TAKE_CLIP, max(1, int(abs(d_mid)/4)))
                if d_mid >= cfg["trigger"]: # Spike -> Sell
                    result[sym].append(Order(sym, bid, -qty))
                else: # Drop -> Buy
                    result[sym].append(Order(sym, ask, qty))
                mem["entries"][sym] = {"ts": state.timestamp}

        return dict(result), 0, self._save(mem)
