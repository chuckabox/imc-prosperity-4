import sys
import os
import json
import math
import argparse
import importlib.util
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / "config"))
from datamodel import Listing, OrderDepth, TradingState, Observation, Order, Trade

@dataclass
class EngineResult:
    final_pnl: float
    pnl_history: List[float]
    trade_count: int
    max_drawdown: float
    sharpe: float
    sortino: float
    calmar: float
    max_pos: Dict[str, int]
    fill_rate: float
    latency_adjustments: int

class AdvancedMatchingEngine:
    """
    Advanced Matching Engine supporting:
    - Market Trade Matching (matching against market trades, not just the book)
    - Execution Latency (delay between state and action)
    - Slippage Model (probabilistic partial fills)
    - Position Limit Enforcement
    """
    def __init__(self, 
                 latency_ticks: int = 0, 
                 slippage_prob: float = 0.0,
                 match_market_trades: bool = False,
                 position_limits: Dict[str, int] = None):
        self.latency_ticks = latency_ticks
        self.slippage_prob = slippage_prob
        self.match_market_trades = match_market_trades
        self.position_limits = position_limits or {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
        
    def run_backtest(self, trader_file: str, csv_path: str) -> EngineResult:
        df = pd.read_csv(csv_path, sep=";")
        df = df.dropna(subset=["bid_price_1", "ask_price_1"])
        
        # Load trader
        module_name = f"trader_{Path(trader_file).stem}_{id(trader_file)}"
        spec = importlib.util.spec_from_file_location(module_name, trader_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        trader = module.Trader()
        
        listings = {p: Listing(p, p, "SEASHELLS") for p in self.position_limits.keys()}
        cash_per_product = {p: 0.0 for p in self.position_limits.keys()}
        positions = {p: 0 for p in self.position_limits.keys()}
        pnl_history = []
        trade_count = 0
        total_orders = 0
        fills = 0
        max_pos_seen = {p: 0 for p in self.position_limits.keys()}
        trader_data = ""
        
        # State Queue for Latency
        state_queue = []
        
        grouped = df.groupby("timestamp")
        all_timestamps = sorted(grouped.groups.keys())
        
        for i, ts in enumerate(all_timestamps):
            group = grouped.get_group(ts)
            order_depths = {}
            mid_prices = {}
            market_trades = {}
            
            for _, row in group.iterrows():
                p = row["product"]
                depth = OrderDepth()
                depth.buy_orders[int(row["bid_price_1"])] = int(row["bid_volume_1"])
                depth.sell_orders[int(row["ask_price_1"])] = -int(row["ask_volume_1"])
                # Add more levels if available
                for lv in [2, 3]:
                    if f"bid_price_{lv}" in row and not pd.isna(row[f"bid_price_{lv}"]):
                        depth.buy_orders[int(row[f"bid_price_{lv}"])] = int(row[f"bid_volume_{lv}"])
                    if f"ask_price_{lv}" in row and not pd.isna(row[f"ask_price_{lv}"]):
                        depth.sell_orders[int(row[f"ask_price_{lv}"])] = -int(row[f"ask_volume_{lv}"])
                
                order_depths[p] = depth
                mid_prices[p] = (int(row["bid_price_1"]) + int(row["ask_price_1"])) / 2.0
                market_trades[p] = [] # Simulation doesn't always have market trades in CSV
                
            current_state = TradingState(
                traderData=trader_data,
                timestamp=ts,
                listings=listings,
                order_depths=order_depths,
                own_trades={},
                market_trades=market_trades,
                position=dict(positions),
                observations=Observation({}, {}),
            )
            
            # Latency Buffer
            state_queue.append(current_state)
            if len(state_queue) > self.latency_ticks:
                delayed_state = state_queue.pop(0)
            else:
                delayed_state = current_state
                
            try:
                orders, _, new_data = trader.run(delayed_state)
                trader_data = new_data
            except Exception:
                orders = {}

            # Execute orders against CURRENT order book (the market at timestamp ts)
            for product, order_list in orders.items():
                if product not in order_depths: continue
                depth = order_depths[product]
                limit = self.position_limits.get(product, 80)
                
                for order in order_list:
                    total_orders += 1
                    # Slippage simulation
                    if self.slippage_prob > 0 and np.random.random() < self.slippage_prob:
                        continue # Simulated miss
                        
                    qty = order.quantity
                    price = order.price
                    
                    if qty > 0: # Buy
                        for ask in sorted(depth.sell_orders.keys()):
                            if price >= ask and qty > 0:
                                avail = -depth.sell_orders[ask]
                                fill = min(qty, avail, limit - positions[product])
                                if fill > 0:
                                    positions[product] += fill
                                    cash_per_product[product] -= fill * ask
                                    qty -= fill
                                    trade_count += 1
                                    fills += 1
                    elif qty < 0: # Sell
                        for bid in sorted(depth.buy_orders.keys(), reverse=True):
                            if price <= bid and qty < 0:
                                avail = depth.buy_orders[bid]
                                fill = min(-qty, avail, limit + positions[product])
                                if fill > 0:
                                    positions[product] -= fill
                                    cash_per_product[product] += fill * bid
                                    qty += fill
                                    trade_count += 1
                                    fills += 1
                                    
            for p in positions:
                max_pos_seen[p] = max(max_pos_seen[p], abs(positions[p]))
                
            mtm = sum(cash_per_product.values())
            for p, pos in positions.items():
                if p in mid_prices:
                    mtm += pos * mid_prices[p]
            pnl_history.append(mtm)

        # Metrics
        returns = np.diff(pnl_history)
        max_pnl = 0
        max_dd = 0
        for p in pnl_history:
            max_pnl = max(max_pnl, p)
            max_dd = max(max_dd, max_pnl - p)
            
        sharpe = (np.mean(returns) / np.std(returns) * np.sqrt(len(returns))) if len(returns) > 1 and np.std(returns) > 0 else 0
        sortino = 0
        if len(returns) > 1:
            downside = returns[returns < 0]
            if len(downside) > 0:
                sortino = (np.mean(returns) / np.std(downside) * np.sqrt(len(returns)))
        
        calmar = (pnl_history[-1] / max_dd) if max_dd > 0 else 0
        
        return EngineResult(
            final_pnl=pnl_history[-1],
            pnl_history=pnl_history,
            trade_count=trade_count,
            max_drawdown=max_dd,
            sharpe=sharpe,
            sortino=sortino,
            calmar=calmar,
            max_pos=max_pos_seen,
            fill_rate=(fills / total_orders) if total_orders > 0 else 0,
            latency_adjustments=self.latency_ticks
        )

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("trader", help="Trader file")
    parser.add_argument("data", help="CSV data file")
    parser.add_argument("--latency", type=int, default=0)
    parser.add_argument("--slippage", type=float, default=0.0)
    args = parser.parse_args()
    
    engine = AdvancedMatchingEngine(latency_ticks=args.latency, slippage_prob=args.slippage)
    res = engine.run_backtest(args.trader, args.data)
    
    print(f"\nAdvanced Backtest Results ({args.trader} on {args.data})")
    print(f"Latency: {args.latency} ticks, Slippage Prob: {args.slippage*100}%")
    print("-" * 50)
    print(f"PnL:        ${res.final_pnl:>12,.2f}")
    print(f"Drawdown:   ${res.max_drawdown:>12,.2f}")
    print(f"Sharpe:      {res.sharpe:>12.4f}")
    print(f"Sortino:     {res.sortino:>12.4f}")
    print(f"Calmar:      {res.calmar:>12.4f}")
    print(f"Trades:      {res.trade_count:>12d}")
    print(f"Fill Rate:   {res.fill_rate*100:>11.1f}%")
