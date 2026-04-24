# Round 3 – Strategy Plan

Goal: **330k XIRECs** over 3+ live days. See `ROUND_3_ANALYSIS.md` for the
raw data-capsule findings that motivate the decisions below.

---

## The thesis in one paragraph

The VEV option complex is systematically priced with **IV ≈ 1.26%/day** while
the underlying's **realised vol ≈ 2.15%/day**. That's a 40% vol-mispricing on
a whole chain. If we buy the right strikes and delta-hedge, the gamma
P&L alone should clear six figures. Layer in (a) traditional HYDROGEL_PACK
mean-reversion market-making (the OSMIUM/AMETHYSTS pattern we solved in
R1/R2) and (b) opportunistic VFE directional exposure, and 330k is in reach.

---

## Module 1 – HYDROGEL_PACK (defensive base P&L, target 80–110k)

**Nature:** stationary, mean-reverting around ~9,990–10,000, OU half-life
≈ 301 ticks, stdev ≈ 32.

**Strategy:** symmetric two-level market maker around a dynamic anchor.

```
anchor       = 9995     # start; blend with EWMA mid
take_edge    = 1        # take when best bid/ask crosses fair ± 1
quote_front  = 28       # size at fair ± 1
quote_second = 20       # size at fair ± 3
skew_soft    = 15       # start skewing quotes above this net position
skew_hard    = 35       # heavy skew
flatten_hard = 58       # flatten aggressively (circuit breaker)
```

Directly port `_osmium_logic` from `ROUND 2/traders/peter/trader_peter_v1.py`
with `ANCHOR = 9995` and re-tuning the skew to Round 3 depth. The R2 logic
already handles the toxicity filter and the skew ladder.

**Risks:** HYDROGEL mean may drift during live days. The EWMA blend (R2's
`VWAP_WEIGHT = 0.65` live, 0.35 anchor) makes it adaptive.

---

## Module 2 – VELVETFRUIT_EXTRACT market-making + trend (target 15–40k)

**Nature:** drifting (+0.29%/day), realised σ ~2.15%/day, lag-1 autocorr
−0.16 (noisy, but pure diffusion beyond lag 1).

**Two roles** (prioritised in order):

### 2a. Delta-hedge vehicle for the VEV book (most important)

After computing portfolio delta from the VEV positions, aim to hold
`-Δ_portfolio` units of VFE. Rebalance whenever |Δ_residual| > hedge_band
(start with band = 10 units). This is the engine that extracts gamma P&L
from module 3.

### 2b. Standalone passive market-making (secondary)

Quote passively at mid ± 2 with small size (e.g., 10 lots). Do **not**
chase the trend naively — we've seen 30%+ losses in R2 from PEPPER/OSMIUM
trend chasing. Only trend-follow on confirmed slope > 0.08 per 100 ticks
(Round 2 PEPPER `SLOPE_STRONG`), and cap at 30 lots to leave room for the
delta-hedge.

---

## Module 3 – VEV options book (THE alpha, target 120–200k)

This is where we make or break the round. The structure:

### Pricing engine

Every tick:

1. Snapshot `S = mid(VELVETFRUIT_EXTRACT)`.
2. Compute `TTE_days = (8 - day) - timestamp / 1_000_000`.
3. Use **σ_model = 0.018 per day** (20% conservative haircut on the 2.15%
   historical — leaves room for vol-of-vol surprise).
4. For each active strike K, compute
   `BS_fair(S, K, TTE_days, σ_model)` and `BS_delta(...)`.

### Position rules

- **Primary strikes: VEV_5200, VEV_5300** (highest $ edge, highest Γ, Δ ≈ 0.5).
- **Secondary: VEV_5100, VEV_5400** (good edge, cleaner Δ).
- **Tertiary: VEV_5000, VEV_5500** (some edge, position-sized half of secondary).
- **Ignore: VEV_4000, VEV_4500** (no edge, delta-1 proxies) and
  `VEV_6000 / VEV_6500` (illiquid, quoted at 0/1).

### Entry rule (per strike)

```
edge = BS_fair(σ_model) - best_ask   # positive → option is cheap
if edge > min_edge_enter:
    target_long = min(K_limit, edge * k_scale)
    buy up to target_long at best_ask
```

Start with `min_edge_enter = 4` XIRECs, `k_scale = 3`. Tune in backtest.

Symmetrically for short side when `best_bid - BS_fair > min_edge_enter`
(will rarely trigger since the whole chain is cheap, but stay symmetric to
avoid being run over if the market corrects).

### Delta hedging

After every trade or every N ticks (N=5 to bound rebalance costs):

```
portfolio_delta = sum over strikes (position_VEV[K] * delta_BS(K))
target_VFE = round(-portfolio_delta)
send orders to bring VFE position toward target_VFE,
  with a dead-band of ±10 to avoid churning
```

### Risk caps

- Per-strike cap = 80% of per-strike position limit (leave room to unwind).
- Total gross vega cap: if realised vol keeps falling short of σ_model for
  > 2000 ticks, halve new-entry size.
- Hard stop: if net daily P&L on the VEV book < -15k, flatten and
  market-make only.

---

## Module 4 – Cross-strike arbitrage (target 20–40k, if present)

Call-spread no-arbitrage: `C(K1) - C(K2) ≤ K2 - K1` for K1 < K2. With
R3's market quotes, check every tick for:

```
if ask(VEV_Klow) + bid(VEV_Khigh) * ... violates the box,
    lock in the synthetic arbitrage
```

Also watch for **ITM options quoted above S - K** (violates lower bound).
With the capsule data this doesn't appear to happen often, but a
pure-arb module costs nothing if capped at tiny size.

---

## What we are **not** doing (and why)

| Temptation | Why we skip |
|---|---|
| Trading VEV_6000 / VEV_6500 | bid 0, ask 1: always at minimum tick, no fills |
| Heavy directional VFE | no detectable trend beyond noise; R2 taught us trend chasing is expensive |
| Unhedged long gamma | if vol dries up on the live days we eat theta; hedging keeps us P&L-positive even at low realised vol |
| Market-making the deep-ITM VEV_4000 | spread is 20, edge is 0, no value |
| Inventing a full IV surface | the flat IV chain tells us a single σ is all we need; don't over-fit |

---

## Ordered implementation plan

1. **Set up the framework** (this PR): config, docs, scratch scripts,
   starter trader skeleton. ← _we are here_
2. **Wire HYDROGEL logic** (port OSMIUM from R2). Backtest — should hit
   ~100k on the capsule.
3. **Wire BS engine + VEV pricing.** Paper-trade on the capsule with no
   execution, log fair-vs-market to CSV, sanity-check IVs.
4. **Add VEV entry + delta-hedge logic.** Backtest on the 3-day capsule.
   Target: gamma P&L > 100k across all 3 days combined.
5. **Add no-arb cross-strike checks.** Cheap to add, may catch rare gifts.
6. **Robustness pass:** run against R1/R2 scenarios + synthetic
   vol-dried-up stress (σ_realised = 0.8%/day). Ensure the bot still
   makes money (via HYDROGEL) even if option book goes flat.
7. **Parameter sweep** (via `tools/manual_optimiser/`) on
   `min_edge_enter`, `k_scale`, hedge band, σ_model haircut.
8. **Final leaderboard check** — compare final PnLs across Ken / Peter /
   Suvin variants.

---

## Position-limit uncertainty

We do **not** yet know the per-product limits for Round 3. Round 2 used
80 for each top-level symbol. Historical Prosperity option rounds often
use 200 per strike or 60 per strike with a 250 aggregate cap. **First task
at the start of live Round 3 is to query the actual limits** (they're
exposed in the `TradingState`) and adapt sizing.

The starter trader scaffolds the logic around `self.limits[symbol]` so
changing the dict in one place adapts every module.
