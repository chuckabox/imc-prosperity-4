
import json
import math
import sys
from typing import Dict, List, Any
from datamodel import Order, OrderDepth, TradingState, Symbol

class Trader:
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 80,
            'INTARIAN_PEPPER_ROOT': 80,
        }
        self.history = {}

    def _load_state(self, state: TradingState):
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}

    def run(self, state: TradingState):
        self._load_state(state)
        result = {}

        # ── PEPPER ROOT: High-conviction accumulation ────────────────
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            orders = []
            
            # Greedy take up to position 40 (safe cap)
            MAX_POS = 40
            buy_cap = MAX_POS - position
            
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
            if best_ask and buy_cap > 0:
                for ask in sorted(depth.sell_orders.keys()):
                    if buy_cap <= 0: break
                    qty = min(abs(depth.sell_orders[ask]), buy_cap)
                    orders.append(Order(product, ask, qty))
                    buy_cap -= qty
            
            # Resting bid to catch flow
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
            if best_bid and buy_cap > 0:
                orders.append(Order(product, best_bid + 1, buy_cap))
            
            result[product] = orders

        # ── OSMIUM: Tape-Aware MM ────────────────────────────────────
        product = 'ASH_COATED_OSMIUM'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            orders = []

            # Fair value anchored at 10k + tape tilt
            tape_vol = 0
            if product in state.market_trades:
                for t in state.market_trades[product]:
                    if t.price >= 10000: tape_vol += t.quantity
                    else: tape_vol -= t.quantity
            tape_adj = math.copysign(min(abs(tape_vol) * 0.15, 2.5), tape_vol)
            fair = 10000.0 + tape_adj

            rem_buy = limit - position
            rem_sell = limit + position

            # Sniper: take mispriced
            take_margin = 2.5
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - take_margin and rem_buy > 0:
                    qty = min(rem_buy, -vol)
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty
                    position += qty
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + take_margin and rem_sell > 0:
                    qty = min(rem_sell, vol)
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty
                    position -= qty

            # MM quoting
            skew = position * 0.05
            bid_price = math.floor(fair - 0.5 - skew)
            ask_price = math.ceil(fair + 0.5 - skew)
            
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
            
            final_bid = min(best_bid + 1, bid_price)
            final_ask = max(best_ask - 1, ask_price)
            
            # Floor/Ceil at fair
            if rem_buy > 0:
                orders.append(Order(product, int(min(final_bid, math.floor(fair-0.5))), rem_buy))
            if rem_sell > 0:
                orders.append(Order(product, int(max(final_ask, math.ceil(fair+0.5))), -rem_sell))
            
            result[product] = orders

        return result, 0, json.dumps(self.history)
