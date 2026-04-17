import sys, json, importlib.util, pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path('ROUND 1/config')))
from datamodel import Listing, OrderDepth, TradingState, Observation, Order

spec = importlib.util.spec_from_file_location('t', 'ROUND 1/traders/ken/trader_robust_ken_v6c.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
trader = m.Trader()

df = pd.read_csv('ROUND 1/data_capsule/prices_round_1_day_-2.csv', sep=';').dropna(subset=['bid_price_1','ask_price_1'])
grouped = df.groupby('timestamp')

positions = {'ASH_COATED_OSMIUM': 0, 'INTARIAN_PEPPER_ROOT': 0}
trader_data = ''
checkpoints = {0, 1000, 1900, 2000, 2100, 3000, 5000, 50000, 500000, 900000}
for i, (ts, g) in enumerate(grouped):
    od = {}
    for _, r in g.iterrows():
        d = OrderDepth()
        d.buy_orders[int(r.bid_price_1)] = int(r.bid_volume_1)
        d.sell_orders[int(r.ask_price_1)] = -int(r.ask_volume_1)
        od[r['product']] = d
    state = TradingState(trader_data, ts, {}, od, {}, {}, dict(positions), Observation({},{}))
    orders, _, trader_data = trader.run(state)
    h = json.loads(trader_data)
    # simulate simple fill
    for prod, ords in orders.items():
        for o in ords:
            if o.quantity > 0:
                asks = sorted(od[prod].sell_orders.keys())
                for a in asks:
                    if o.price >= a:
                        avail = -od[prod].sell_orders[a]
                        fill = min(o.quantity, avail, 80 - positions[prod])
                        positions[prod] += fill
                        o.quantity -= fill
                        if o.quantity <= 0: break
            elif o.quantity < 0:
                bids = sorted(od[prod].buy_orders.keys(), reverse=True)
                for b in bids:
                    if o.price <= b:
                        avail = od[prod].buy_orders[b]
                        fill = min(-o.quantity, avail, 80 + positions[prod])
                        positions[prod] -= fill
                        o.quantity += fill
                        if o.quantity >= 0: break
    if ts in checkpoints:
        pp = positions['INTARIAN_PEPPER_ROOT']
        print(f'ts={ts:>7} pos_pp={pp:>3} cap={h.get("pp_cap")} slope={h.get("pp_measured_slope")} start_mid={h.get("pp_start_mid")} stopped={h.get("pp_stopped")}')
