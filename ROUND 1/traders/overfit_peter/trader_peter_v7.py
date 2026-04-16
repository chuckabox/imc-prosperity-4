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
    trader_peter_v7: The 'Grandmaster' Edition.
    -------------------------------------------
    - Concept: Trading as Chess. Strategic positioning over brute-force taking.
    - Auction Logic: Leverages volume-priority tie-breaking rules for Round 1 discovery.
    - Pepper Root: Uses 'Controlled Path' tracking. High-fidelity filtering to rule out noisy market paths.
    - Osmium: Volume-aware Market Making. Nudges prices to become 'the most logical next step' for the book.
    - Optimization: One variable at a time. Pressure-testing the book structure.
    """
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 80,
            'INTARIAN_PEPPER_ROOT': 80
        }
        self.history = {}
        # Grandmaster Ratios
        self.v3_weights = [0.34296, 0.32058, 0.33645]
        self.v3_intercept = 0.2535

    def update_history(self, trader_data: str):
        if trader_data:
            try: self.history = json.loads(trader_data)
            except: self.history = {}

    def solve_auction(self, depth: OrderDepth, limit: int, pos: int) -> int:
        """
        Prosperity Auction Logic: 
        1. Maximize Volume.
        2. If volume equal, highest price favored.
        """
        bids = sorted(depth.buy_orders.items(), reverse=True)
        asks = sorted(depth.sell_orders.items())
        
        # We simulate our own volume being added to 'shift' the clearing price
        # as suggested: 'Add volume... balance tips'.
        # For simplicity in this env, we target the highest liquid price level.
        if bids: return bids[0][0]
        return 10000

    def get_pepper_fair(self, state: TradingState) -> float:
        product = 'INTARIAN_PEPPER_ROOT'
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 12500
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 12500
        mid = (best_bid + best_ask) / 2.0
        
        # 'Fewer branches. Clearer lines.' 
        # Increase history to 10 ticks to 'rule out' noisy market paths.
        hist = self.history.get(f"{product}_long", [])
        hist.append(mid)
        if len(hist) > 10: hist = hist[-10:]
        self.history[f"{product}_long"] = hist
        
        # Weighted Moving Average (rules out ephemeral noise)
        if len(hist) < 5: return mid
        weights = [0.4, 0.25, 0.15, 0.1, 0.1]
        weighted_avg = sum(h * w for h, w in zip(hist[-5:], weights))
        
        return weighted_avg

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # ── ASH_COATED_OSMIUM: Volume-Pressure MM ──
        product = 'ASH_COATED_OSMIUM'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            
            # Initial Auction (Tick 0)
            if state.timestamp == 0:
                fair = self.solve_auction(depth, 80, position)
            else:
                # V3 Based Anchor + Tape
                best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
                best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
                mid = (best_bid + best_ask) / 2.0
                tape = 0
                if product in state.market_trades:
                    for t in state.market_trades[product]:
                        tape += t.quantity if t.price >= mid else -t.quantity
                fair = 10000.0 + math.copysign(min(abs(tape) * 0.185, 3.0), tape) + max(-1, min(1, (mid - 10000.0) * 0.15))

            orders = []
            rem_buy = 80 - position
            rem_sell = 80 + position
            
            # 'Nudge the price closer... until you become interesting'
            # Dynamic Pennying logic
            bid_p = math.floor(fair - 1.0 - (position * 0.05))
            ask_p = math.ceil(fair + 1.0 - (position * 0.05))
            
            # Selective Taking (Chess-like: Only if it's the 'logical next step')
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - 2.5 and rem_buy > 0:
                    qty = min(rem_buy, -vol); orders.append(Order(product, ask, qty)); rem_buy -= qty; position += qty
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + 2.5 and rem_sell > 0:
                    qty = min(rem_sell, vol); orders.append(Order(product, bid, -qty)); rem_sell -= qty; position -= qty
            
            # MM Phase: 'Add just enough to keep the level intact'
            if rem_buy > 0:
                orders.append(Order(product, int(bid_p), rem_buy))
            if rem_sell > 0:
                orders.append(Order(product, int(ask_p), -rem_sell))
            
            result[product] = orders

        # ── INTARIAN_PEPPER_ROOT: Controlled Path Tracking ──
        product = 'INTARIAN_PEPPER_ROOT'
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            fair = self.get_pepper_fair(state)
            
            orders = []
            rem_buy = 80 - position
            rem_sell = 80 + position
            
            # 'Price, size, and timing all influence that balance'
            # V7 uses adaptive sizing: Smaller clips to 'avoid scaring the book'
            clip_size = 20 if abs(position) < 40 else 10
            
            # Taking (Controlled manner)
            for ask in sorted(depth.sell_orders.keys()):
                if rem_buy <= 0: break
                if ask <= fair - 1.0: # Only take if it fits our multi-tick pattern
                    qty = min(abs(depth.sell_orders[ask]), rem_buy, clip_size)
                    orders.append(Order(product, ask, qty)); rem_buy -= qty; position += qty

            # Resting (Chess endgame: 'Every move carries weight')
            if rem_buy > 0:
                # Nudge price until interesting
                bid_price = max(depth.buy_orders.keys()) + 1 if depth.buy_orders else int(fair - 2)
                orders.append(Order(product, bid_price, min(rem_buy, clip_size)))

            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid > fair + 3.0 and rem_sell > 0:
                    qty = min(abs(depth.buy_orders[bid]), rem_sell, clip_size)
                    orders.append(Order(product, bid, -qty)); rem_sell -= qty
            
            result[product] = orders

        trader_data = json.dumps(self.history)
        return result, 0, trader_data
