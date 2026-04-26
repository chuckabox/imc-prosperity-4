import json
import math
import sys
import importlib.util
import os
from datamodel import TradingState, OrderDepth, Order

def replay_strategy(trader_class, activities_data):
    trader = trader_class()
    state = TradingState(
        traderData="",
        timestamp=0,
        listings={},
        order_depths={},
        own_trades={},
        market_trades={},
        position={},
        observations={}
    )
    
    ts_groups = {}
    for entry in activities_data:
        ts = entry['ts']
        if ts not in ts_groups: ts_groups[ts] = []
        ts_groups[ts].append(entry)
        
    total_pnl = 0
    positions = {}
    pnl_history = []
    executed_trades = []
    
    sorted_ts = sorted(ts_groups.keys())
    
    for ts in sorted_ts:
        state.timestamp = ts
        state.position = positions.copy()
        
        for entry in ts_groups[ts]:
            symbol = entry['symbol']
            mid = entry['mid']
            depth = OrderDepth()
            depth.buy_orders = {int(mid - 1): 100}
            depth.sell_orders = {int(mid + 1): -100}
            state.order_depths[symbol] = depth
            
        orders, _, trader_data = trader.run(state)
        state.traderData = trader_data
        
        for symbol, order_list in orders.items():
            for order in order_list:
                try:
                    mid = next(e['mid'] for e in ts_groups[ts] if e['symbol'] == symbol)
                    exec_price = mid + (1 if order.quantity > 0 else -1)
                    qty = order.quantity
                    positions[symbol] = positions.get(symbol, 0) + qty
                    total_pnl -= exec_price * qty
                    executed_trades.append({
                        'ts': ts,
                        'symbol': symbol,
                        'price': exec_price,
                        'qty': qty
                    })
                except StopIteration:
                    pass
        
        current_val = 0
        for symbol, pos in positions.items():
            try:
                mid = next((e['mid'] for e in ts_groups[ts] if e['symbol'] == symbol), 0)
                current_val += pos * mid
            except: pass
            
        pnl_history.append({'ts': ts, 'pnl': total_pnl + current_val})
        
    return pnl_history, executed_trades

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python replay_tool.py script1.py script2.py ...")
        sys.exit(1)

    with open('visualizer_data.js', 'r') as f:
        content = f.read()
        json_str = content.split('const ACTIVITIES_DATA = ')[1].split(';')[0]
        activities = json.loads(json_str)
    
    comparison_results = {}

    for script_path in sys.argv[1:]:
        module_name = os.path.basename(script_path).replace('.py', '')
        print(f"Replaying {module_name}...")
        
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        pnl_history, trades = replay_strategy(module.Trader, activities)
        comparison_results[module_name] = {
            'pnl_history': pnl_history,
            'trades': trades
        }
        print(f"  Final PnL: {pnl_history[-1]['pnl']:,.0f}")

    with open('comparison_results.js', 'w') as f:
        f.write('const COMPARISON_DATA = ' + json.dumps(comparison_results) + ';\n')
    print("\nResults saved to comparison_results.js. Now refresh visualizer.html.")
