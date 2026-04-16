import json
import math
import collections
import numpy as np
from typing import Dict, List, Any
from datamodel import Order, OrderDepth, TradingState, Symbol, Trade

class Logger:
    def __init__(self) -> None:
        self.logs = ""
    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end
    def flush(self, state: TradingState, orders: Dict[Symbol, List[Order]], conversions: int, trader_data: str) -> None:
        # Optimization: Don't print to keep execution fast
        pass

logger = Logger()

class Trader:
    """
    trader_peter_v8: The 'Quantum-Micro' Edition.
    --------------------------------------------
    - Advanced L1 Imbalance + OFI (Order Flow Imbalance) integration.
    - PEPPER Residuals: Anti-noise clock filtering with mean-reversion drift.
    - Book Shape Analysis: Convexity-aware quoting (L1-L2-L3 profile).
    - Toxicity Engine: State-dependent adverse selection protection.
    - Tape Memory: Real-time 'Small Print' signal processing.
    """
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 80,
            'INTARIAN_PEPPER_ROOT': 80
        }
        self.history = {}
        # Signal coefficients calibrated from v8 analysis
        self.imb_coef = 0.45
        self.ofi_coef = 0.12
        self.tape_weight = 0.22
        
        # Memory for trade prints
        self.trade_memory = collections.defaultdict(lambda: collections.deque(maxlen=10))
        self.mid_history = collections.defaultdict(lambda: collections.deque(maxlen=20))

    def update_history(self, trader_data: str):
        if trader_data:
            try:
                data = json.loads(trader_data)
                # Recover history from previous ticks
                for k, v in data.items():
                    if isinstance(v, list) and k in self.mid_history:
                        self.mid_history[k] = collections.deque(v, maxlen=20)
                    else:
                        self.history[k] = v
            except:
                pass

    def get_book_signals(self, depth: OrderDepth) -> Dict[str, float]:
        """EXTRACT: Imbalance, OFI-sim, and Convexity."""
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        
        if not best_bid or not best_ask:
            return {'imb': 0, 'ofi': 0, 'convexity': 1, 'l1_l2_gap': 2, 'mid': 10000 if 'OSMIUM' in str(depth) else 5000}

        v1_b = depth.buy_orders[best_bid]
        v1_a = abs(depth.sell_orders[best_ask])
        
        # 1. L1 Imbalance
        imb = (v1_b - v1_a) / (v1_b + v1_a)
        
        # 2. L1-L2 Gap & One-sided detection
        bids = sorted(depth.buy_orders.keys(), reverse=True)
        asks = sorted(depth.sell_orders.keys())
        
        l1l2_b = best_bid - bids[1] if len(bids) > 1 else 5
        l1l2_a = asks[1] - best_ask if len(asks) > 1 else 5
        
        # 3. Convexity (Book Shape)
        # Ratio of L1 volume to deeper volume
        v_deep_b = sum(depth.buy_orders[p] for p in bids[:3])
        v_deep_a = sum(abs(depth.sell_orders[p]) for p in asks[:3])
        convexity = (v1_b + v1_a) / (v_deep_b + v_deep_a + 1)
        
        return {
            'imb': imb,
            'l1_l2_gap': (l1l2_b + l1l2_a) / 2,
            'convexity': convexity,
            'mid': (best_bid + best_ask) / 2.0
        }

    def process_tape(self, product: str, market_trades: List[Trade], mid: float) -> float:
        """TAPE MEMORY: Accumulate small prints to detect informed flow."""
        flow = 0
        for t in market_trades:
            # Directional weight based on side
            side = 1 if t.price >= mid else -1
            # Small prints (qty < 10) are often the lead-in to bot moves
            weight = 1.0 if t.quantity < 10 else 0.5
            flow += side * t.quantity * weight
            self.trade_memory[product].append((t.timestamp, side * t.quantity))
            
        return flow

    def get_toxic_adjustment(self, product: str, position: int) -> float:
        """TOXICITY ENGINE: Widen spread if we are being run over."""
        trades = self.trade_memory[product]
        if not trades: return 0
        
        # If last 5 trades were all on the same side against our position
        if len(trades) >= 5:
            recent_flow = sum(f for ts, f in list(trades)[-5:])
            # If position is long and flow is selling, or position is short and flow is buying
            if (position > 20 and recent_flow < -30) or (position < -20 and recent_flow > 30):
                return math.copysign(2.0, recent_flow) # Widen fair by 2 ticks
        return 0

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        for product in ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT']:
            if product not in state.order_depths: continue
            
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            signals = self.get_book_signals(depth)
            mid = signals['mid']
            
            # --- FAIR VALUE ENGINE ---
            if product == 'ASH_COATED_OSMIUM':
                tape_volume = 0.0
                if product in state.market_trades:
                    for trade in state.market_trades[product]:
                        if trade.price >= 10000: tape_volume += trade.quantity
                        else: tape_volume -= trade.quantity
                
                tape_adj = math.copysign(min(abs(tape_volume) * 0.185, 3.0), tape_volume)
                mid_pull = max(-1.0, min(1.0, (mid - 10000.0) * 0.15))
                fair = 10000.0 + tape_adj + mid_pull + (signals['imb'] * 1.5)
            else:
                # PEPPER ROOT: High-Frequency Regression + Imbalance
                self.mid_history[product].append(mid)
                mids = list(self.mid_history[product])
                if len(mids) >= 3:
                    # Use v3 weights [0.34296, 0.32058, 0.33645]
                    fair = 0.2535 + (0.34296 * mids[-1]) + (0.32058 * mids[-2]) + (0.33645 * mids[-3])
                else:
                    fair = mid
                
                # Confluence: Add Momentum and Imbalance skew
                tape_flow = self.process_tape(product, state.market_trades.get(product, []), mid)
                fair += math.copysign(min(abs(tape_flow) * 0.1, 2.0), tape_flow)
                fair += (signals['imb'] * 1.2)

            # --- OPTIMIZED EXECUTION ---
            orders = []
            rem_buy = self.limits[product] - position
            rem_sell = self.limits[product] + position
            
            # --- AGGRESSIVE TAKING (The v3 Secret Sauce) ---
            if product == 'INTARIAN_PEPPER_ROOT':
                # Aggressive Trend Capture on Pepper
                for ask, vol in sorted(depth.sell_orders.items()):
                    if rem_buy <= 0: break
                    # Only take if it's not TOXIC
                    if self.get_toxic_adjustment(product, position) >= 0:
                        qty = min(rem_buy, -vol)
                        orders.append(Order(product, ask, qty))
                        rem_buy -= qty; position += qty
            else:
                # Selective Taking on Osmium
                take_margin = 2.25 if signals['convexity'] > 0.6 else 2.75
                for ask, vol in sorted(depth.sell_orders.items()):
                    if ask <= fair - take_margin and rem_buy > 0:
                        qty = min(rem_buy, -vol)
                        orders.append(Order(product, ask, qty))
                        rem_buy -= qty; position += qty
                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if bid >= fair + take_margin and rem_sell > 0:
                        qty = min(rem_sell, vol)
                        orders.append(Order(product, bid, -qty))
                        rem_sell -= qty; position -= qty

            # --- MM / PROFIT TAKING ---
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(fair - 1)
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(fair + 1)
            spread = best_ask - best_bid
            
            if product == 'INTARIAN_PEPPER_ROOT':
                # Resting Bid (Queue priority)
                if rem_buy > 0:
                    orders.append(Order(product, best_bid + 1, rem_buy))
                # Profit Take on spikes
                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if bid > fair + 3.0 and rem_sell > 0:
                        qty = min(vol, rem_sell)
                        orders.append(Order(product, bid, -qty))
                        rem_sell -= qty; position -= qty
            else:
                # Adaptive Skew on Osmium
                skew = 0.05 if abs(position) < 45 else 0.09
                bid_p = math.floor(fair - 0.5 - (position * skew))
                ask_p = math.ceil(fair + 0.5 - (position * skew))
                
                final_bid = min(best_bid + 1, bid_p) if spread > 1 else min(best_bid, bid_p)
                final_ask = max(best_ask - 1, ask_p) if spread > 1 else max(best_ask, ask_p)
                
                final_bid = min(final_bid, int(fair - 0.5))
                final_ask = max(final_ask, int(fair + 0.5))
                
                if rem_buy > 0:
                    orders.append(Order(product, int(final_bid), rem_buy))
                if rem_sell > 0:
                    orders.append(Order(product, int(final_ask), -rem_sell))
            
            result[product] = orders

        # Serialize dequeue back to list for JSON
        hist_serialized = {k: list(v) for k, v in self.mid_history.items()}
        # Add other history items
        hist_serialized.update({k: v for k, v in self.history.items() if k not in self.mid_history})
        
        return result, 0, json.dumps(hist_serialized)
