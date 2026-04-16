import sys
import os
import pandas as pd
import json
import math

# Use the backtest logic to test locally inside the script
from tools.backtest_cli import run_cli_backtest

code = """
import json
import math
import collections
from typing import Dict, List, Any
from datamodel import Order, OrderDepth, TradingState, Symbol

class Trader:
    def __init__(self):
        self.limits = {'ASH_COATED_OSMIUM': 80, 'INTARIAN_PEPPER_ROOT': 80}
        self.emas = {}

    def run(self, state: TradingState):
        if state.traderData:
            try:
                self.emas = json.loads(state.traderData)
            except:
                pass
                
        result = {}
        for product in self.limits.keys():
            if product not in state.order_depths: continue
            
            depth = state.order_depths[product]
            pos = state.position.get(product, 0)
            lim = self.limits[product]
            
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 0
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 0
            if not best_bid or not best_ask: continue
            
            mid = (best_bid + best_ask) / 2.0
            
            if product not in self.emas:
                self.emas[product] = {'fast': mid, 'slow': mid}
                
            fast_ema = self.emas[product]['fast'] * 0.8 + mid * 0.2
            slow_ema = self.emas[product]['slow'] * 0.95 + mid * 0.05
            self.emas[product]['fast'] = fast_ema
            self.emas[product]['slow'] = slow_ema
            
            # Target position based on TA trend
            if fast_ema > slow_ema + 0.5:
                target = lim
            elif fast_ema < slow_ema - 0.5:
                target = -lim
            else:
                target = 0
            
            v_b = depth.buy_orders[best_bid]
            v_a = abs(depth.sell_orders[best_ask])
            imb = (v_b - v_a) / (v_b + v_a)
            
            fair = fast_ema + imb * 1.5
            skew = (pos - target) * 0.05
            
            spread = 1.5
            buy_price = math.floor(fair - spread - skew)
            sell_price = math.ceil(fair + spread - skew)
            
            orders = []
            block = 20
            
            buy_rem = lim - pos
            if buy_rem > 0:
                for i in range(4):
                    if buy_rem <= 0: break
                    p = int(buy_price - i)
                    q = min(buy_rem, block)
                    orders.append(Order(product, p, q))
                    buy_rem -= q
                    
            sell_rem = lim + pos
            if sell_rem > 0:
                for i in range(4):
                    if sell_rem <= 0: break
                    p = int(sell_price + i)
                    q = min(sell_rem, block)
                    orders.append(Order(product, p, -q))
                    sell_rem -= q
                    
            result[product] = orders
            
        return result, 0, json.dumps(self.emas)
"""

with open("ROUND 1/traders/trader_robust.py", "w") as f:
    f.write(code.strip())

# Test on Train Validation split (day -2 and -1)
print("TRAINING VALIDATION SET (-2, -1):")
os.environ["PYTHONPATH"] = "ROUND 1/config"
import subprocess
try:
    cmd = f"{sys.executable} \"ROUND 1/tools/backtest_cli.py\" \"ROUND 1/traders/trader_robust.py\""
    out = subprocess.check_output(cmd, shell=True, env=os.environ).decode()
    print([line for line in out.split('\\n') if 'Final PnL' in line or 'Total PnL' in line])
except Exception as e:
    print("Error:", e)
