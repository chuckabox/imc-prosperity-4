# Peter's Round 1 Trader Evolution — v6_safe → v13

This document captures the design reasoning, fragility analysis, and knob
progression across Peter's Round 1 traders. Every version is a direct
evolution of a specific predecessor with a documented rationale for each
change. Companion to `round1_pattern_analysis.md`.

---

## 1. The two products (recap)

| Product              | Nature                                   | Correct play                         |
| :------------------- | :--------------------------------------- | :----------------------------------- |
| `INTARIAN_PEPPER_ROOT` | Deterministic ~$1k/day upward drift      | Accumulate long, cap, hold           |
| `ASH_COATED_OSMIUM`  | Hard anchor at 10,000 ± ~5 ticks         | Resin-style MM around 10,000         |

Every Round 1 strategy lives or dies on (a) capturing the Pepper drift
without being short, and (b) not bleeding on Osmium when the anchor
misbehaves or one-sided flow arrives.

---

## 2. Ken's lineage (reference points)

Peter evolves against Ken's versions — each solves a specific problem:

| Version       | Pepper cap | Pepper slope-stop  | Osmium take-edge | Osmium quotes | Key idea                              |
| :------------ | :--------- | :----------------- | :--------------- | :------------ | :------------------------------------ |
| `ken_v6_safe` | 40         | 5-neg-streak       | 2                | 20 / 15       | Safe defaults; survive reversed drift |
| `ken_v6_agg`  | 80         | none               | 1                | 30 / 20       | Maximise drift capture, accept tail   |
| `ken_v6b`     | 60         | 5-neg-streak       | 1                | 25 / 18       | "Safe's brain, agg's ambition"        |
| `ken_v6c`     | **adaptive** 0/30/60/80 | 5-neg-streak | 1 | 25 / 18 | **Drift-adaptive warmup measurement** |

Ken's v6c — "our best trader absolutely" — introduced the regime-adaptive
cap: measure realised drift during a 2,000-tick warmup, then pick the
Pepper cap that matches (Strong → 80, Moderate → 60, Weak → 30,
Negative → 0). This is the single highest-leverage idea in the Round 1
codebase and Peter's subsequent versions all build on it.

---

## 3. Peter's lineage

### v6_safe — "stability-first refinement of ken_v6_safe"

Improvements over `ken_v6_safe`, each addressing a concrete fragility:

Pepper:
- **Magnitude-based slope guard** (drop ≥ 8 over 20-tick window) vs ken's
  consecutive-negative-streak. Streak trips on normal drift noise.
- **Recovery** if drift clearly resumes. Ken's stop is permanent.
- **Adaptive max-long**: 20 → 40 only after 30 confirmed positive-slope ticks.
- **Passive bid cap** of 10 to limit adverse fills on downspikes.
- **Tighter take**: `ask <= mid` (no `+1` buffer).
- **Chunked flatten** when stopped.

Osmium:
- **Anchor sanity**: halve quote sizes if 20-tick median drifts > 6 from 10k.
- **Graduated 3-tier skew** (0 / 1 / 2 at |pos| > 25 / 50) vs ken's binary.
- **Toxic-flow throttle**: skip takes when last-tick tape shows ≥ 40 lots
  of one-sided aggression.
- **Earlier flatten** (55 vs 60), smaller quotes (15/10 vs 20/15).
- **Hard clamp**: quotes never more than ±4 from anchor.
- Take edge 3 (vs 2) for fewer toxic fills.

### v10_safe — "ken_v6b's upside mechanics + v6_safe's guardrails"

`ken_v6b` raised mean PnL via (a) gradual `PEPPER_ADD_PER_TICK` accumulation
spreading entry cost across ticks, and (b) tighter Osmium take-edge (1 tick)
with larger quotes (25/18). But v6b kept v6_safe's brittle streak-stop and
had no adverse-flow protection.

v10_safe **preserves** v6b's two PnL unlocks and **replaces** its three
winrate killers:
- Magnitude stop + 2-tick hysteresis + recovery (fixes false streak trips).
- Toxic-flow gate (fixes TAKE_EDGE=1 adverse-fill bleed).
- Anchor-sanity half-scaling (fixes bleed on anchor-drift regimes).

Knobs: cap ramps 30 → 60 after 20 confirmed ticks, `TAKE_PER_TICK` 5→10,
magnitude stop `-8` with hysteresis=2, recovery `+5`, flatten chunk 15.
Osmium: take-edge 1, quotes 22/15, skew at 22/45, flatten 55, clamp ±4.

### v6d — "ken_v6c's regime-picking + v10_safe's guardrails"

Analysing `ken_v6c` surfaced five fragilities; v6d fixes each while
preserving the adaptive cap innovation:

| # | Fragility in v6c                                             | v6d fix                                                                           |
| - | :----------------------------------------------------------- | :-------------------------------------------------------------------------------- |
| 1 | Slope uses raw first-mid vs current — one outlier biases     | **Smooth both endpoints**: median of first 30 vs median of last 30 samples       |
| 2 | Cap locked after warmup — late-session drift stays at low cap | **Upgrade-only re-eval** every 5,000 ticks after warmup                          |
| 3 | Streak-based slope stop (brittle + permanent)                | **Magnitude stop (-8) + 2-tick hysteresis + recovery (+5)**                      |
| 4 | Take `ask <= mid+1` + uncapped passive                       | Take only at `ask <= mid`; passive capped at 10                                  |
| 5 | Osmium: edge 1 + 25-lot quotes + binary skew + no clamp      | Toxic-flow gate; anchor-sanity halving; 3-tier skew at 22/45; ±4 clamp; flatten 55 |

Warmup shortened 2000 → 1500 ticks (smoothing lets us decide earlier with
equal confidence). Tentative cap 20 / add-per-tick 5 during warmup so we
participate conservatively rather than idle.

### v11 — "Aggressive by Default, Safe by Exception"

Explicit goal: match ken_v6c's ~$78k PnL while retaining v6d's guardrails.

Five targeted loosenings on v6d, each a pragmatic concession:

| Knob                  | v6d         | v11         | Rationale                                             |
| :-------------------- | :---------- | :---------- | :---------------------------------------------------- |
| Pepper take           | `ask <= mid` | `ask <= mid + 1` | "Pay-to-play" — tight take misses trend fills     |
| `PEPPER_PASSIVE_CAP`  | 10          | **40**      | Build position 4x faster on stable windows           |
| `PEPPER_STOP_THRESHOLD` | -8        | **-12**     | Relax so minor pullbacks don't false-trigger         |
| Osmium front / second | 22 / 15     | **25 / 18** | Match v6c's edge capture                              |
| Strong-drift cap      | 80          | 80          | Already correct; restated                             |

All v6d guardrails retained intact.

**Note on v11's passive bug**: the intent "4x faster passive" didn't
materialise — `tick_budget = min(rem_cap, add_per_tick=10)` meant passive
could never exceed 10. v12 fixes this.

### v12 — "six targeted leaks in v11"

| # | Fix                                    | v11 behaviour                                       | v12 behaviour                                                        |
| - | :------------------------------------- | :-------------------------------------------------- | :------------------------------------------------------------------- |
| 1 | **Separate take & passive budgets**    | `PASSIVE_CAP=40` never bound (tick_budget dominates) | Take budget (10/15) and 40-lot passive are independent              |
| 2 | **STRONG regime accelerates**          | 10 take/tick at cap 80                              | 15 take/tick at cap 80 (fills in ~6 ticks vs ~8)                    |
| 3 | **Fast-track cap commit**              | Wait full 1500-ts warmup                            | At 700 ts + 10 samples, slope ≥ 0.10 commits cap 80 early           |
| 4 | **First-tick-of-stop flatten**         | Uniform 15/tick on stop                             | 30 on trigger tick, 15/tick after                                    |
| 5 | **Directional toxic gate**             | Blocks both sides on one-sided tape                 | Buyers-dominant → skip buys, keep selling into their bids           |
| 6 | **Adaptive Osmium take-edge**          | `edge=1` always                                     | `edge=2` while anchor-off — more edge demanded when fair is uncertain |

### v13 — "regime-aware at every decision point"

Five regime-aware upgrades on v12:

| # | Fix                                | v12                                    | v13                                                            |
| - | :--------------------------------- | :------------------------------------- | :------------------------------------------------------------- |
| 1 | **Adaptive stop threshold**        | Flat `-12` for all regimes             | STRONG `-16/+7`, MOD `-12/+5`, WEAK `-8/+4`                    |
| 2 | **Fast-track also promotes MODERATE** | Only commits STRONG at 700 ts        | MODERATE commits early too (slope ≥ 0.04)                      |
| 3 | **Inside-spread passive in STRONG** | All passive at `bb+1`                 | Split 50/50 across `bb+1` and `ba-1` when spread ≥ 3           |
| 4 | **First-tick flatten 30 → 40**     | 30 on trigger tick                     | 40 on trigger tick — halves exposure after the signal confirms  |
| 5 | **Position-asymmetric take-edge**  | `edge=1` both sides                    | `buy_edge = base + pos//30`, `sell_edge = base + (-pos)//30`    |

---

## 4. Design principles crystallised from the evolution

1. **Smoothing beats single-point measurement.** v6c's raw `(mid - start_mid) / elapsed`
   can be biased by one noisy tick. v6d's median-of-30-samples is robust
   with the same warmup length.

2. **Safety layers compose multiplicatively, not additively.** Skew + flatten
   + asymmetric edge + anchor-sanity all pushing the same direction (unwind
   position, avoid bad fills) means no single mechanism has to be heavy-handed.

3. **Directional signals deserve directional responses.** The v11 toxic-flow
   gate blocked both sides; v12's directional gate preserves the *profitable*
   leg of one-sided flow while cutting the adverse one.

4. **Regime-aware thresholds beat flat defaults.** v13's stop threshold
   scales with the measured cap (STRONG drift tolerates deeper pullbacks
   because the drift signal is real; WEAK regime tightens to limit damage).

5. **Recovery is as important as stopping.** Ken's streak-stop is permanent
   — one noise trip kills the day. Peter's magnitude stop + resume threshold
   lets drift resumption reactivate accumulation.

6. **Upgrade-only re-eval avoids whiplash.** v6d's mid-session cap re-eval
   only raises; the magnitude stop handles the downside cleanly. This
   separation of concerns (cap = regime commitment, stop = circuit breaker)
   is cleaner than a single "dynamic cap" that fights itself.

7. **The passive budget and take budget are semantically different.** v11's
   bug (tick_budget dominating passive cap) came from treating them as one
   number. v12 separates them: take = crossing-spread budget, passive =
   resting-bid budget, both bounded by `rem_cap`.

---

## 5. Knob reference — v6d through v13

Pepper:

| Knob                           | v6d     | v11     | v12       | v13                        |
| :----------------------------- | :------ | :------ | :-------- | :------------------------- |
| Warmup ticks                   | 1500    | 1500    | 1500      | 1500                       |
| Fast-track ticks               | —       | —       | 700       | 700                        |
| Fast-track slope               | —       | —       | 0.10      | 0.10 (STRONG) / 0.04 (MOD) |
| Smooth samples                 | 30      | 30      | 15        | 15                         |
| Re-eval interval               | 5000    | 5000    | 5000      | 5000                       |
| Slope tiers                    | 0.06 / 0.02 / -0.02 | same | same | same                |
| Cap tiers                      | 80 / 60 / 30 / 0    | same | same | same                |
| Tentative cap                  | 20      | 20      | 20        | 20                         |
| Take/tick (normal / strong)    | 10 / —  | 10 / —  | 10 / 15   | 10 / 15                    |
| Passive cap (actually binding) | 10      | 10 *    | 40        | 40                         |
| Stop threshold                 | -8      | -12     | -12       | -16 / -12 / -8 (regime)    |
| Hysteresis                     | 2       | 2       | 2         | 2                          |
| Resume threshold               | +5      | +5      | +5        | +7 / +5 / +4 (regime)      |
| Flatten first / chunk          | — / 15  | — / 15  | 30 / 15   | 40 / 15                    |
| Inside-spread passive in STRONG | no     | no      | no        | **yes** (spread ≥ 3)       |

\* v11's `PASSIVE_CAP=40` was nominally set but didn't bind due to budget bug.

Osmium:

| Knob                       | v6d  | v11   | v12         | v13                              |
| :------------------------- | :--- | :---- | :---------- | :------------------------------- |
| Anchor                     | 10k  | 10k   | 10k         | 10k                              |
| Take-edge (normal / unsafe) | 1 / —  | 1 / — | 1 / 2     | 1 / 2 + `pos//30` asymmetric     |
| Front / second quote       | 22/15 | 25/18 | 25/18       | 25/18                            |
| Skew tiers (soft / hard)   | 22 / 45 | 22 / 45 | 22 / 45 | 22 / 45                          |
| Flatten                    | 55    | 55   | 55          | 55                               |
| Anchor drift threshold / ticks | 6 / 20 | 6 / 20 | 6 / 20 | 6 / 20                           |
| Toxic-flow volume          | 40    | 40    | 40          | 40                               |
| Toxic-flow directionality  | both sides | both sides | **directional** | directional                 |
| Clamp ± from anchor        | 4     | 4    | 4           | 4                                |

---

## 6. Open questions for future versions

- **End-of-day liquidation**: currently we hold 80 long Pepper to close
  and mark-to-market at final mid. Is there value in a forced-flatten in
  the last N ticks to crystallise gains? (Probably not under IMC MTM rules.)
- **Osmium fair blending**: when anchor-off, should fair shift toward
  recent median (e.g., 0.7×10k + 0.3×recent_median) rather than just
  shrinking quote sizes? Risk: chases a bad signal.
- **Cross-product correlation**: is there signal in Osmium order-book
  imbalance that predicts Pepper tick direction, or vice versa? Not yet
  investigated.
- **Slippage modelling**: local robust backtests show $500k+ PnL; real
  portal delivers $2-15k. Our current fill assumptions likely overstate
  passive-fill rates. Live paper trading needed before sizing knobs further.
