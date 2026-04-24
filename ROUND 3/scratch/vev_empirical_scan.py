from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1] / "data_capsule"
FILES = [ROOT / "prices_round_3_day_0.csv", ROOT / "prices_round_3_day_1.csv"]
STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
VEV = {f"VEV_{k}": k for k in STRIKES}
VFE = "VELVETFRUIT_EXTRACT"


def load_rows():
    out = defaultdict(dict)  # (day, ts) -> product -> mid
    for f in FILES:
        with f.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            for r in reader:
                day = int(r["day"])
                ts = int(r["timestamp"])
                prod = r["product"]
                mid = float(r["mid_price"])
                out[(day, ts)][prod] = mid
    return out


def main():
    rows = load_rows()
    keys = sorted(rows.keys())

    # Time value stats by strike.
    tv = defaultdict(list)
    for k in keys:
        m = rows[k]
        s = m.get(VFE)
        if s is None:
            continue
        for sym, strike in VEV.items():
            o = m.get(sym)
            if o is None:
                continue
            intrinsic = max(s - strike, 0.0)
            tv[sym].append(o - intrinsic)

    print("=== Avg empirical time-value (day0+day1) ===")
    for sym in sorted(tv.keys()):
        vals = tv[sym]
        vals_sorted = sorted(vals)
        q10 = vals_sorted[int(0.10 * (len(vals_sorted) - 1))]
        q90 = vals_sorted[int(0.90 * (len(vals_sorted) - 1))]
        print(
            f"{sym}: mean={mean(vals):.2f}  q10={q10:.2f}  q90={q90:.2f}  n={len(vals)}"
        )

    # Mispricing mean-reversion test over next tick.
    # gap_t = option_mid - (intrinsic + avg_time_value_for_strike)
    # ret_{t+1} = option_mid_{t+1} - option_mid_t
    print("\n=== Mean reversion sanity by mispricing bucket (next-tick) ===")
    base_tv = {sym: mean(vals) for sym, vals in tv.items()}

    # Build aligned series per symbol.
    for sym, strike in VEV.items():
        series = []
        for i in range(len(keys) - 1):
            k0 = keys[i]
            k1 = keys[i + 1]
            m0 = rows[k0]
            m1 = rows[k1]
            if sym not in m0 or sym not in m1 or VFE not in m0:
                continue
            s0 = m0[VFE]
            o0 = m0[sym]
            o1 = m1[sym]
            intrinsic = max(s0 - strike, 0.0)
            gap = o0 - (intrinsic + base_tv[sym])
            ret1 = o1 - o0
            series.append((gap, ret1))

        if not series:
            continue
        neg = [r for g, r in series if g <= -2.0]
        mid = [r for g, r in series if -2.0 < g < 2.0]
        pos = [r for g, r in series if g >= 2.0]

        def m(vals):
            return mean(vals) if vals else 0.0

        print(
            f"{sym}: ret1(gap<=-2)={m(neg):+.3f} n={len(neg)} | "
            f"ret1(|gap|<2)={m(mid):+.3f} n={len(mid)} | "
            f"ret1(gap>=2)={m(pos):+.3f} n={len(pos)}"
        )


if __name__ == "__main__":
    main()

