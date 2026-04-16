import json
import math
from typing import Dict, List, Any

from datamodel import Order, OrderDepth, TradingState, Symbol

class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: Dict[Symbol, List[Order]], conversions: int, trader_data: str) -> None:
        pass

logger = Logger()

class Trader:
    """
    Peter V4 (Robust Sniper)
    Hybrid execution. Consensus signal (EMA momentum, OFI, L1 imbalance).
    Max position throttle, volatility checks, sigmoid skew.
    """
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

    def _calculate_l1_imbalance(self, depth: OrderDepth) -> float:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else 0
        bq = depth.buy_orders.get(bb, 0)
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else 0
        aq = abs(depth.sell_orders.get(ba, 0))
        total = bq + aq
        if total == 0: return 0.0
        return (bq - aq) / total

    def _sigmoid_skew(self, pos: int, limit: int) -> float:
        x = pos / limit * 4.0
        return (1 / (1 + math.exp(-x))) * 2 - 1

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
        
        tc = self.history.get("tc", 0)
        self.history["tc"] = tc + 1

        if len(hist) < 40: return []

        ema_f = self._ema(hist, 8)
        ema_s = self._ema(hist, 24)
        vol = max(1.0, float(max(hist[-15:]) - min(hist[-15:])))
        
        high_vol = vol > 35

        ofi = self._calculate_ofi(product, depth)
        ofi_acc = self.history.get("pp_o_acc", 0) * 0.4 + ofi * 0.6
        self.history["pp_o_acc"] = ofi_acc
        
        l1_imb = self._calculate_l1_imbalance(depth)
        
        trend = (ema_f - ema_s) / (vol * 0.1 + 0.1)
        
        norm_trend = max(-1.0, min(1.0, trend / 2.0))
        norm_ofi = max(-1.0, min(1.0, ofi_acc / 10.0))
        
        consensus = norm_trend * 0.3 + norm_ofi * 0.4 + l1_imb * 0.3

        limit = 60 if tc < 100 else 80
        rem_buy = limit - pos
        rem_sell = limit + pos

        orders = []
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None

        skew = self._sigmoid_skew(pos, limit) * 2.0
        spread_half = max(1.0, vol * 0.8)
        if high_vol: spread_half *= 2.0
        
        fair = ema_f

        bid_price = math.floor(fair - spread_half - skew)
        ask_price = math.ceil(fair + spread_half - skew)

        # Strategic Taking
        if not high_vol:
            if consensus > 0.7 and ba and ba <= fair + 1 and rem_buy > 0:
                q = min(rem_buy, abs(depth.sell_orders.get(ba, 0)), 15)
                orders.append(Order(product, ba, int(q)))
                rem_buy -= q
            elif consensus < -0.7 and bb and bb >= fair - 1 and rem_sell > 0:
                q = min(rem_sell, depth.buy_orders.get(bb, 0), 15)
                orders.append(Order(product, bb, int(-q)))
                rem_sell -= q

        # Passive Layering
        if bb is not None: bid_price = min(bid_price, bb + 1)
        if ba is not None: ask_price = max(ask_price, ba - 1)
        if bid_price >= ask_price: ask_price = bid_price + 1

        if rem_buy > 0:
            orders.append(Order(product, int(bid_price), min(rem_buy, 20)))
        if rem_sell > 0:
            orders.append(Order(product, int(ask_price), -min(rem_sell, 20)))

        # Emergency Unwind
        if (pos > limit * 0.75 and consensus < -0.3) or (pos < -limit * 0.75 and consensus > 0.3):
            if pos > 0 and bb: orders.append(Order(product, bb, -min(pos, 20)))
            elif pos < 0 and ba: orders.append(Order(product, ba, min(abs(pos), 20)))

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
        
        tc = self.history.get("tc", 0)

        if len(hist) < 40: return []

        fair = self._ema(hist, 40)
        vol = max(1.0, float(max(hist[-20:]) - min(hist[-20:])))
        
        high_vol = vol > 15
        
        tape_val = 0.0
        if product in state.market_trades:
            for t in state.market_trades[product]:
                tape_val += t.quantity if t.price >= mid else -t.quantity
        self.history["o_tape"] = self.history.get("o_tape", 0) * 0.5 + tape_val * 0.5
        
        l1_imb = self._calculate_l1_imbalance(depth)
        ofi = self._calculate_ofi(product, depth)
        ofi_acc = self.history.get("op_o_acc", 0) * 0.4 + ofi * 0.6
        self.history["op_o_acc"] = ofi_acc
        
        norm_tape = max(-1.0, min(1.0, self.history["o_tape"] / 15.0))
        norm_ofi = max(-1.0, min(1.0, ofi_acc / 5.0))
        
        consensus = norm_tape * 0.4 + norm_ofi * 0.3 + l1_imb * 0.3
        
        limit = 60 if tc < 100 else 80
        rem_buy = limit - pos
        rem_sell = limit + pos

        orders = []
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None

        skew = self._sigmoid_skew(pos, limit) * 1.5
        spread_half = max(0.5, vol * 0.5)
        if high_vol: spread_half *= 2.0

        bid_price = math.floor(fair - spread_half - skew)
        ask_price = math.ceil(fair + spread_half - skew)

        # Strategic Taking
        if not high_vol:
            if consensus > 0.7 and ba and ba <= fair + 1 and rem_buy > 0:
                q = min(rem_buy, abs(depth.sell_orders.get(ba, 0)), 15)
                orders.append(Order(product, ba, int(q)))
                rem_buy -= q
            elif consensus < -0.7 and bb and bb >= fair - 1 and rem_sell > 0:
                q = min(rem_sell, depth.buy_orders.get(bb, 0), 15)
                orders.append(Order(product, bb, int(-q)))
                rem_sell -= q

        # Passive Layering
        if bb is not None: bid_price = min(bid_price, bb + 1)
        if ba is not None: ask_price = max(ask_price, ba - 1)
        if bid_price >= ask_price: ask_price = bid_price + 1

        if rem_buy > 0:
            orders.append(Order(product, int(bid_price), min(rem_buy, 20)))
        if rem_sell > 0:
            orders.append(Order(product, int(ask_price), -min(rem_sell, 20)))

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
