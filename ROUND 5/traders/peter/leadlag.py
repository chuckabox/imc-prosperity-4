import json
from collections import deque
from typing import Dict, List
from datamodel import Order, TradingState

# LEAD-LAG strategy for BLACK_HOLES and POLYESTER
# Leader: GALAXY_SOUNDS_BLACK_HOLES
# Laggard: SLEEP_POD_POLYESTER
# Lookback: 100

SYM_LIMIT = 10
LOOKBACK = 100
EDGE = 1
SIGNAL_THRESH = 5.0 # Min move in leader to trigger lag trade

class Trader:
    def _load(self, td: str) -> Dict:
        if not td: return self._empty()
        try:
            mem = json.loads(td)
            # JSON doesn't support deques, convert lists back
            mem["h_lead"] = deque(mem.get("h_lead", []), maxlen=LOOKBACK)
            mem["h_lag"] = deque(mem.get("h_lag", []), maxlen=LOOKBACK)
            return mem
        except:
            return self._empty()

    def _empty(self) -> Dict:
        return {
            "last_ts": -1,
            "h_lead": deque(maxlen=LOOKBACK),
            "h_lag": deque(maxlen=LOOKBACK),
            "ratio_ewma": 1.0,
        }

    def _save(self, mem: Dict) -> str:
        # Convert deques to lists for JSON
        out = mem.copy()
        out["h_lead"] = list(mem["h_lead"])
        out["h_lag"] = list(mem["h_lag"])
        return json.dumps(out, separators=(",", ":"))

    def _mid(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders:
            return None
        return (max(d.buy_orders.keys()) + min(d.sell_orders.keys())) / 2.0

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem = self._empty()
        mem["last_ts"] = state.timestamp

        LEAD = "GALAXY_SOUNDS_BLACK_HOLES"
        LAG = "SLEEP_POD_POLYESTER"

        mid_lead = self._mid(state, LEAD)
        mid_lag = self._mid(state, LAG)

        if mid_lead is None or mid_lag is None:
            return {}, 0, self._save(mem)

        # Update history
        mem["h_lead"].append(mid_lead)
        mem["h_lag"].append(mid_lag)

        # Update running ratio
        mem["ratio_ewma"] = 0.99 * mem["ratio_ewma"] + 0.01 * (mid_lag / mid_lead)

        if len(mem["h_lead"]) < LOOKBACK:
            return {}, 0, self._save(mem)

        # Signal: Leader move vs its own 100-tick average
        avg_lead = sum(mem["h_lead"]) / len(mem["h_lead"])
        lead_dev = mid_lead - avg_lead
        
        # Predicted lag
        pred_lag = mid_lead * mem["ratio_ewma"]
        lag_dev = mid_lag - pred_lag

        result = {}
        orders = []
        
        pos_lag = state.position.get(LAG, 0)
        
        # If leader is significantly above its average, but lag is still below its predicted
        # it means lag is LAGGING the upward move -> BUY LAG.
        if lead_dev > SIGNAL_THRESH and lag_dev < -2.0:
            buy_q = min(SYM_LIMIT - pos_lag, 2)
            if buy_q > 0:
                ask_lag = min(state.order_depths[LAG].sell_orders.keys())
                orders.append(Order(LAG, ask_lag, buy_q))
        elif lead_dev < -SIGNAL_THRESH and lag_dev > 2.0:
            sell_q = min(SYM_LIMIT + pos_lag, 2)
            if sell_q > 0:
                bid_lag = max(state.order_depths[LAG].buy_orders.keys())
                orders.append(Order(LAG, bid_lag, -sell_q))

        if orders:
            result[LAG] = orders

        return result, 0, self._save(mem)
