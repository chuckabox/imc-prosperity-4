"""Deep data analysis for Round 3 — looking for the real alpha.

Hypotheses tested:
1. HYDROGEL_PACK has a hidden non-stationary signal (the "real alpha" hint).
2. VFE realized vol is inflated by bid-ask bounce; true vol may be much
   lower than 2.15%/day, making the option mispricing thesis wrong.
3. There is a cross-asset relationship between HYDROGEL and VFE/vouchers.
4. Voucher prices follow a pattern that isn't pure Black-Scholes.
"""
from __future__ import annotations
import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parents[1] / "data_capsule"
FILES = [ROOT / f"prices_round_3_day_{d}.csv" for d in (0, 1, 2)]
VFE = "VELVETFRUIT_EXTRACT"
HP = "HYDROGEL_PACK"
STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]

def load_rows():
    out = defaultdict(dict)  # (day, ts) -> product -> (mid, bb, ba, bvol, avol)
    for f in FILES:
        with f.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            for r in reader:
                day = int(r["day"])
                ts = int(r["timestamp"])
                prod = r["product"]
                mid = float(r["mid_price"])
                bb = float(r["bid_price_1"]) if r["bid_price_1"] else None
                ba = float(r["ask_price_1"]) if r["ask_price_1"] else None
                bv = float(r["bid_volume_1"]) if r["bid_volume_1"] else 0
                av = float(r["ask_volume_1"]) if r["ask_volume_1"] else 0
                out[(day, ts)][prod] = (mid, bb, ba, bv, av)
    return out

def returns(series):
    return [series[i] - series[i-1] for i in range(1, len(series))]

def log_returns(series):
    return [math.log(series[i]/series[i-1]) for i in range(1, len(series)) if series[i-1] > 0]

def autocorr(x, lag=1):
    if len(x) <= lag:
        return 0.0
    m = mean(x)
    var = sum((v-m)**2 for v in x) / len(x)
    if var == 0:
        return 0.0
    cov = sum((x[i]-m)*(x[i-lag]-m) for i in range(lag, len(x))) / (len(x) - lag)
    return cov / var

def main():
    rows = load_rows()
    keys = sorted(rows.keys())
    print(f"Loaded {len(keys)} timestamps across {len(set(k[0] for k in keys))} days\n")

    # Build per-product mid series
    series = defaultdict(list)
    for k in keys:
        for prod, vals in rows[k].items():
            series[prod].append((k, vals[0]))

    # === Volatility analysis: bias-corrected ===
    print("=== Realized volatility analysis (bias correction) ===")
    print("For mid_price returns: σ_obs^2 = σ_true^2 + 2*σ_noise^2 (bid-ask bounce model)")
    print("Cov(r_t,r_{t-1}) = -σ_noise^2  =>  σ_true^2 = σ_obs^2 + 2*Cov_lag1\n")
    for prod in [VFE, HP]:
        if prod not in series:
            continue
        # tick-to-tick log returns
        for resample in [1, 5, 50, 500]:
            mids = [m for _, m in series[prod]][::resample]
            if len(mids) < 100:
                continue
            rets = log_returns(mids)
            sd = stdev(rets) if len(rets) > 1 else 0
            ac1 = autocorr(rets, 1)
            ac5 = autocorr(rets, 5)
            # Per-day vol scaling (10000 ticks per day, so 100/resample multiplier on sqrt)
            ticks_per_day = 10000 / resample
            day_vol = sd * math.sqrt(ticks_per_day)
            # bias-corrected
            cov1 = ac1 * sd * sd
            true_var = sd*sd + 2*cov1  # for AR(1) bid-ask model
            true_var = max(true_var, 0)
            true_day_vol = math.sqrt(true_var * ticks_per_day)
            print(f"  {prod} resample={resample}: σ_obs/day={day_vol*100:.3f}%  ac1={ac1:+.3f}  ac5={ac5:+.3f}  σ_true/day≈{true_day_vol*100:.3f}%")
        print()

    # === Hydrogel deep dive ===
    print("=== HYDROGEL_PACK deep dive ===")
    hp_mids = [m for _, m in series[HP]]
    print(f"  N={len(hp_mids)}")
    print(f"  mean={mean(hp_mids):.2f} std={stdev(hp_mids):.2f} min={min(hp_mids):.1f} max={max(hp_mids):.1f}")
    # Per-day stats
    by_day = defaultdict(list)
    for (d, ts), m in series[HP]:
        by_day[d].append(m)
    for d in sorted(by_day):
        s = by_day[d]
        print(f"  day{d}: mean={mean(s):.2f} std={stdev(s):.2f} range=[{min(s):.1f},{max(s):.1f}]")

    # Mean-reversion: what's the half-life with current rolling mean?
    rets = returns(hp_mids)
    # OU: dx = -theta*(x - mu)*dt + ...
    # Regress dx on (x - mu)
    mu = mean(hp_mids)
    xc = [m - mu for m in hp_mids[:-1]]
    dx = rets
    num = sum(x*d for x,d in zip(xc, dx))
    den = sum(x*x for x in xc)
    theta = -num/den if den else 0
    half_life_ticks = math.log(2) / theta if theta > 0 else float('inf')
    print(f"  OU theta (per tick)={theta:.5f}  half_life={half_life_ticks:.0f} ticks ({half_life_ticks/100:.0f} ts of timestamp)")

    # Stationarity: split into 4 chunks, check mean shifts
    n = len(hp_mids)
    for i in range(4):
        chunk = hp_mids[i*n//4:(i+1)*n//4]
        print(f"  chunk{i}: mean={mean(chunk):.2f} std={stdev(chunk):.2f}")

    # === Cross-asset correlation between HP changes and other products ===
    print("\n=== Cross-asset Δmid correlations (lag 0 and lag 1) ===")
    # Build aligned arrays
    aligned = defaultdict(list)
    for k in keys:
        m = rows[k]
        if HP in m and VFE in m:
            for prod in m:
                aligned[prod].append((k, m[prod][0]))
    # Use products with full data
    main_prods = [HP, VFE] + [f"VEV_{k}" for k in STRIKES]
    deltas = {}
    for p in main_prods:
        if p in series:
            mids = [m for _, m in series[p]]
            deltas[p] = returns(mids)

    n_min = min(len(v) for v in deltas.values())
    for p in main_prods:
        deltas[p] = deltas[p][:n_min]

    def corr(a, b):
        ma, mb = mean(a), mean(b)
        sa = sum((x-ma)**2 for x in a)**0.5
        sb = sum((x-mb)**2 for x in b)**0.5
        if sa == 0 or sb == 0:
            return 0
        return sum((x-ma)*(y-mb) for x,y in zip(a,b)) / (sa*sb)

    print(f"  {'pair':25s}  corr0   corr1(HP→other)  corr1(other→HP)")
    for p in main_prods:
        if p == HP:
            continue
        c0 = corr(deltas[HP], deltas[p])
        # lag1: HP at t-1 predicts other at t
        c1f = corr(deltas[HP][:-1], deltas[p][1:])
        # lag1: other at t-1 predicts HP at t
        c1b = corr(deltas[p][:-1], deltas[HP][1:])
        print(f"  HP-{p:22s}  {c0:+.3f}   {c1f:+.3f}              {c1b:+.3f}")

    # === Order book imbalance for HYDROGEL — predictive power? ===
    print("\n=== HYDROGEL order book imbalance signal ===")
    imb_data = []  # (imbalance, next_return)
    hp_data = [(k, *v) for k, val in rows.items() if HP in val for v in [val[HP]]]
    hp_data.sort(key=lambda x: x[0])  # sort by (day, ts)
    for i in range(len(hp_data) - 1):
        k0, mid0, bb, ba, bv, av = hp_data[i]
        k1, mid1, *_ = hp_data[i+1]
        if k0[0] != k1[0]:  # don't cross day boundaries
            continue
        if bv + av == 0:
            continue
        imb = (bv - av) / (bv + av)
        ret = mid1 - mid0
        imb_data.append((imb, ret))

    # Bucket by imbalance
    buckets = defaultdict(list)
    for imb, ret in imb_data:
        b = round(imb * 4) / 4  # 0.25 bucket
        buckets[b].append(ret)
    print(f"  {'imbalance':>10s}   mean_next_Δmid    n")
    for b in sorted(buckets):
        v = buckets[b]
        if len(v) < 50:
            continue
        print(f"  {b:>+10.2f}     {mean(v):+.4f}        {len(v)}")

    # === HYDROGEL: time-of-day pattern? ===
    print("\n=== HYDROGEL time-of-day mean ===")
    by_ts_bucket = defaultdict(list)
    for (d, ts), m in series[HP]:
        bucket = ts // 100000  # 10 buckets per day
        by_ts_bucket[bucket].append(m)
    for b in sorted(by_ts_bucket):
        v = by_ts_bucket[b]
        print(f"  ts_bucket {b}: mean={mean(v):.2f} std={stdev(v):.2f} n={len(v)}")

    # === Voucher dynamics: how do prices evolve through the day ===
    print("\n=== Voucher mid prices: per-day mean (decay check) ===")
    print(f"  {'product':15s} day0      day1      day2")
    by_day_prod = defaultdict(lambda: defaultdict(list))
    for (d, ts), m in series[VFE]:
        by_day_prod[VFE][d].append(m)
    for s in STRIKES:
        sym = f"VEV_{s}"
        for (d, ts), m in series[sym]:
            by_day_prod[sym][d].append(m)
    for sym in [VFE] + [f"VEV_{s}" for s in STRIKES]:
        line = f"  {sym:15s}"
        for d in (0,1,2):
            v = by_day_prod[sym][d]
            line += f"  {mean(v):8.2f}"
        print(line)

if __name__ == "__main__":
    main()
