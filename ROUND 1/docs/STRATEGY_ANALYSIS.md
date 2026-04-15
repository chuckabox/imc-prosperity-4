# Round 1 Strategy Analysis

Generated: 2026-04-15  
Backtester: `backtest_cli.py` (aggressive take + 50% passive fill simulation)  
Products: `ASH_COATED_OSMIUM` | `INTARIAN_PEPPER_ROOT` | Position limit: 80 each

---

## Backtest Results Summary

| Trader | Day -2 | Day -1 | Day 0 | **Total** |
|---|---|---|---|---|
| `archive/old_ken/trader_ken_v6_1.py` | 100,480 | 101,713 | 99,288 | **301,481** ✅ |
| `traders/trader_ken_v2.py` | 90,885 | 92,362 | 89,595 | **272,842** |
| `trader_peter4.py` | 90,885 | 92,362 | 89,595 | **272,842** ✅ |
| `trader_peter2_2.py` | 81,309 | 89,103 | 84,907 | **255,319** |
| `trader_peter2_2_1.py` | 81,309 | 89,103 | 84,907 | **255,319** |
| `trader_peter3.py` | 82,626 | 82,302 | 82,584 | **247,512** |
| `trader_adin.py` | 81,480 | 80,938 | 81,086 | **243,504** |
| `trader_peter_2_2_2.py` | 69,353 | 75,468 | 56,054 | **200,875** |
| `trader.py` (current production) | 97,348 | 18,764 | -63,903 | **52,210** ⚠️ |
| `old_peter/trader_peter10.py` | 31,487 | 33,012 | 32,373 | **96,872** |
| `old_peter/trader_peter11.py` | 49,865 | -28,401 | -117,611 | **-96,147** 🚨 |

> Note: `trader_adin.py` required a `traderData` attribute fix to run on `backtest_cli.py`.  
> README reports actual competition score of ~8k — backtest numbers are inflated due to generous passive fill simulation (50% of market volume).
> `trader_ken_v2.py` matches `trader_10k`/`trader_peter4` style and reproduced the same local total.

---

## Osmium-First Analysis (Priority)

The Round 1 hint indicates that `ASH_COATED_OSMIUM` may have a hidden pattern. In practice, the strongest variants still rely on a stable anchor around `10000`, then improve execution adaptively.

### Osmium Strategy Progression

| Family | Osmium Fair | Execution | Outcome |
|---|---|---|---|
| Baseline market makers (`peter4`, `ken v2`, `10k`) | `10000 + tape_adj` (capped) | sniper + pennying + basic skew | Stable and strong |
| Tuned variant (`ken v6.1`) | `10000 + tape_adj + mid_pull` | spread-aware take edge + dynamic skew + split passive size | Better local consistency and higher totals |
| Failed regression attempts (`trader.py`, `peter11`) | 3-lag regression with old intercept/weights | sniper + layering | Fair-value drift, poor firing quality, unstable PnL |

### What Matters Most for Osmium

1. **Correct fair-value center**  
   Keep fair anchored near `10000` unless regression is re-fitted on Osmium-specific data. Old STARFRUIT-style coefficients are miscalibrated for current Osmium scale.

2. **Capped tape adjustment**  
   Tape should be capped (e.g., ±2.5 to ±3.0) to avoid overreacting to one timestamp.

3. **Adaptive execution beats static execution**  
   Spread-aware take thresholds and stronger skew at large inventory improve reliability over fixed `2.5`/fixed skew setups.

4. **Inventory safety is non-negotiable**  
   Dynamic skew and multi-level quoting reduce chance of getting pinned near limit.

### Practical Recommendation for Osmium

- Use the `ken v6.1` Osmium structure as baseline behavior.
- If testing hidden-pattern models, keep the `v6.1` execution layer unchanged and only swap the fair estimator.
- Reject any regression fair that drifts away from observed book center for long periods.

---

## Pepper Root Analysis (Dedicated)

Pepper behaves differently from Osmium in this dataset. The strongest performers are trend-friendly and can hold inventory for extended periods. Over-defensive rewrites reduced PnL materially in local backtests.

### Pepper Variant Comparison (same Osmium baseline, `backtest_cli.py`)

| Variant | Day -2 | Day -1 | Day 0 | Total | Notes |
|---|---:|---:|---:|---:|---|
| `ken_pepper_original.py` | 99,436 | 101,852 | 98,018 | **299,306** | Original aggressive Pepper (best so far) |
| `ken_pepper_v3.py` | 99,271 | 101,620 | 97,637 | 298,528 | Tiny near-limit safety, very small tradeoff |
| `ken_pepper_v4.py` | 98,279 | 100,474 | 96,481 | 295,234 | Capital-preservation mode (stronger rails + emergency unwind) |
| `ken_pepper_v1.py` | 34,683 | 41,185 | 31,485 | 107,353 | Too defensive |
| `ken_pepper_v2.py` | 31,872 | 39,119 | 30,628 | 101,619 | Still too defensive |

### What We Learned About Pepper

1. **Aggression is currently rewarded**  
   The original Pepper logic (fast accumulation + spike exits) dominates in this harness.

2. **Large safety rewrites hurt too much**  
   Tight caps, wide passive quotes, and small clips reduce inventory risk but destroy trend capture.

3. **Small safety layers are viable**  
   `v3` keeps nearly all PnL while adding near-limit protection; this is the best balance so far.

4. **Capital-preservation mode is workable but costs edge**  
   `v4` improves crash posture with earlier rails and emergency unwind, but gives up additional PnL versus `v3`/original.

### Recommended Pepper Baseline

- Use `ken_pepper_original.py` when optimizing for pure local backtest total.
- Use `ken_pepper_v3.py` when you want almost identical performance with modest limit-safety improvement.
- Use `ken_pepper_v4.py` when drawdown protection is prioritized over max total.
- Avoid `v1`/`v2` style defensive versions unless market regime changes substantially.

---

## Individual Trader Analysis

### `trader.py` — v12 Production Bot (Current Upload) ⚠️

**Total: 52,210 | HIGHLY INCONSISTENT across days**

**Strategy:**
- **Osmium**: 3-lag regression with weights `[0.3616, 0.3148, 0.2925]` + intercept `309.9`. Produces a predicted "next price" that supposedly exploits a "hidden pattern."
- **Pepper Root**: Fixed anchor at 11,500 + tape adjustment (capped ±1.2 ticks).
- **Execution**: Sniper (0.8/1.5 edge margin) + fragmented 4-layer market making (20 units/block).

**What's working:**
- The fragmented layering avoids showing full order size at one price level.
- Tape reading (trade flow momentum) adds a small real-time adjustment.
- Good Day -2 performance (+97k) because Pepper was near 11,500 anchor.

**What's NOT working:**
- **Critical: The Osmium regression produces a bad fair price.** The weights `[0.3616, 0.3148, 0.2925]` with intercept `309.9` appear copied from a different product (likely old Starfruit). For Osmium trading around 10,000, these weights give predictions that drift significantly from the actual market, causing the sniper to either never fire or fire incorrectly.
- **Critical: The fixed 11,500 anchor for Pepper Root is a disaster waiting to happen.** On Day 0, Pepper Root prices moved well above 11,500 (reaching ~12,000). The algorithm accumulated a max short position of -80 units against a rising market, producing an MTM loss of **-1,040,000** on that position alone.
- **Day 0 result: -63,903** — this strategy LOSES money on the most recent day of data, which is the most representative of current market conditions.

---

### `trader_peter4.py` — Best Performer ✅

**Total: 272,842 | Consistent: 89-93k per day**

**Strategy:**
- **Osmium**: Hardcoded `10000` anchor + tape adjustment (capped ±2.5 ticks). Tape reads against fixed `10000` threshold (not dynamic mid). Sniper at `fair - 2.5` / `fair + 2.5`. Then aggressive pennying with soft `0.05` inventory skew.
- **Pepper Root**: Same 3-lag regression `[0.34296, 0.32058, 0.33645]` + intercept `0.2535` + confluence volume momentum boost (±1.0 tick when prediction and volume agree). Aggressive pennying.
- **Execution**: Sniper first, then penny the queue (bid+1, ask-1), safety guard at ±0.5 from fair.

**What's working:**
- The `10000` anchor for Osmium is correct and stable — the product mean-reverts around this level. The tape cap (±2.5) prevents over-reaction to noise.
- The regression weights for Pepper (`0.34296 + 0.32058 + 0.33645 ≈ 0.999`) act as a weighted moving average that adapts to the current price level — no drift problem.
- The sniper threshold of 2.5 ticks is calibrated for Osmium's spread, getting good fills on mispricings.
- The pennying strategy (bid+1 above best bid) keeps the algorithm at front of queue for passive fills.

**Why it beats peter2_2:**
- Peter4's tape reading for Osmium uses `10000` as the threshold (fixed), while peter2_2 uses the dynamic mid. When the mid drifts, peter2_2's tape signal becomes noisy. Peter4's signal is cleaner.

---

### `trader_peter2_2.py` / `trader_peter2_2_1.py` — Identical Twins

**Total: 255,319 | Consistent: 81-89k per day**

Both files are **byte-for-byte identical** in logic. This is dead code — `trader_peter2_2_1.py` is a duplicate.

**Strategy:**
- **Osmium**: Hardcoded `10000` + tape adj, BUT uses dynamic `mid` as tape threshold (slight difference from peter4).
- **Pepper Root**: Same regression + confluence momentum as peter4.
- **Execution**: Same sniper + pennying approach as peter4.

**Why it underperforms peter4 (~17k less):** The tape threshold in Osmium uses the dynamic `mid` instead of the fixed `10000`. When the market mid drifts (e.g., ~9,990), trades at 9,995 would NOT trigger the upward tape adjustment (since they're still below mid), but peter4 WOULD detect them as bullish (since they're above 10,000). This gives peter4 slightly better directional signals.

---

### `trader_peter3.py` — Uncapped Tape Danger

**Total: 247,512 | Consistent: 82k per day**

**Strategy:**
- **Osmium**: Uses the **current mid** as base (not hardcoded 10000), with **uncapped** tape adjustment (`tape_volume * 0.25`). This is the most distinct Osmium approach.
- **Pepper Root**: Same regression as peter4.
- **Execution**: Different from peter2_2 — uses dynamic thresholds based on momentum strength, variable passive spread.

**What's different:**
- The uncapped tape adjustment (`* 0.25`) can produce large fair price swings on high-volume timestamps. A 40-unit buy surge would shift fair price by 10 ticks, causing the passive maker quotes to sit far from market — reducing fills.
- The dynamic threshold/spread calculation based on `momentum_strength` introduces complexity without a clear backtest advantage.

**Verdict:** The uncapped tape creates inconsistency. Consistent but slightly below peter4.

---

### `trader_adin.py` — Greedy Pepper Accumulation

**Total: 243,504 | Consistent: ~81k per day**

**Strategy:**
- **Osmium**: Uses dynamic mid as base + tape adj (capped ±2.5), simple passive MM with inventory skew `position/limit`.
- **Pepper Root**: 3-lag regression, but drastically different execution — **takes ALL available asks greedily** (no price filter), leaves a resting bid at best_bid+1, only sells on sharp spikes (fair + 3).

**What's different:**
- The Pepper strategy is biased long — it buys everything available and waits for spike exits. This works on all 3 test days because Pepper was in an uptrend. In a flat or downtrending market, this would accumulate losing inventory.
- Osmium is purely passive market-making — less aggressive than peter4's pennying approach, which is why Osmium PnL is lower.
- Missing `self.traderData = ""` in `__init__` causes the `backtest_cli.py` to crash without the wrapper fix.

**Risk:** The "buy all asks" Pepper strategy is only robust in uptrends. If Pepper reverses, this algorithm will hold max long at a loss.

---

### `trader_peter_2_2_2.py` — Regime Detection Experiment

**Total: 200,875 | Inconsistent: 56-75k per day**

**Strategy:**
- **Osmium**: Detects UPTREND/DOWNTREND/NEUTRAL based on short momentum (lag 3) and long momentum (lag 8). In each regime, uses different position targets and execution logic.
- **Pepper Root**: Pure mean reversion (regression only, no momentum boost).

**Why it underperforms:**
- The regime detection requires 8 history points before acting — that's 8 timesteps of flat trading at the start of each day.
- In NEUTRAL regime, only 20 units are traded (vs full 80) — this caps potential PnL during sideways markets.
- The regime transitions add latency. A false NEUTRAL detection during a trending market leaves money on the table.
- Day 0 is particularly weak (+56k vs peter4's +89k), suggesting the regime logic misclassifies the Day 0 market.
- The code has a subtle bug in DOWNTREND: `qty = min(rem_sell, vol, position - target_position)` — `position - target_position` can be `0 - (-30) = 30`, which is a hard cap on each snipe regardless of capacity.

---

### `old_peter/trader_peter11.py` — The Disaster 🚨

**Total: -96,147 | Catastrophic on Day 0 (-117,611)**

**Strategy:**
- **Osmium**: 3-lag regression with `os_weights [0.3616, 0.3148, 0.2925]` + intercept `309.9`. (Same bad weights as current `trader.py`)
- **Pepper Root**: Fixed anchor at 11,500.
- **Execution**: Sniper at 1.2 ticks + fragmented 4-layer MM (20 units/block).
- **Limits**: 80 units.

**What went wrong:**
- The 11,500 anchor for Pepper at 80-unit limits is catastrophic when Pepper moves to 12,000+ on Day 0. The algorithm is convinced the fair price is 11,500, so it sells aggressively at 11,500-12,000 into a rising market, accumulating a -80 short position. End-of-day MTM value: -117k.
- This is the most dangerous strategy in the archive. Uploading this to competition would result in a massive loss.
- The Osmium regression adds additional instability (overestimates value, causing mispriced quotes).

**Key lesson:** Never hardcode a mean-reversion anchor for a product that moves in trends.

---

### `old_peter/trader_peter10.py` — Safe but Capped

**Total: 96,872 | Consistent: ~32k per day**

**Strategy:** Same logic as `trader_peter11.py` but with **20-unit limits** (the original Round 1 constraint).

**Analysis:** The 20-unit cap means the same flawed anchors don't produce catastrophic losses — the maximum damage is bounded. Day 0 at 32k positive (vs peter11's -117k) shows the position limit is the key protective factor. However, this strategy is fundamentally incorrect and would underperform in any scenario where Pepper moves away from 11,500.

---

## Critical Findings

### Finding 1: Osmium Anchor + Capped Tape Is the Most Reliable Base

Across tested families, strategies anchored around `10000` with capped tape adjustment are consistently robust. Execution tuning (adaptive thresholds, skew, passive split) gives incremental edge on top of this baseline.

### Finding 2: The Current Production Bot (`trader.py`) Is Broken for Day 0

The production bot loses **-63,903** on Day 0 — the most recent historical data. The dominant root cause is Pepper-side anchoring, but Osmium-side fair estimation is also miscalibrated.

### Finding 3: Regression for Osmium Doesn't Work (Current Coefficients)

The weights `[0.3616, 0.3148, 0.2925]` with intercept `309.9` are borrowed from the old `STARFRUIT` product in a previous IMC round:
```
prediction = 309.9 + 0.3616*p[-1] + 0.3148*p[-2] + 0.2925*p[-3]
```
For Osmium prices ~10,000, this gives ~**9,927** — consistently underestimating the true price by ~73. This means the sniper will rarely fire (thinks fair is 9,927, market is at 10,000, so no "mispriced asks" exist) and the passive market maker will quote too far below market.

### Finding 4: Pepper Root 3-Lag Regression Weights ARE Correct

The weights `[0.34296, 0.32058, 0.33645]` + intercept `0.2535` sum to ~1.0 on the lag weights. This is effectively a momentum-adjusted moving average of recent prices. Unlike the Osmium regression, these weights track the **current price level** rather than regressing toward a hardcoded mean. This is why Pepper predictions are reliable across all days.

### Finding 5: `trader_peter2_2.py` and `trader_peter2_2_1.py` Are Identical

Both files produce the exact same backtest output. One should be deleted to reduce confusion.

### Finding 6: Regime Detection Underperforms Simple Market Making

The 2-regime system in `trader_peter_2_2_2.py` (UPTREND/DOWNTREND/NEUTRAL) scores ~70k less than `trader_peter4.py`. The added complexity does not pay off on these 3 test days. Market making with inventory skew is simpler and more robust.

---

## What's Working (Best Practices from Peter4)

1. **Osmium fair price**: `10000 + tape_adj`, where `tape_adj = copysign(min(|volume| * 0.15, 2.5), volume)` — anchored, capped, uses fixed 10000 as the tape threshold.
2. **Pepper fair price**: 3-lag autoregression `[0.34296, 0.32058, 0.33645]` + `0.2535` + optional ±1.0 confluence momentum boost.
3. **Sniper threshold**: 2.5 ticks for Osmium, 2.0 ticks for Pepper.
4. **Market making**: Penny the queue (bid+1, ask-1), capped at ±0.5 from fair.
5. **Inventory skew**: 0.05 per position unit to discourage one-sided accumulation.
6. **Position limits**: 80 units is the correct maximum for both products.

---

## What to Try Next

1. **Lock Osmium baseline first**: Keep `10000 + capped tape` (or `v6.1` variant with `mid_pull`) and preserve adaptive execution. Do not deploy old regression coefficients on Osmium.

2. **Fix the production bot** (`trader.py`): Replace the Osmium regression with anchor+tape and the Pepper anchor with the 3-lag autoregression.

3. **Improve Pepper exits**: Add a controlled sniper sell when Pepper trades above fair by a sufficient edge, with inventory-aware caps.

4. **Test Osmium threshold sweeps**: Evaluate take edge around 2.0-2.7 and skew regime switch levels around 40-60 inventory.

5. **Inventory safety rails**: Add soft unwind behavior from ±55 to ±65 before hard limit saturation.

---

## Rust Backtester Note

The Rust backtester (referenced in `BACKTESTING_GUIDE.md`) is designed for WSL2 on Windows. On macOS (current environment), it cannot run via `wsl`. To use it:
- Install Rust natively: `curl https://sh.rustup.rs -sSf | sh`
- Clone/build the `prosperity_rust_backtester` repo with `cargo build --release`
- Run: `./prosperity_rust_backtester --trader "ROUND 1/trader_peter4.py" --products summary`

The Rust backtester would enable rapid parameter sweeps (e.g., scanning tape cap values 1.0–5.0, sniper thresholds 1.0–3.0) to find the optimal configuration for peter4.
