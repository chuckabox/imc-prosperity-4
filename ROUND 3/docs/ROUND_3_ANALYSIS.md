# Round 3 – Data Capsule Analysis

> **Mission:** reach **330,000 XIRECs** this round.
> Round 2 top bots averaged ~250k; the edge this round has to come from the
> **VEV options complex** – we need real option-pricing P&L, not just tighter
> market-making.

Data used: `prices_round_3_day_{0,1,2}.csv` (30k rows × 12 products each).
Timestamp step = 100; each day = 10,000 steps = 1,000,000 timestamp units.

---

## 1. Product universe (12 symbols)

| Symbol | Type | First mid (d0) | Last mid (d2) | Role |
|---|---|---:|---:|---|
| `HYDROGEL_PACK` | stationary | 10,000 | 10,010 | market-make |
| `VELVETFRUIT_EXTRACT` | drifting underlying | 5,250 | 5,295.5 | option underlying / delta hedge |
| `VEV_4000` | deep ITM call | 1,250 | 1,295 | pure VFE proxy (Δ≈1) |
| `VEV_4500` | deep ITM call | 750 | 795.5 | pure VFE proxy (Δ≈1) |
| `VEV_5000` | ITM call | 257 | 296.5 | **vol / gamma** |
| `VEV_5100` | ITM call | 171.5 | 201.5 | **vol / gamma** |
| `VEV_5200` | ATM-ish call | 101.5 | 119 | **vol / gamma (sweetest spot)** |
| `VEV_5300` | ATM-ish call | 53 | 58 | **vol / gamma (sweetest spot)** |
| `VEV_5400` | OTM call | 23 | 20 | vol / gamma |
| `VEV_5500` | OTM call | 8.5 | 7 | vol / gamma |
| `VEV_6000` | deep OTM | 0.5 | 0.5 | dead (stuck at 0/1) |
| `VEV_6500` | deep OTM | 0.5 | 0.5 | dead (stuck at 0/1) |

All VEVs are **European call options** on VELVETFRUIT_EXTRACT with
TTE = 7 Solvenarian days starting **from day 1**. So:

| Day | TTE @ start | TTE @ end |
|---|---:|---:|
| 0 | 8.0 | 7.0 |
| 1 | 7.0 | 6.0 |
| 2 | 6.0 | 5.0 |

(Live competition days 3+ continue the decay.)

---

## 2. VELVETFRUIT_EXTRACT – the underlying

| Metric | Value |
|---|---|
| Mean | 5,250.1 |
| Stdev | 15.63 |
| Range | 5,198 – 5,300 |
| Log-return σ per tick (100 ts) | **0.000215** |
| **Realised σ per day** | **2.15%** |
| Daily drift | +0.29%/day (upward over 3 days) |
| Lag-1 autocorr of returns | −0.159 |

The lag-1 autocorr of −0.16 means short-term **mean reversion** in returns
(bid/ask bounce is a big chunk of this). Lags 5+ are ≈0 → **no medium-term
momentum**, pure diffusion with mild bid-ask noise.

---

## 3. HYDROGEL_PACK – the "OSMIUM / AMETHYSTS" of Round 3

| Metric | Value |
|---|---|
| Mean | 9,990.8 |
| Stdev | 31.9 |
| Range | 9,891 – 10,079 |
| Ornstein-Uhlenbeck θ (per tick) | 0.00230 |
| **Mean-reversion half-life** | **≈301 ticks (30,100 ts)** |
| Per-day means | 9,991 / 9,992 / 9,989 |

Fair value is effectively **flat at ~9,990–10,000**, with strong mean reversion
(half-life 301 ticks = ~3% of a day). Functionally identical to the
OSMIUM/AMETHYSTS pattern: **symmetric market-make with tight skew near
±limit**. Round 2's `OSMIUM_ANCHOR = 10_000` approach is a starting point; the
observed mean is slightly below, so 9,995 may be a better anchor.

---

## 4. VEV options – THE BIG ALPHA

**Implied vol vs realised vol** sampled at each day's open:

| Day | TTE | S | Strike | Market | BS(σ=2.15%) | Δ(market) | **IV/day** |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0 | 8.0 | 5,250.0 | 5000 | 257.00 | 287.29 | −30.29 | **1.25%** |
| 0 | 8.0 | 5,250.0 | 5100 | 171.50 | 214.52 | −43.02 | **1.26%** |
| 0 | 8.0 | 5,250.0 | 5200 | 101.50 | 153.31 | −51.81 | **1.25%** |
| 0 | 8.0 | 5,250.0 | 5300 |  53.00 | 104.50 | −51.50 | **1.27%** |
| 0 | 8.0 | 5,250.0 | 5400 |  23.00 |  67.78 | −44.78 | **1.26%** |
| 0 | 8.0 | 5,250.0 | 5500 |   8.50 |  41.75 | −33.25 | **1.26%** |
| 1 | 7.0 | 5,245.0 | 5200 |  95.50 | 142.36 | −46.86 | **1.28%** |
| 1 | 7.0 | 5,245.0 | 5300 |  47.00 |  94.14 | −47.14 | **1.28%** |
| 2 | 6.0 | 5,267.5 | 5200 | 104.00 | 146.98 | −42.98 | **1.27%** |
| 2 | 6.0 | 5,267.5 | 5300 |  53.00 |  95.50 | −42.50 | **1.32%** |

### The headline
- **Implied vol is a flat 1.25–1.30 %/day across all strikes and all 3 days.**
- **Historical realised vol is 2.15 %/day.**
- The market is using **~58% of the true vol** → options are systematically
  **underpriced by 20–50 XIRECs each**.

### Two ways to read this
1.  **Bots are dumb / using static fair values** — if the market continues to
    price at IV=1.26%, we can hold underpriced calls and let realised
    volatility print us a gamma P&L.
2.  **Realised vol over the live round might be lower** — the 2.15% figure
    includes quote-bounce noise. A purer estimator (5-minute sampling) would
    be lower. Also possible the live days print less vol than the capsule.

Reality is probably between the two, but **at an IV/RV ratio of 0.58 the
margin of safety is enormous**. Even if true vol is 1.7%/day instead of
2.15%, options are still ~25% cheap.

### Per-option theoretical edge (σ_true = 2.15%/day, TTE = 7)

| Option | Market | BS | Edge | Δ | Implied lots at LIMIT=? |
|---|---:|---:|---:|---:|---:|
| VEV_5000 | 277.55 | ~250 | +28 | 0.81 | Limited by VFE delta hedge |
| VEV_5100 | 203.83 | ~160 | +44 | 0.70 | |
| **VEV_5200** | **142.36** | **~95** | **+48** | **0.57** | **sweet spot** |
| **VEV_5300** |  **94.14** |  **~47** | **+47** | **0.44** | **sweet spot** |
| VEV_5400 |  58.75 |  ~17 | +42 | 0.31 | |
| VEV_5500 |  34.53 |   ~7 | +27 | 0.21 | |

**VEV_5200 and VEV_5300** are the cleanest plays: biggest $ edge, gamma is
high, vega is high, and delta ≈ 0.5 so delta-hedging works best.

---

## 5. Dead options – VEV_6000 / VEV_6500

Both are **stuck at mid = 0.5** (bid 0, ask 1) on every single tick of every
day. These are priced at the minimum tick, implying market-makers refuse to
quote tighter and no one trades them. Rational BS value at σ=2.15%, T=7 for
K=6000 is ~1.7, for K=6500 is ~0.02 — so **VEV_6000 is actually cheap at
0.5** but it's essentially illiquid (always 0/1). Expected P&L from
holding to expiry depends entirely on whether VFE spikes through 6000 —
won't in 3 live days.

**Action:** ignore both in v1. Revisit if we see surprising quotes later.

---

## 6. Deep ITM – VEV_4000 / VEV_4500

These are priced at almost exactly **intrinsic value** (S − K) with
essentially no time value. They're delta-1 VFE proxies. Limited edge
unless they become mispriced, which the capsule suggests they won't
(spread of 20 XIRECs vs intrinsic is tight). **Use only as secondary hedge
instruments** if VFE liquidity dries up.

---

## 7. Strategy headlines

| Source of P&L | Expected contribution | Risk |
|---|---|---|
| HYDROGEL market-make | 80–110k over 3 days | low – bounded by LIMIT |
| VFE market-make / drift | 15–40k | medium – directional |
| **VEV long-gamma (hedged)** | **120–200k** | medium – needs delta mgmt |
| VEV spread-capture | 20–40k | low |
| **Total target** | **~330k** | |

Without the VEV layer, 330k is not reachable. HYDROGEL alone can't do it
(OSMIUM in R2 was ≤ 110k).

---

## 8. Open questions to resolve before final submission

1. **Position limits per product for Round 3.** Round 2 used 80 for both.
   VEVs may have smaller limits (typical Prosperity options rounds limit
   vouchers to 200 combined, or 60 per strike). **Test first tick
   empirically; don't hard-code.**
2. **Are the "live" days 3–4 or 3–5?** Affects how aggressive we get with
   late-TTE gamma.
3. ~~**What does the `La_trahison_des_images.png` file contain?**~~
   **Resolved.** The image is René Magritte's *La trahison des images*
   ("Ceci n'est pas une pipe"). Thematically: *the representation is not the
   thing itself*. Our take: **the market's quoted IV (~1.26%/day) is not the
   real volatility (~2.15%/day realised)** — the painting confirms the
   IV/RV gap is the intended alpha. Trade with conviction.
4. **Trade tape signal in `trades_round_3_day_*.csv`:** look for whale
   signatures like Round 1's `Olivia` counter-party that signaled
   reversals.

---

## 9. Reproducing this analysis

```bash
python "ROUND 3/scratch/vev_iv_scan.py"   # prints the IV/RV table
python "ROUND 3/scratch/hydrogel_stats.py"  # prints HP mean-reversion stats
```
