"""VEV Alpha Hunter: Deep analysis of option market microstructure.

Scans for untapped alpha in VEV options across all 3 days:
1. Market making opportunity: spreads vs fair value
2. Wing strike liquidity (4000, 4500, 6000, 6500) — currently unused
3. Time-of-day patterns in mispricing
4. Autocorrelation of mispricing (momentum vs mean-reversion)
5. VFE-to-VEV lead-lag relationship
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parents[1] / "data_capsule"
FILES = {
    0: ROOT / "prices_round_3_day_0.csv",
    1: ROOT / "prices_round_3_day_1.csv",
    2: ROOT / "prices_round_3_day_2.csv",
}
ALL_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
FIT_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
VEV = {f"VEV_{k}": k for k in ALL_STRIKES}
VFE = "VELVETFRUIT_EXTRACT"
HP = "HYDROGEL_PACK"


def load_data():
    """Returns dict: (day, ts) -> product -> {mid, bid1, ask1, bid_vol1, ask_vol1}"""
    out = defaultdict(dict)
    for day, f in FILES.items():
        with f.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            for r in reader:
                ts = int(r["timestamp"])
                prod = r["product"]
                mid = float(r["mid_price"]) if r.get("mid_price") else None
                bid1 = float(r["bid_price_1"]) if r.get("bid_price_1") and r["bid_price_1"] else None
                ask1 = float(r["ask_price_1"]) if r.get("ask_price_1") and r["ask_price_1"] else None
                bid_vol1 = float(r["bid_volume_1"]) if r.get("bid_volume_1") and r["bid_volume_1"] else None
                ask_vol1 = float(r["ask_volume_1"]) if r.get("ask_volume_1") and r["ask_volume_1"] else None
                out[(day, ts)][prod] = {
                    "mid": mid, "bid1": bid1, "ask1": ask1,
                    "bid_vol1": bid_vol1, "ask_vol1": ask_vol1,
                }
    return out


def analyze_spreads(data):
    """Analyze spread distribution for each VEV strike."""
    print("=" * 80)
    print("ANALYSIS 1: VEV Spread Distribution (all days)")
    print("=" * 80)
    spreads = defaultdict(list)
    for (day, ts), products in data.items():
        for sym, strike in VEV.items():
            info = products.get(sym)
            if info and info["bid1"] is not None and info["ask1"] is not None:
                s = info["ask1"] - info["bid1"]
                spreads[sym].append(s)

    print(f"{'Strike':<12} {'Mean':>8} {'Std':>8} {'P10':>8} {'Median':>8} {'P90':>8} {'Count':>8}")
    for sym in sorted(spreads.keys(), key=lambda s: VEV[s]):
        vals = sorted(spreads[sym])
        n = len(vals)
        p10 = vals[int(0.10 * (n - 1))]
        p50 = vals[int(0.50 * (n - 1))]
        p90 = vals[int(0.90 * (n - 1))]
        print(f"{sym:<12} {mean(vals):>8.1f} {stdev(vals):>8.1f} {p10:>8.1f} {p50:>8.1f} {p90:>8.1f} {n:>8d}")


def analyze_wing_liquidity(data):
    """Analyze wing strikes (4000, 4500, 6000, 6500) that we're NOT trading."""
    print("\n" + "=" * 80)
    print("ANALYSIS 2: Wing Strike Liquidity & Time Value")
    print("=" * 80)
    wing_strikes = [4000, 4500, 6000, 6500]
    for k in wing_strikes:
        sym = f"VEV_{k}"
        mids = []
        time_vals = []
        for (day, ts), products in sorted(data.items()):
            info = products.get(sym)
            vfe_info = products.get(VFE)
            if info and info["mid"] and vfe_info and vfe_info["mid"]:
                mids.append(info["mid"])
                intr = max(vfe_info["mid"] - k, 0.0)
                time_vals.append(info["mid"] - intr)
        if mids:
            print(f"\n{sym}:")
            print(f"  Mid: mean={mean(mids):.1f} std={stdev(mids):.1f} min={min(mids):.1f} max={max(mids):.1f}")
            print(f"  TimeVal: mean={mean(time_vals):.2f} std={stdev(time_vals):.2f}")
            print(f"  Observations: {len(mids)}")


def analyze_mm_opportunity(data):
    """Analyze passive market-making opportunity using smile fair value."""
    print("\n" + "=" * 80)
    print("ANALYSIS 3: Market Making Opportunity (Fair vs Market)")
    print("=" * 80)
    print("Checking if we can passively quote strikes using our smile model fair value.")
    print("If (market_bid > fair) or (market_ask < fair), that's a passive fill opportunity.\n")

    from collections import Counter

    # For each timestamp, fit smile and check all strikes
    keys = sorted(data.keys())
    opp_counts = defaultdict(lambda: {"buy_opp": 0, "sell_opp": 0, "buy_edge_sum": 0.0, "sell_edge_sum": 0.0})

    for (day, ts) in keys:
        products = data[(day, ts)]
        vfe_info = products.get(VFE)
        if not vfe_info or not vfe_info["mid"]:
            continue
        S = vfe_info["mid"]
        
        # Simple TTE approximation
        TTE_START = 8.0
        T = max(0.5, (TTE_START - day) - ts / 1_000_000)

        # Solve IVs for fit strikes
        fit_iv = {}
        for k in FIT_STRIKES:
            info = products.get(f"VEV_{k}")
            if not info or not info["mid"] or info["mid"] <= 0:
                continue
            iv = _iv_solve(info["mid"], S, k, T)
            if iv is not None:
                fit_iv[k] = iv

        if len(fit_iv) < 4:
            continue

        # Fit smile
        pts = [(math.log(x / S), fit_iv[x]) for x in fit_iv]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        coefs = _solve_3x3(xs, ys)
        if coefs is None:
            continue

        # Check ALL strikes (including wings)
        for k in ALL_STRIKES:
            sym = f"VEV_{k}"
            info = products.get(sym)
            if not info or info["bid1"] is None or info["ask1"] is None:
                continue

            mny = math.log(k / S)
            iv_k = coefs[0] * mny * mny + coefs[1] * mny + coefs[2]
            if iv_k <= 0.01:
                continue
            fair = _bs_call(S, k, T, iv_k)

            # Can we buy below fair?
            if info["ask1"] < fair - 0.5:
                opp_counts[sym]["buy_opp"] += 1
                opp_counts[sym]["buy_edge_sum"] += fair - info["ask1"]
            # Can we sell above fair?
            if info["bid1"] > fair + 0.5:
                opp_counts[sym]["sell_opp"] += 1
                opp_counts[sym]["sell_edge_sum"] += info["bid1"] - fair

    print(f"{'Strike':<12} {'BuyOpps':>8} {'BuyEdge':>10} {'SellOpps':>9} {'SellEdge':>10}")
    for sym in sorted(opp_counts.keys(), key=lambda s: VEV[s]):
        c = opp_counts[sym]
        avg_buy = c["buy_edge_sum"] / c["buy_opp"] if c["buy_opp"] > 0 else 0
        avg_sell = c["sell_edge_sum"] / c["sell_opp"] if c["sell_opp"] > 0 else 0
        print(f"{sym:<12} {c['buy_opp']:>8d} {avg_buy:>10.2f} {c['sell_opp']:>9d} {avg_sell:>10.2f}")


def analyze_vfe_lead_lag(data):
    """Check if VFE moves lead VEV mid-price moves (exploitable momentum)."""
    print("\n" + "=" * 80)
    print("ANALYSIS 4: VFE-to-VEV Lead-Lag (does VFE predict VEV moves?)")
    print("=" * 80)

    keys = sorted(data.keys())
    for k in [5200, 5300]:
        sym = f"VEV_{k}"
        vfe_ret = []
        vev_next_ret = []
        for i in range(len(keys) - 2):
            k0, k1, k2 = keys[i], keys[i+1], keys[i+2]
            d0, d1, d2 = data[k0], data[k1], data[k2]
            # Same day only
            if k0[0] != k1[0] or k1[0] != k2[0]:
                continue
            vfe0 = d0.get(VFE, {}).get("mid")
            vfe1 = d1.get(VFE, {}).get("mid")
            vev1 = d1.get(sym, {}).get("mid")
            vev2 = d2.get(sym, {}).get("mid")
            if all(v is not None and v > 0 for v in [vfe0, vfe1, vev1, vev2]):
                vfe_ret.append(vfe1 - vfe0)
                vev_next_ret.append(vev2 - vev1)

        if len(vfe_ret) > 100:
            # Bucket VFE returns
            neg = [r for v, r in zip(vfe_ret, vev_next_ret) if v < -1]
            mid = [r for v, r in zip(vfe_ret, vev_next_ret) if -1 <= v <= 1]
            pos = [r for v, r in zip(vfe_ret, vev_next_ret) if v > 1]
            print(f"\n{sym}:")
            print(f"  VFE down>1 -> next VEV ret: {mean(neg) if neg else 0:+.3f} (n={len(neg)})")
            print(f"  VFE flat   -> next VEV ret: {mean(mid) if mid else 0:+.3f} (n={len(mid)})")
            print(f"  VFE up>1   -> next VEV ret: {mean(pos) if pos else 0:+.3f} (n={len(pos)})")


def analyze_time_of_day(data):
    """Check if mispricing is stronger at certain times of day."""
    print("\n" + "=" * 80)
    print("ANALYSIS 5: Time-of-Day Patterns in VEV Spreads")
    print("=" * 80)

    # Bucket by timestamp ranges
    buckets = {
        "0-100k (Open)": (0, 100_000),
        "100k-300k (Early)": (100_000, 300_000),
        "300k-600k (Mid)": (300_000, 600_000),
        "600k-900k (Late)": (600_000, 900_000),
        "900k+ (Close)": (900_000, 1_000_001),
    }
    for sym in [f"VEV_{k}" for k in FIT_STRIKES]:
        print(f"\n{sym}:")
        for bucket_name, (lo, hi) in buckets.items():
            spreads = []
            for (day, ts), products in data.items():
                if lo <= ts < hi:
                    info = products.get(sym)
                    if info and info["bid1"] is not None and info["ask1"] is not None:
                        spreads.append(info["ask1"] - info["bid1"])
            if spreads:
                print(f"  {bucket_name}: spread mean={mean(spreads):.1f} std={stdev(spreads):.1f} n={len(spreads)}")


# ---------- BS Helpers ----------

def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _bs_call(S, K, T, sigma):
    if T <= 1e-10 or sigma <= 1e-10:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)

def _iv_solve(price, S, K, T):
    intr = max(0.0, S - K)
    if price <= intr + 1e-6 or price >= S:
        return None
    lo, hi = 1e-4, 2.0
    for _ in range(32):
        mid = 0.5 * (lo + hi)
        if _bs_call(S, K, T, mid) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)

def _solve_3x3(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    sx = sum(xs); sx2 = sum(x*x for x in xs); sx3 = sum(x**3 for x in xs); sx4 = sum(x**4 for x in xs)
    sy = sum(ys); sxy = sum(x*y for x,y in zip(xs,ys)); sx2y = sum(x*x*y for x,y in zip(xs,ys))
    A = [[sx4, sx3, sx2], [sx3, sx2, sx], [sx2, sx, n]]
    b = [sx2y, sxy, sy]
    det = (A[0][0]*(A[1][1]*A[2][2]-A[1][2]*A[2][1]) - A[0][1]*(A[1][0]*A[2][2]-A[1][2]*A[2][0]) + A[0][2]*(A[1][0]*A[2][1]-A[1][1]*A[2][0]))
    if abs(det) < 1e-12:
        return None
    inv = 1.0 / det
    x1 = (b[0]*(A[1][1]*A[2][2]-A[1][2]*A[2][1]) - A[0][1]*(b[1]*A[2][2]-A[1][2]*b[2]) + A[0][2]*(b[1]*A[2][1]-A[1][1]*b[2])) * inv
    x2 = (A[0][0]*(b[1]*A[2][2]-A[1][2]*b[2]) - b[0]*(A[1][0]*A[2][2]-A[1][2]*A[2][0]) + A[0][2]*(A[1][0]*b[2]-b[1]*A[2][0])) * inv
    x3 = (A[0][0]*(A[1][1]*b[2]-b[1]*A[2][1]) - A[0][1]*(A[1][0]*b[2]-b[1]*A[2][0]) + b[0]*(A[1][0]*A[2][1]-A[1][1]*A[2][0])) * inv
    return (x1, x2, x3)


if __name__ == "__main__":
    print("Loading data...")
    data = load_data()
    print(f"Loaded {len(data)} timestamp snapshots.\n")
    analyze_spreads(data)
    analyze_wing_liquidity(data)
    analyze_mm_opportunity(data)
    analyze_vfe_lead_lag(data)
    analyze_time_of_day(data)
