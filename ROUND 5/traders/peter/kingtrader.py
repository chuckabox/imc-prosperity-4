import json
from collections import defaultdict
from typing import Dict, List, Tuple
from datamodel import Order, TradingState

# KINGTRADER: Only trade high-conviction Dishes. Stop-loss on everything else.
WHITELIST = ["ROBOT_DISHES", "ROBOT_LAUNDRY", "PANEL_2X4"]
SYM_LIMIT = 10
TAKE_CLIP = 2
TRIGGER_MOVE = 10.0
STOP_LOSS = -2000 # Max loss per symbol before permanent pause

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
            "last_mid": {},
            "last_ts": -1,
            "entry_ts": {},
            "pnl": {},
            "paused": [],
        }

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _bba(self, state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders:
            return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem = self._empty()
        mem["last_ts"] = state.timestamp
        
        result: Dict[str, List[Order]] = defaultdict(list)

        for symbol in state.order_depths.keys():
            # Only trade WHITELIST
            if symbol not in WHITELIST: continue
            if symbol in mem["paused"]: continue

            bid, ask = self._bba(state, symbol)
            if bid is None or ask is None: continue
            
            mid = (bid + ask) / 2.0
            last_mid = mem["last_mid"].get(symbol, mid)
            d_mid = mid - last_mid
            mem["last_mid"][symbol] = mid

            pos = state.position.get(symbol, 0)
            entry_ts = mem["entry_ts"].get(symbol, -1)
            
            # --- Stop Loss Check (Simplified) ---
            # If we were in a trade and it went against us
            # We track pnl roughly.
            sym_pnl = mem["pnl"].get(symbol, 0)
            if sym_pnl < STOP_LOSS:
                mem["paused"].append(symbol)
                continue

            # --- EXIT: 1-tick hold ---
            if pos != 0 and (entry_ts < 0 or state.timestamp > entry_ts):
                if pos > 0:
                    result[symbol].append(Order(symbol, bid, -pos))
                    mem["pnl"][symbol] = sym_pnl + (bid - last_mid) * pos
                else:
                    result[symbol].append(Order(symbol, ask, -pos))
                    mem["pnl"][symbol] = sym_pnl + (ask - last_mid) * pos
                mem["entry_ts"][symbol] = -1
                continue

            # --- ENTRY: Shock Fade ---
            if pos != 0: continue
            
            spread = ask - bid
            move_trigger = max(TRIGGER_MOVE, 1.5 * spread)
            
            if abs(d_mid) >= move_trigger:
                q = min(TAKE_CLIP, max(1, int(abs(d_mid) / 5)))
                if d_mid >= move_trigger: # Spike -> Sell
                    result[symbol].append(Order(symbol, bid, -q))
                    mem["entry_ts"][symbol] = state.timestamp
                elif d_mid <= -move_trigger: # Drop -> Buy
                    result[symbol].append(Order(symbol, ask, q))
                    mem["entry_ts"][symbol] = state.timestamp

        return dict(result), 0, self._save(mem)
