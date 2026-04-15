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
    Antigravity Round 1 Defender Strategy (trader_peter7)
    ----------------------------------------------------
    - Goal: 10,000 PnL by combining Aggressive Taking with Active Defense.
    - Risk Management: "Active Exit" (Market Take Stop Loss) + OFI Kill-Switch.
    - Signal: 3-Lag Linear Regression.
    """
    
    def __init__(self):
        self.limits = {'ASH_COATED_OSMIUM': 20, 'INTARIAN_PEPPER_ROOT': 20}
        self.sf_weights = [0.34296, 0.32058, 0.33645]
        self.sf_intercept = 0.2535
        self.history = {}
        self.last_fairs = {}
        self.traderData = ""

    def update_history(self, trader_data: str):
        if trader_data:
            try: self.history = json.loads(trader_data)
            except: self.history = {}

    def get_fair_price(self, product: str, state: TradingState) -> float:
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
        mid = (best_bid + best_ask) / 2.0
        
        if product == 'ASH_COATED_OSMIUM': return 10000.0
            
        if product == 'INTARIAN_PEPPER_ROOT':
            p_hist = self.history.get(product, [])
            if not isinstance(p_hist, list): p_hist = []
            p_hist.append(mid)
            if len(p_hist) > 3: p_hist = p_hist[-3:]
            self.history[product] = p_hist
            if len(p_hist) < 3: return mid
            
            # 3-lag Predict
            pred = self.sf_intercept
            for i in range(3):
                pred += self.sf_weights[i] * p_hist[-(i+1)]
            return pred
        return mid

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}
        
        for product in ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT']:
            if product not in state.order_depths: continue
            
            depth = state.order_depths[product]
            orders: List[Order] = []
            pos = state.position.get(product, 0)
            lim = self.limits[product]
            
            fair = self.get_fair_price(product, state)
            
            # --- 1. ACTIVE EXIT (STOP LOSS) ---
            # If fair has dropped significantly and we are long, market take best bid to exit
            last_fair = self.last_fairs.get(product, fair)
            self.last_fairs[product] = fair
            
            # If price is moving hard against big position, exit 25% of position immediately
            if pos > 12 and fair < last_fair - 1.5:
                # Market Take Sell to exit
                best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else -1
                if best_bid != -1:
                    qty = min(pos, 5) # Cut 5 units
                    orders.append(Order(product, best_bid, -qty))
                    pos -= qty
            
            if pos < -12 and fair > last_fair + 1.5:
                # Market Take Buy to exit
                best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 999999
                if best_ask != 999999:
                    qty = min(-pos, 5)
                    orders.append(Order(product, best_ask, qty))
                    pos += qty

            # --- 2. THE SNIPER (1.2 Threshold) ---
            rem_buy = lim - pos
            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - 1.2 and rem_buy > 0:
                    q = min(rem_buy, -vol)
                    orders.append(Order(product, int(ask), q))
                    rem_buy -= q
                    pos += q
            
            rem_sell = lim + pos
            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + 1.2 and rem_sell > 0:
                    q = min(rem_sell, vol)
                    orders.append(Order(product, int(bid), -q))
                    rem_sell -= q
                    pos -= q

            # --- 3. LIQUIDITY GUARD (OFI KILL-SWITCH) ---
            bid_vol = sum(depth.buy_orders.values())
            ask_vol = -sum(depth.sell_orders.values())
            imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 0
            
            # --- 4. MAKER QUOTING ---
            skew = 0.3
            final_bid = math.floor(fair - 1 - pos * skew)
            final_ask = math.ceil(fair + 1 - pos * skew)
            
            # Tight Spread Catch: If spread > 5, squeeze it
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else fair - 5
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else fair + 5
            
            # OFI Defense: Don't buy if market is crashing (ask_vol >> bid_vol)
            if imbalance < -0.85: final_bid -= 2 # Push bid deep
            if imbalance > 0.85: final_ask += 2 # Push ask deep
            
            # Combined Pennier
            final_bid = min(best_bid + 1, final_bid)
            final_ask = max(best_ask - 1, final_ask)
            
            # Final Cross Check
            final_bid = min(final_bid, math.floor(fair - 0.5))
            final_ask = max(final_ask, math.ceil(fair + 0.5))
            
            if (lim - pos) > 0:
                orders.append(Order(product, int(final_bid), lim - pos))
            if (lim + pos) > 0:
                orders.append(Order(product, int(final_ask), -(lim + pos)))
                
            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
