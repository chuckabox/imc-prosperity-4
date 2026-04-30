"""Scan all 50 products for medium-volatility sweet spot.

Goal: find products less volatile than PEBBLES_XL / MICROCHIP_OVAL (Tier 3)
but with more reversion alpha than Tier 1 stable names (ROBOT/TRANSLATOR/PANEL).

Per product, compute over 3 days of data:
  mid_std       : std of mid price (level vol)
  abs_dmid_mean : avg absolute tick-to-tick mid change (realized vol)
  abs_dmid_p95  : 95th percentile shock size
  shock_count_8 : # ticks with |dmid| >= 8 (potential fade entries)
  shock_count_14: # ticks with |dmid| >= 14 (Math1061 trigger)
  spread_med    : median bid-ask spread
  ac1           : 1-lag autocorrelation of mid changes (negative = reversion)
  edge_per_tick : abs_dmid_mean - spread_med * 0.5 (rough net edge)
"""

import csv
import os
from collections import defaultdict
from statistics import median, mean, pstdev

DATA_DIR = "/Users/siddhant/Desktop/prosperity/imc-prosperity-4/ROUND 5/data_capsule"
FILES = [f"prices_round_5_day_{d}.csv" for d in (2, 3, 4)]

# product -> list of (timestamp, mid, spread)
series = defaultdict(list)

for fname in FILES:
    path = os.path.join(DATA_DIR, fname)
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=";")
        header = next(reader)
        idx = {h: i for i, h in enumerate(header)}
        for row in reader:
            try:
                prod = row[idx["product"]]
                bid1 = row[idx["bid_price_1"]]
                ask1 = row[idx["ask_price_1"]]
                mid = row[idx["mid_price"]]
                ts = int(row[idx["timestamp"]])
                day = int(row[idx["day"]])
                if not bid1 or not ask1 or not mid:
                    continue
                bid1 = float(bid1)
                ask1 = float(ask1)
                mid = float(mid)
                spread = ask1 - bid1
                # use (day, ts) for unique key, store as tuple
                series[prod].append((day, ts, mid, spread))
            except Exception:
                continue

print(f"Loaded {len(series)} products")
print()

results = []
for prod, rows in series.items():
    rows.sort(key=lambda r: (r[0], r[1]))
    mids = [r[2] for r in rows]
    spreads = [r[3] for r in rows]

    # tick-to-tick changes (within same day only to avoid jump at day rollover)
    dmids = []
    for i in range(1, len(rows)):
        if rows[i][0] == rows[i - 1][0]:
            dmids.append(rows[i][2] - rows[i - 1][2])
    if not dmids:
        continue

    abs_dmids = [abs(d) for d in dmids]
    abs_dmid_mean = mean(abs_dmids)
    abs_dmids_sorted = sorted(abs_dmids)
    p95 = abs_dmids_sorted[int(len(abs_dmids_sorted) * 0.95)]
    shock_8 = sum(1 for x in abs_dmids if x >= 8)
    shock_14 = sum(1 for x in abs_dmids if x >= 14)

    spread_med = median(spreads)
    mid_std = pstdev(mids)

    # 1-lag autocorrelation of dmid (negative => reversion)
    n = len(dmids)
    if n > 2:
        m_d = mean(dmids)
        var = sum((d - m_d) ** 2 for d in dmids) / n
        cov = sum((dmids[i] - m_d) * (dmids[i - 1] - m_d) for i in range(1, n)) / n
        ac1 = cov / var if var > 0 else 0.0
    else:
        ac1 = 0.0

    edge_per_tick = abs_dmid_mean - spread_med * 0.5

    results.append({
        "prod": prod,
        "mid_std": round(mid_std, 1),
        "abs_dmid_mean": round(abs_dmid_mean, 2),
        "abs_dmid_p95": round(p95, 1),
        "shock_8": shock_8,
        "shock_14": shock_14,
        "spread_med": round(spread_med, 1),
        "ac1": round(ac1, 3),
        "edge": round(edge_per_tick, 2),
    })

# Sort by edge_per_tick desc - want products where moves > spread
results.sort(key=lambda r: r["edge"], reverse=True)

cols = ["prod", "mid_std", "abs_dmid_mean", "abs_dmid_p95", "shock_8", "shock_14", "spread_med", "ac1", "edge"]
header = " | ".join(c.ljust(28 if c == "prod" else 12) for c in cols)
print(header)
print("-" * len(header))
for r in results:
    print(" | ".join(str(r[c]).ljust(28 if c == "prod" else 12) for c in cols))
