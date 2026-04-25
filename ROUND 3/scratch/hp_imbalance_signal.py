"""HYDROGEL imbalance signal — characterize fully.

Questions:
1. Does the +4 XIRECs move REVERT (mean-reversion) or PERSIST (trend)?
2. How does the signal decay over horizons (1, 5, 20, 50 ticks)?
3. Is it caused by mid recomputing because the bid/ask volumes change,
   or is it predictive of *trade-driven* moves?
4. What's the realistic capture if we cross the spread to take?
"""
from __future__ import annotations
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parents[1] / "data_capsule"
FILES = [ROOT / f"prices_round_3_day_{d}.csv" for d in (0, 1, 2)]
HP = "HYDROGEL_PACK"

def load_hp():
    rows = []
    for f in FILES:
        with f.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            for r in reader:
                if r["product"] != HP:
                    continue
                day = int(r["day"])
                ts = int(r["timestamp"])
                bb1 = float(r["bid_price_1"]) if r["bid_price_1"] else None
                ba1 = float(r["ask_price_1"]) if r["ask_price_1"] else None
                bv1 = float(r["bid_volume_1"]) if r["bid_volume_1"] else 0
                av1 = float(r["ask_volume_1"]) if r["ask_volume_1"] else 0
                # Levels 2/3
                bb2 = float(r["bid_price_2"]) if r["bid_price_2"] else None
                ba2 = float(r["ask_price_2"]) if r["ask_price_2"] else None
                bv2 = float(r["bid_volume_2"]) if r["bid_volume_2"] else 0
                av2 = float(r["ask_volume_2"]) if r["ask_volume_2"] else 0
                mid = float(r["mid_price"])
                rows.append((day, ts, mid, bb1, ba1, bv1, av1, bb2, ba2, bv2, av2))
    return sorted(rows, key=lambda x: (x[0], x[1]))

def main():
    rows = load_hp()
    print(f"HYDROGEL rows: {len(rows)}")

    horizons = [1, 5, 20, 50, 100]
    print("\n=== Imbalance bucket × horizon — mean future Δmid ===")
    print(f"{'imb':>6s} | " + " | ".join(f"h={h:3d}" for h in horizons) + " |   n   |")

    buckets = {}
    for i in range(len(rows) - max(horizons)):
        d0, ts0, mid0, bb1, ba1, bv1, av1, *_ = rows[i]
        if bv1 + av1 == 0:
            continue
        imb = (bv1 - av1) / (bv1 + av1)
        # bucket to nearest 0.1
        bkey = round(imb, 1)
        # check all horizons stay within same day
        ok = all(rows[i+h][0] == d0 for h in horizons)
        if not ok:
            continue
        buckets.setdefault(bkey, []).append([rows[i+h][2] - mid0 for h in horizons])

    for bkey in sorted(buckets):
        n = len(buckets[bkey])
        if n < 30:
            continue
        means = [mean(col) for col in zip(*buckets[bkey])]
        line = f"{bkey:>+6.1f} | " + " | ".join(f"{m:+5.2f}" for m in means) + f" | {n:5d} |"
        print(line)

    # === Persistence: does the move stick or revert? ===
    print("\n=== Persistence test (extreme imbalance only) ===")
    extreme = [v for k, v in buckets.items() if abs(k) >= 0.7 for v in v]
    print(f"  |imb|>=0.7  n={len(extreme)}")
    if extreme:
        for hi, h in enumerate(horizons):
            vals = [row[hi] for row in extreme]
            print(f"  horizon {h:3d}: mean Δ={mean(vals):+.3f} std={stdev(vals):.2f}")

    # === How often does the signal actually fire? ===
    print("\n=== Signal frequency at various thresholds ===")
    total = sum(len(v) for v in buckets.values())
    for thr in [0.3, 0.5, 0.7, 0.9]:
        firing = sum(len(v) for k, v in buckets.items() if abs(k) >= thr)
        print(f"  |imb|>={thr}: {firing} ticks ({100*firing/total:.2f}%) ≈ {firing/3:.0f}/day")

    # === Volume-weighted: bigger imbalances → bigger moves? ===
    print("\n=== Imbalance + volume scale ===")
    big = []
    for i in range(len(rows) - 1):
        d0, ts0, mid0, bb1, ba1, bv1, av1, *_ = rows[i]
        if bv1 + av1 == 0 or rows[i+1][0] != d0:
            continue
        imb = (bv1 - av1) / (bv1 + av1)
        net_vol = bv1 - av1
        d1 = rows[i+1][2] - mid0
        big.append((imb, net_vol, bv1 + av1, d1))

    print("  Bucket by net signed volume (bv-av):")
    bvbuckets = defaultdict(list)
    for imb, nv, tv, d1 in big:
        b = round(nv / 5) * 5
        bvbuckets[b].append(d1)
    for b in sorted(bvbuckets):
        v = bvbuckets[b]
        if len(v) < 50:
            continue
        print(f"    nv≈{b:+4d}: mean Δmid={mean(v):+.3f}  n={len(v)}")

if __name__ == "__main__":
    main()
