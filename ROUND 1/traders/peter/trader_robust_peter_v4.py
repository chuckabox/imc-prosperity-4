
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

        # ── PEPPER ROOT: Multi-Layer Liquidity Provider ──────────────
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            depth = state.order_depths[product]
            pos = state.position.get(product, 0)
            limit = self.limits[product]
            orders = []

            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None

            if best_bid and best_ask:
                mid = (best_bid + best_ask) / 2.0
                bid_vol = sum(depth.buy_orders.values())
                ask_vol = abs(sum(depth.sell_orders.values()))
                imb = (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 0
                
                # Fair Value with aggressive inventory return (0.06)
                fair = mid - (pos * 0.06) + (imb * 0.15)

                rem_buy = limit - pos
                rem_sell = limit + pos

                # Dynamic Sniping
                for ask, vol in sorted(depth.sell_orders.items()):
                    if ask <= fair + 0.2 and rem_buy > 0:
                        qty = min(rem_buy, -vol)
                        orders.append(Order(product, ask, qty))
                        rem_buy -= qty
                
                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if bid >= fair - 0.2 and rem_sell > 0:
                        qty = min(rem_sell, vol)
                        orders.append(Order(product, bid, -qty))
                        rem_sell -= qty

                # Multi-Layer Passive Quotes (20 per level to capture spikes)
                bid_p = int(min(best_bid + 1, math.floor(fair)))
                ask_p = int(max(best_ask - 1, math.ceil(fair)))
                if bid_p >= ask_p: bid_p, ask_p = int(mid-1), int(mid+1)

                layer_size = 20
                for i in range(4):
                    if rem_buy > 0:
                        q = min(rem_buy, layer_size)
                        orders.append(Order(product, bid_p - i, q))
                        rem_buy -= q
                    if rem_sell > 0:
                        q = min(rem_sell, layer_size)
                        orders.append(Order(product, ask_p + i, -q))
                        rem_sell -= q

            result[product] = orders

        # ── OSMIUM: Multi-Layer Magnet MM ────────────────────────────
        product = 'ASH_COATED_OSMIUM'
        if product in state.order_depths:
            depth = state.order_depths[product]
            pos = state.position.get(product, 0)
            limit = self.limits[product]
            orders = []

            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
            mid = (best_bid + best_ask) / 2.0

            tape_vol = 0
            if product in state.market_trades:
                for t in state.market_trades[product]:
                    if t.price >= 10000: tape_vol += t.quantity
                    else: tape_vol -= t.quantity
            tape_adj = math.copysign(min(abs(tape_vol) * 0.25, 4.0), tape_vol)

            bid_v, ask_v = sum(depth.buy_orders.values()), abs(sum(depth.sell_orders.values()))
            pressure = (bid_v - ask_v) / (bid_v + ask_v) if (bid_v + ask_v) > 0 else 0
            dist_pull = (10000 - mid) * 0.08
            
            fair = 10000.0 + tape_adj + (pressure * 2.5) + dist_pull

            rem_buy, rem_sell = limit - pos, limit + pos

            # Snipe
            take_m = 1.5
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - take_m and rem_buy > 0:
                    qty = min(rem_buy, -vol, 30)
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty
                    pos += qty
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + take_m and rem_sell > 0:
                    qty = min(rem_sell, vol, 30)
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty
                    pos -= qty

            # Multi-Layer Passive Quotes
            skew = pos * 0.06
            bid_p = int(min(best_bid + 1, math.floor(fair - 0.5 - skew)))
            ask_p = int(max(best_ask - 1, math.ceil(fair + 0.5 - skew)))
            if bid_p >= ask_p: bid_p, ask_p = int(fair-1), int(fair+1)

            for i in range(4):
                if rem_buy > 0:
                    q = min(rem_buy, 20)
                    orders.append(Order(product, bid_p - i, q))
                    rem_buy -= q
                if rem_sell > 0:
                    q = min(rem_sell, 20)
                    orders.append(Order(product, ask_p + i, -q))
                    rem_sell -= q
            
            result[product] = orders

        return result, 0, json.dumps(self.history)
