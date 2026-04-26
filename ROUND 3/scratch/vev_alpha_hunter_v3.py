"""VEV Alpha Hunter v3: Long Gamma / IV Scalping analysis.

The ROUND_3_ANALYSIS doc and Frankfurt Hedgehogs both identify the IV/RV gap
as the core alpha. Market IV ≈ 1.26%/day vs Realised Vol ≈ 2.15%/day.

This script quantifies:
1. Pure gamma PnL from buying ATM options and delta-hedging
2. IV scalping: buying when IV deviates below the smile (same as our RV pairs)
3. Whether we can buy options CHEAPER than intrinsic at certain timestamps
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
FIT_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
VFE = "VELVETFRUIT_EXTRACT"


def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _bs_call(S, K, T, sigma):
    if T <= 1e-10 or sigma <= 1e-10:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def load_data():
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
                out[(day, ts)][prod] = {"mid": mid, "bid1": bid1, "ask1": ask1}
    return out


def analyze_intrinsic_violations(data):
    """Check if options ever trade BELOW intrinsic value."""
    print("=" * 80)
    print("ANALYSIS 1: Options Below Intrinsic Value")
    print("=" * 80)
    
    for k in FIT_STRIKES:
        sym = f"VEV_{k}"
        violations = []
        for (day, ts), products in sorted(data.items()):
            info = products.get(sym)
            vfe = products.get(VFE)
            if not info or not vfe or info["ask1"] is None or vfe["mid"] is None:
                continue
            intrinsic = max(vfe["mid"] - k, 0.0)
            if info["ask1"] < intrinsic - 0.5:
                violations.append({
                    "day": day, "ts": ts,
                    "ask": info["ask1"], "intrinsic": intrinsic,
                    "free_money": intrinsic - info["ask1"],
                })
        
        if violations:
            avg_edge = mean(v["free_money"] for v in violations)
            print(f"\n{sym}: {len(violations)} intrinsic violations!")
            print(f"  Avg free money: {avg_edge:.2f}")
            print(f"  Sample: {violations[:3]}")
        else:
            print(f"{sym}: No intrinsic violations (clean)")


def analyze_gamma_pnl_potential(data):
    """Simulate theoretical gamma PnL from holding ATM options and hedging."""
    print("\n" + "=" * 80)
    print("ANALYSIS 2: Theoretical Gamma PnL (Buy & Delta-Hedge)")
    print("=" * 80)
    
    # Track VFE moves tick-to-tick and compute gamma PnL
    keys = sorted(data.keys())
    
    for k in [5200, 5300]:
        sym = f"VEV_{k}"
        gamma_pnls = []
        
        for day in [0, 1, 2]:
            day_keys = [(d, t) for d, t in keys if d == day]
            if len(day_keys) < 2:
                continue
            
            TTE_START = 8.0
            
            for i in range(len(day_keys) - 1):
                k0, k1 = day_keys[i], day_keys[i+1]
                p0, p1 = data[k0], data[k1]
                
                vfe0 = p0.get(VFE, {}).get("mid")
                vfe1 = p1.get(VFE, {}).get("mid")
                opt0 = p0.get(sym, {}).get("mid")
                opt1 = p1.get(sym, {}).get("mid")
                
                if not all(v is not None for v in [vfe0, vfe1, opt0, opt1]):
                    continue
                
                T = max(0.5, (TTE_START - day) - k0[1] / 1_000_000)
                
                # Use market IV as proxy
                sigma_mkt = 0.0126 * math.sqrt(365)  # 1.26%/day annualized
                
                # Gamma PnL = 0.5 * gamma * (dS)^2
                sqrt_T = math.sqrt(T)
                d1 = (math.log(vfe0 / k) + 0.5 * sigma_mkt**2 * T) / (sigma_mkt * sqrt_T)
                pdf = math.exp(-0.5 * d1**2) / math.sqrt(2 * math.pi)
                gamma = pdf / (vfe0 * sigma_mkt * sqrt_T)
                
                dS = vfe1 - vfe0
                gamma_pnl = 0.5 * gamma * dS * dS
                
                # Theta cost per tick
                theta = -(vfe0 * pdf * sigma_mkt) / (2 * sqrt_T)
                dt = 1.0 / 1_000_000  # 1 tick in days
                theta_cost = abs(theta) * dt
                
                net = gamma_pnl - theta_cost
                gamma_pnls.append(net)
        
        if gamma_pnls:
            total = sum(gamma_pnls)
            avg = mean(gamma_pnls)
            pos_pct = len([x for x in gamma_pnls if x > 0]) / len(gamma_pnls)
            print(f"\n{sym} (per 1 contract held):")
            print(f"  Total gamma PnL (3 days): {total:.2f}")
            print(f"  Avg per tick: {avg:.4f}")
            print(f"  % positive ticks: {pos_pct:.1%}")
            print(f"  If held 50 contracts: {total * 50:.0f} XIRECs")


def analyze_market_iv_vs_realized(data):
    """Compare market-implied IV to realized vol more precisely."""
    print("\n" + "=" * 80)
    print("ANALYSIS 3: IV vs Realized Vol (per day)")
    print("=" * 80)
    
    keys = sorted(data.keys())
    for day in [0, 1, 2]:
        day_keys = [(d, t) for d, t in keys if d == day]
        vfe_rets = []
        for i in range(len(day_keys) - 1):
            p0 = data[day_keys[i]].get(VFE, {}).get("mid")
            p1 = data[day_keys[i+1]].get(VFE, {}).get("mid")
            if p0 and p1 and p0 > 0:
                vfe_rets.append(math.log(p1 / p0))
        
        if vfe_rets:
            tick_vol = stdev(vfe_rets)
            # 10000 ticks/day
            daily_vol = tick_vol * math.sqrt(10000)
            ann_vol = daily_vol * math.sqrt(365)
            print(f"\nDay {day}:")
            print(f"  Per-tick log-return stdev: {tick_vol:.6f}")
            print(f"  Daily vol: {daily_vol:.4f} ({daily_vol*100:.2f}%)")
            print(f"  Annualized vol: {ann_vol:.4f} ({ann_vol*100:.1f}%)")
            print(f"  Market IV (annualized): ~24.1%  (1.26%/day)")
            print(f"  Ratio RV/IV: {ann_vol/0.241:.2f}x")


if __name__ == "__main__":
    print("Loading data...")
    data = load_data()
    print(f"Loaded {len(data)} snapshots.\n")
    
    analyze_intrinsic_violations(data)
    analyze_gamma_pnl_potential(data)
    analyze_market_iv_vs_realized(data)
