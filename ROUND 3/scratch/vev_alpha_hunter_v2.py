"""VEV Alpha Hunter v2: Trade tape analysis for counterparty patterns.

Inspired by ROUND_3_ANALYSIS.md question #4: "look for whale signatures
like Round 1's Olivia counterparty that signaled reversals."

Scans trade tapes for:
1. Recurring counterparty names and their directional bias
2. Large trades that predict VFE direction (lead-lag from tape)
3. VEV position limit utilization (actual vs theoretical)
"""
from __future__ import annotations

import csv
from collections import defaultdict, Counter
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1] / "data_capsule"
FILES = {
    0: ROOT / "trades_round_3_day_0.csv",
    1: ROOT / "trades_round_3_day_1.csv",
    2: ROOT / "trades_round_3_day_2.csv",
}
PRICE_FILES = {
    0: ROOT / "prices_round_3_day_0.csv",
    1: ROOT / "prices_round_3_day_1.csv",
    2: ROOT / "prices_round_3_day_2.csv",
}


def load_trades():
    out = []
    for day, f in FILES.items():
        with f.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            for r in reader:
                out.append({
                    "day": day,
                    "ts": int(r["timestamp"]),
                    "buyer": r.get("buyer", ""),
                    "seller": r.get("seller", ""),
                    "symbol": r["symbol"],
                    "price": float(r["price"]),
                    "quantity": int(r["quantity"]),
                })
    return out


def load_vfe_prices():
    """Load VFE mid prices for lead-lag analysis."""
    out = {}  # (day, ts) -> mid
    for day, f in PRICE_FILES.items():
        with f.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            for r in reader:
                if r["product"] == "VELVETFRUIT_EXTRACT":
                    mid = float(r["mid_price"]) if r.get("mid_price") else None
                    if mid:
                        out[(day, int(r["timestamp"]))] = mid
    return out


def analyze_counterparties(trades):
    """Find counterparty patterns."""
    print("=" * 80)
    print("ANALYSIS 1: Counterparty Signatures")
    print("=" * 80)

    # Count by buyer/seller per symbol
    buyer_counts = defaultdict(Counter)
    seller_counts = defaultdict(Counter)
    for t in trades:
        if t["buyer"]:
            buyer_counts[t["symbol"]][t["buyer"]] += t["quantity"]
        if t["seller"]:
            seller_counts[t["symbol"]][t["seller"]] += t["quantity"]

    for sym in sorted(set(t["symbol"] for t in trades)):
        buyers = buyer_counts[sym].most_common(10)
        sellers = seller_counts[sym].most_common(10)
        if not buyers and not sellers:
            continue
        print(f"\n{sym}:")
        print(f"  Top Buyers:  {buyers[:5]}")
        print(f"  Top Sellers: {sellers[:5]}")


def analyze_vev_trade_frequency(trades):
    """How often do VEV trades happen and what sizes?"""
    print("\n" + "=" * 80)
    print("ANALYSIS 2: VEV Trade Frequency & Size")
    print("=" * 80)

    vev_trades = defaultdict(list)
    for t in trades:
        if t["symbol"].startswith("VEV_"):
            vev_trades[t["symbol"]].append(t)

    print(f"{'Symbol':<12} {'Count':>6} {'TotalQty':>10} {'AvgQty':>8} {'AvgPrice':>10}")
    for sym in sorted(vev_trades.keys()):
        tl = vev_trades[sym]
        total_qty = sum(t["quantity"] for t in tl)
        avg_qty = total_qty / len(tl) if tl else 0
        avg_price = mean(t["price"] for t in tl) if tl else 0
        print(f"{sym:<12} {len(tl):>6} {total_qty:>10} {avg_qty:>8.1f} {avg_price:>10.1f}")


def analyze_whale_trades(trades, vfe_prices):
    """Look for large VFE trades that predict future VFE direction."""
    print("\n" + "=" * 80)
    print("ANALYSIS 3: Large VFE Trade Predictive Power")
    print("=" * 80)

    vfe_trades = [t for t in trades if t["symbol"] == "VELVETFRUIT_EXTRACT"]
    
    # For each large trade, check VFE return over next N ticks
    for threshold in [10, 20, 30]:
        big_buys_ret = []
        big_sells_ret = []
        for t in vfe_trades:
            if t["quantity"] < threshold:
                continue
            # Look 5 ticks ahead
            future_ts = t["ts"] + 500  # 5 ticks * 100 ts/tick
            current_mid = vfe_prices.get((t["day"], t["ts"]))
            future_mid = vfe_prices.get((t["day"], future_ts))
            if current_mid and future_mid:
                ret = future_mid - current_mid
                if t["buyer"]:  # someone is buying aggressively
                    big_buys_ret.append(ret)
                elif t["seller"]:  # someone is selling aggressively
                    big_sells_ret.append(ret)
        
        buy_avg = mean(big_buys_ret) if big_buys_ret else 0
        sell_avg = mean(big_sells_ret) if big_sells_ret else 0
        print(f"\nThreshold >= {threshold} qty:")
        print(f"  Big Buys  -> next 5-tick VFE ret: {buy_avg:+.3f} (n={len(big_buys_ret)})")
        print(f"  Big Sells -> next 5-tick VFE ret: {sell_avg:+.3f} (n={len(big_sells_ret)})")


def analyze_vev_position_limit(trades):
    """Check actual position limit from the trade data."""
    print("\n" + "=" * 80)
    print("ANALYSIS 4: Actual VEV Position Limits (from trade sizes)")
    print("=" * 80)
    
    # Track cumulative position per symbol per day
    for day in [0, 1, 2]:
        day_trades = [t for t in trades if t["day"] == day]
        positions = defaultdict(int)
        max_pos = defaultdict(int)
        for t in sorted(day_trades, key=lambda x: x["ts"]):
            sym = t["symbol"]
            if not sym.startswith("VEV_"):
                continue
            # Approximate: all trades contribute to total market position
            positions[sym] += t["quantity"]
            max_pos[sym] = max(max_pos[sym], positions[sym])
        
        print(f"\nDay {day} - Cumulative trade volume (proxy for position activity):")
        for sym in sorted(max_pos.keys()):
            print(f"  {sym}: total_vol={positions[sym]}")


if __name__ == "__main__":
    print("Loading trades...")
    trades = load_trades()
    print(f"Loaded {len(trades)} trades.\n")
    
    print("Loading VFE prices...")
    vfe_prices = load_vfe_prices()
    print(f"Loaded {len(vfe_prices)} VFE price snapshots.\n")
    
    analyze_counterparties(trades)
    analyze_vev_trade_frequency(trades)
    analyze_whale_trades(trades, vfe_prices)
    analyze_vev_position_limit(trades)
