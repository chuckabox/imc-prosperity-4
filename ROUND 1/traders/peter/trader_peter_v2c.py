import json
import math
from typing import Dict, List, Any

from datamodel import Order, OrderDepth, TradingState, Symbol


class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        conversions: int,
        trader_data: str,
    ) -> None:
        pass


logger = Logger()


class Trader:
    """
    Peter V2c: The Refined Sniper
    -----------------------------
    Fixed v2 "Stuck in Storm" bug by moving unwind before vol clamp.
    Reduced Osmium tape threshold for better activation.
    Added trailing-stop style exits to smooth the curve.
    """

    LIMIT_OSMIUM = 80
    LIMIT_PEPPER = 80

    def __init__(self):
        self.history = {}

    def _load_state(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except Exception:
                self.history = {}

    def _ema(self, prices: list, span: int) -> float:
        if not prices: return 0.0
        alpha = 2.0 / (span + 1)
        val = prices[0]
        for p in prices[1:]:
            val = alpha * p + (1 - alpha) * val
        return val

    def _get_mid(self, depth: OrderDepth) -> float:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb and ba: return (bb + ba) / 2.0
        return bb or ba or 0.0

    def _calculate_ofi(self, product: str, depth: OrderDepth) -> float:
        pk = f"{product}_l1"
        p_l = self.history.get(pk, {})
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else 0
        bq = depth.buy_orders.get(bb, 0)
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else 0
        aq = abs(depth.sell_orders.get(ba, 0))
        if not p_l:
            self.history[pk] = {"bb": bb, "bq": bq, "ba": ba, "aq": aq}
            return 0.0
        db = bq if bb > p_l["bb"] else (bq - p_l["bq"] if bb == p_l["bb"] else -p_l["bq"])
        da = aq if ba < p_l["ba"] else (aq - p_l["aq"] if ba == p_l["ba"] else -p_l["aq"])
        self.history[pk] = {"bb": bb, "bq": bq, "ba": ba, "aq": aq}
        return db - da

    def _pepper_logic(self, state: TradingState) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths: return []
        depth = state.order_depths[product]
        pos = state.position.get(product, 0)
        mid = self._get_mid(depth)
        
        hist = self.history.get("pp", [])
        hist.append(mid)
        if len(hist) > 100: hist.pop(0)
        self.history["pp"] = hist
        if len(hist) < 40: return []

        ema_f = self._ema(hist, 8)
        ema_s = self._ema(hist, 24)
        vol = max(1.0, float(max(hist[-15:]) - min(hist[-15:])))
        
        ofi = self._calculate_ofi(product, depth)
        ofi_acc = self.history.get("pp_o_acc", 0) * 0.4 + ofi * 0.6
        self.history["pp_o_acc"] = ofi_acc
        
        trend = (ema_f - ema_s) / (vol * 0.1 + 0.1)
        
        orders = []
        rem_buy = 80 - pos
        rem_sell = 80 + pos
        
        ba = min(depth.sell_orders.items())[0] if depth.sell_orders else None
        bb = max(depth.buy_orders.items())[0] if depth.buy_orders else None

        # 1. EMERGENCY UNWIND (Moved BEFORE vol clamp)
        # If trend reverses sharply, exit immediately regardless of volatility
        if (pos > 0 and trend < -0.8) or (pos < 0 and trend > 0.8):
            if pos > 0 and bb: 
                q = min(pos, 30) # Aggressive exit
                orders.append(Order(product, bb, int(-q)))
                pos -= q
                rem_sell += q
            elif pos < 0 and ba: 
                q = min(abs(pos), 30)
                orders.append(Order(product, ba, int(q)))
                pos += q
                rem_buy += q

        # 2. VOLATILITY CLAMP
        if vol > 45: return orders # Adaptive: increased from 35
        
        # 3. ENTRY SIGNALS
        signal_buy = trend > 1.2 and ofi_acc > 7
        signal_sell = trend < -1.2 and ofi_acc < -7
        
        if ba and signal_buy and rem_buy > 0:
            q = min(rem_buy, abs(depth.sell_orders.get(ba, 0)), 15)
            orders.append(Order(product, ba, int(q)))
        elif bb and signal_sell and rem_sell > 0:
            q = min(rem_sell, depth.buy_orders.get(bb, 0), 15)
            orders.append(Order(product, bb, int(-q)))
            
        # 4. SOFT EXIT (Smooth the curve)
        # If trend is neutral but we have position, scale out slowly
        if pos > 0 and trend < 0.2:
            if bb: orders.append(Order(product, bb, -min(pos, 10)))
        elif pos < 0 and trend > -0.2:
            if ba: orders.append(Order(product, ba, min(abs(pos), 10)))

        return orders

    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths: return []
        depth = state.order_depths[product]
        pos = state.position.get(product, 0)
        mid = self._get_mid(depth)
        
        hist = self.history.get("op", [])
        hist.append(mid)
        if len(hist) > 100: hist.pop(0)
        self.history["op"] = hist
        if len(hist) < 30: return []

        anchor = self._ema(hist, 40)
        
        tape_val = 0.0
        if product in state.market_trades:
            for t in state.market_trades[product]:
                tape_val += t.quantity if t.price >= mid else -t.quantity
        
        # Lower tape filter for activation (8 instead of 10)
        self.history["o_tape"] = self.history.get("o_tape", 0) * 0.6 + tape_val * 0.4
        
        # High Conviction Entry
        signal_buy = self.history["o_tape"] > 8 and mid > anchor
        signal_sell = self.history["o_tape"] < -8 and mid < anchor
        
        orders = []
        rem_buy = 80 - pos
        rem_sell = 80 + pos
        
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None

        if ba and signal_buy and rem_buy > 0:
            orders.append(Order(product, ba, min(rem_buy, 20)))
        elif bb and signal_sell and rem_sell > 0:
            orders.append(Order(product, bb, -min(rem_sell, 20)))
            
        # Safer Passive Exit (moved before we get stuck)
        if pos != 0:
            if pos > 0 and ba: orders.append(Order(product, ba, -min(pos, 5)))
            if pos < 0 and bb: orders.append(Order(product, bb, min(abs(pos), 5)))

        return orders

    def run(self, state: TradingState):
        self._load_state(state.traderData)
        result = {}
        pep = self._pepper_logic(state)
        if pep: result["INTARIAN_PEPPER_ROOT"] = pep
        osm = self._osmium_logic(state)
        if osm: result["ASH_COATED_OSMIUM"] = osm
        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
