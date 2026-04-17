import pandas as pd
import numpy as np
import os
import sys
import math
from typing import Dict, List, Any

# Add local paths for module resolution
import os
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..", "config")))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..", "traders")))

from datamodel import Listing, OrderDepth, TradingState, Observation, Order

class BacktestEngine:
    def __init__(self, days=None):
        self.days = days if days else [-2, -1, 0]
        self.root_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.abspath(os.path.join(self.root_dir, "..", "data_capsule"))

    def run(self, TraderClass, name="Strategy"):
        total_pnl = 0
        all_results = []
        
        for day in self.days:
            price_file = os.path.join(self.data_dir, f"prices_round_1_day_{day}.csv")
            trade_file = os.path.join(self.data_dir, f"trades_round_1_day_{day}.csv")
            
            if not os.path.exists(price_file): 
                print(f"  [!] Missing data for day {day}")
                continue
            
            # Load Data
            df_p = pd.read_csv(price_file, sep=";")
            df_t = pd.read_csv(trade_file, sep=";") if os.path.exists(trade_file) else None
            
            # Grouping
            grouped_p = df_p.groupby("timestamp")
            trades_dict = {}
            if df_t is not None:
                for (t, s), g in df_t.groupby(["timestamp", "symbol"]):
                    trades_dict[(t, s)] = g.to_dict("records")
            
            # Init State
            trader = TraderClass()
            trader.traderData = ""
            pos = {"ASH_COATED_OSMIUM": 0, "INTARIAN_PEPPER_ROOT": 0}
            cash = 0.0
            pnl_series = []
            metrics = {"takes": 0, "makes": 0, "take_pnl": 0.0, "make_pnl": 0.0}
            
            listings = {
                "ASH_COATED_OSMIUM": Listing("ASH_COATED_OSMIUM", "ASH_COATED_OSMIUM", "SEASHELLS"),
                "INTARIAN_PEPPER_ROOT": Listing("INTARIAN_PEPPER_ROOT", "INTARIAN_PEPPER_ROOT", "SEASHELLS")
            }

            for ts, group in grouped_p:
                depths = {}
                mids = {}
                for _, row in group.iterrows():
                    sym = row["product"]
                    d = OrderDepth()
                    if not pd.isna(row["bid_price_1"]): d.buy_orders[int(row["bid_price_1"])] = int(row["bid_volume_1"])
                    if not pd.isna(row["ask_price_1"]): d.sell_orders[int(row["ask_price_1"])] = -int(row["ask_volume_1"])
                    depths[sym] = d
                    bb = max(d.buy_orders.keys()) if d.buy_orders else 0
                    ba = min(d.sell_orders.keys()) if d.sell_orders else 0
                    mids[sym] = (bb + ba) / 2.0 if bb and ba else (bb or ba or 10000)

                state = TradingState(
                    traderData=trader.traderData,
                    timestamp=ts,
                    listings=listings,
                    order_depths=depths,
                    own_trades={},
                    market_trades={},
                    position=pos,
                    observations=Observation({}, {})
                )
                
                orders, _, trader_data = trader.run(state)
                trader.traderData = trader_data
                
                # Execution
                for sym, order_list in orders.items():
                    if sym not in depths: continue
                    d = depths[sym]
                    
                    # Sort orders: Market takes first
                    ordered_orders = sorted(order_list, key=lambda x: abs(x.price - mids[sym]), reverse=True)
                    
                    for order in ordered_orders:
                        price = int(order.price)
                        qty = int(order.quantity)
                        if qty == 0: continue
                        
                        limit = trader.limits.get(sym, 20)
                        
                        # 1. Taker (Aggressive)
                        if qty > 0: # Buy
                            best_ask = min(d.sell_orders.keys()) if d.sell_orders else 999999
                            if price >= best_ask:
                                fill = min(qty, -d.sell_orders[best_ask], limit - pos[sym])
                                if fill > 0:
                                    pos[sym] += fill
                                    cash -= fill * best_ask
                                    qty -= fill
                                    metrics["takes"] += fill
                                    metrics["take_pnl"] += fill * (mids[sym] - best_ask)
                        else: # Sell
                            best_bid = max(d.buy_orders.keys()) if d.buy_orders else -999999
                            if price <= best_bid:
                                fill = min(-qty, d.buy_orders[best_bid], pos[sym] + limit)
                                if fill > 0:
                                    pos[sym] -= fill
                                    cash += fill * best_bid
                                    qty += fill
                                    metrics["takes"] += fill
                                    metrics["take_pnl"] += fill * (best_bid - mids[sym])
                        
                        # 2. Maker (Passive)
                        if qty != 0:
                            mkt_trades = trades_dict.get((ts, sym), [])
                            for trade in mkt_trades:
                                tp = trade["price"]
                                tv = trade["quantity"]
                                if qty > 0 and price >= tp: # Buy fill
                                    f = min(qty, int(tv * 0.4) + 1, limit - pos[sym])
                                    if f > 0:
                                        pos[sym] += f
                                        cash -= f * price
                                        qty -= f
                                        metrics["makes"] += f
                                        metrics["make_pnl"] += f * (mids[sym] - price)
                                elif qty < 0 and price <= tp: # Sell fill
                                    f = min(-qty, int(tv * 0.4) + 1, pos[sym] + limit)
                                    if f > 0:
                                        pos[sym] -= f
                                        cash += f * price
                                        qty += f
                                        metrics["makes"] += f
                                        metrics["make_pnl"] += f * (price - mids[sym])

                # Mark to Market
                mtm = cash
                for sym, p in pos.items():
                    mtm += p * mids[sym]
                pnl_series.append(mtm)
            
            day_pnl = pnl_series[-1]
            total_pnl += day_pnl
            all_results.append({"day": day, "pnl": day_pnl, "metrics": metrics})
            
        return {"total_pnl": total_pnl, "days": all_results, "name": name}

if __name__ == "__main__":
    engine = BacktestEngine()
    import importlib.util
    
    trader_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "traders", "peter"))
    results = []
    
    print(f"[SEARCH] Auditing Peter Portfolio in: {trader_dir}")
    
    trader_files = [f for f in os.listdir(trader_dir) if f.startswith("trader_peter_") and f.endswith(".py")]
    
    for f in sorted(trader_files):
        path = os.path.join(trader_dir, f)
        spec = importlib.util.spec_from_file_location("trader_module", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        print(f"[RUNNING] {f}...")
        results.append(engine.run(module.Trader, f))
    
    print("\n" + "="*60)
    print(f"{'STRATEGY':<30} | {'TOTAL PNL':<15} | {'MAKES':<10}")
    print("-" * 60)
    
    # Sort by total PnL
    results.sort(key=lambda x: x['total_pnl'], reverse=True)
    
    for r in results:
        total_makes = sum(d['metrics']['makes'] for d in r['days'])
        print(f"{r['name']:<30} | ${r['total_pnl']:>12,.2f} | {total_makes:>10}")
    
    print("="*60)
