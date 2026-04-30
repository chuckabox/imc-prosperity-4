import json
import math
from collections import defaultdict
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

# SAFEKILLER: Enhanced Market Maker with Drawdown Protection

LIMITS = {
    "AMETHYSTS": 20,
    "STARFRUIT": 20,
    "ORCHIDS": 100,
    "CHOCOLATE": 250,
    "STRAWBERRIES": 350,
    "ROSES": 60,
    "GIFT_BASKET": 60,
    "COCONUT": 300,
    "COCONUT_COUPON": 600,
    "GALAXY_SOUNDS_BLACK_HOLES": 100,
    "SLEEP_POD_POLYESTER": 100
}
DEFAULT_LIMIT = 20
MM_CLIP = 5
BASE_INV_SKEW = 0.25 # Base skew per unit of inventory
LEADER = "GALAXY_SOUNDS_BLACK_HOLES"
LAG = "SLEEP_POD_POLYESTER"
LL_LOOKBACK = 100
TREND_LOOKBACK_SHORT = 10
TREND_LOOKBACK_LONG = 50

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
            "price_hist": {} # sym -> list of mid prices
        }

    def _save(self, mem: Dict) -> str:
        mem["bh_hist"] = mem["bh_hist"][-LL_LOOKBACK:]
        mem["poly_hist"] = mem["poly_hist"][-LL_LOOKBACK:]
        for sym in mem["price_hist"]:
            mem["price_hist"][sym] = mem["price_hist"][sym][-TREND_LOOKBACK_LONG:]
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

    def get_limit(self, sym: str) -> int:
        return LIMITS.get(sym, DEFAULT_LIMIT)

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

        # 2. Universal Passive Market Making with Drawdown Protection
        for sym in state.order_depths.keys():
            bid, ask = self._bba(state, sym)
            if bid is None or ask is None: continue
            
            mid = (bid + ask) / 2.0
            pos = state.position.get(sym, 0)
            limit = self.get_limit(sym)
            
            if sym not in mem["price_hist"]: mem["price_hist"][sym] = []
            mem["price_hist"][sym].append(mid)
            hist = mem["price_hist"][sym]
            
            # Trend Detection for Toxic Flow Protection
            trend_adj = 0.0
            if len(hist) >= TREND_LOOKBACK_SHORT:
                ma_short = sum(hist[-TREND_LOOKBACK_SHORT:]) / TREND_LOOKBACK_SHORT
                if len(hist) >= TREND_LOOKBACK_LONG:
                    ma_long = sum(hist[-TREND_LOOKBACK_LONG:]) / TREND_LOOKBACK_LONG
                    trend_diff = ma_short - ma_long
                    # If short-term is higher than long-term, price is trending up. 
                    # We should shift fair price up to avoid getting filled on asks too easily.
                    trend_adj = trend_diff * 0.5

            # Dynamic Inventory Skew (Non-linear to prevent max inventory buildup)
            # As position approaches limit, skew increases quadratically
            pos_ratio = pos / limit
            inv_skew_factor = BASE_INV_SKEW * (1.0 + abs(pos_ratio) * 2.0)
            
            # Fair price calculation
            fair = mid - (inv_skew_factor * pos) + trend_adj
            
            # Apply Leader-Lag skew only to the LAG product
            if sym == LAG:
                fair += ll_skew
                
            # Quote determination
            # We widen our spread if volatility/trend is high to protect capital
            edge = 1 + abs(trend_adj) * 0.5
            
            optimal_bid = int(round(fair - edge))
            optimal_ask = int(round(fair + edge))
            
            mm_bid = min(optimal_bid, ask - 1)
            mm_ask = max(optimal_ask, bid + 1)
            
            # Drawdown cut-loss mechanism (Cross spread if inventory is critical and trend is against us)
            if pos_ratio > 0.8 and trend_adj < -0.5: # Long position, price crashing
                mm_ask = bid # Hit the bid to dump
            elif pos_ratio < -0.8 and trend_adj > 0.5: # Short position, price pumping
                mm_bid = ask # Hit the ask to cover
            
            # Sizing: Scale down clip size as we approach limits
            bid_clip = max(1, int(MM_CLIP * (1 - max(0, pos_ratio))))
            ask_clip = max(1, int(MM_CLIP * (1 - max(0, -pos_ratio))))
            
            if pos < limit:
                result[sym].append(Order(sym, mm_bid, min(bid_clip, limit - pos)))
            if pos > -limit:
                result[sym].append(Order(sym, mm_ask, -min(ask_clip, limit + pos)))

        return dict(result), 0, self._save(mem)
