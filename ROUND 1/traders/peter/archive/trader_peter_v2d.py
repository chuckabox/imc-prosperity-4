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
    Peter V2d: The Professional (Fixed)
    --------------------------
    Pepper: V2c Sniper (Robust, 100% Winrate logic).
    Osmium: Adaptive Market Maker (Takes and Makes).
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
        
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None

        # 1. EMERGENCY UNWIND (Fixed product reference)
        if (pos > 0 and trend < -0.8) or (pos < 0 and trend > 0.8):
            if pos > 0 and bb: 
                q = min(pos, 30)
                orders.append(Order(product, bb, int(-q)))
                pos -= int(q)
                rem_sell = 80 + pos # refresh
            elif pos < 0 and ba: 
                q = min(abs(pos), 30)
                orders.append(Order(product, ba, int(q)))
                pos += int(q)
                rem_buy = 80 - pos # refresh

        # 2. VOLATILITY CLAMP
        if vol > 45: return orders 
        
        # 3. SNIPER ENTRIES
        signal_buy = trend > 1.2 and ofi_acc > 7
        signal_sell = trend < -1.2 and ofi_acc < -7
        
        if ba and signal_buy and rem_buy > 0:
            q = min(rem_buy, abs(depth.sell_orders.get(ba, 0)), 20)
            orders.append(Order(product, ba, int(q)))
            pos += int(q)
            rem_buy = 80 - pos
            rem_sell = 80 + pos
        elif bb and signal_sell and rem_sell > 0:
            q = min(rem_sell, depth.buy_orders.get(bb, 0), 20)
            orders.append(Order(product, bb, int(-q)))
            pos -= int(q)
            rem_buy = 80 - pos
            rem_sell = 80 + pos
            
        # 4. SOFT EXIT
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
        
        # 1. TAPE TRACKING
        tape_val = 0.0
        if product in state.market_trades:
            for t in state.market_trades[product]:
                tape_val += t.quantity if t.price >= mid else -t.quantity
        self.history["o_tape"] = self.history.get("o_tape", 0) * 0.7 + tape_val * 0.3
        
        hist = self.history.get("op", [])
        hist.append(mid)
        if len(hist) > 50: hist.pop(0)
        self.history["op"] = hist
        
        # 2. FAIR PRICE DERIVATION
        # Short-mid EMA for fair price stability
        fair = self._ema(hist, 5) 
        fair += self.history["o_tape"] * 0.15
        
        orders = []
        rem_buy = 80 - pos
        rem_sell = 80 + pos
        
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        
        # 3. TAKING (Strategic sweep)
        take_margin = 2.0
        if ba and ba <= fair - take_margin and rem_buy > 0:
            q = min(rem_buy, abs(depth.sell_orders.get(ba, 0)), 15)
            orders.append(Order(product, ba, int(q)))
            pos += int(q)
        if bb and bb >= fair + take_margin and rem_sell > 0:
            q = min(rem_sell, depth.buy_orders.get(bb, 0), 15)
            orders.append(Order(product, bb, int(-q)))
            pos -= int(q)

        # 4. MAKING (Providing liquidity with dynamic skew)
        rem_buy = 80 - pos
        rem_sell = 80 + pos
        
        skew = pos * 0.08
        bid_price = math.floor(fair - 1.0 - skew)
        ask_price = math.ceil(fair + 1.0 - skew)
        
        if bb: bid_price = min(bid_price, bb + 1)
        if ba: ask_price = max(ask_price, ba - 1)
        if bid_price >= ask_price:
            bid_price = ask_price - 1
            
        if rem_buy > 0:
            orders.append(Order(product, int(bid_price), int(rem_buy)))
        if rem_sell > 0:
            orders.append(Order(product, int(ask_price), int(-rem_sell)))

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
