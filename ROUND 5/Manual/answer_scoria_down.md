# Answer — "Scoria Down" (skip Scoria) — Round 5 Manual

**Use this answer if you believe Scoria will go DOWN or are unsure.**

This file is the v5 base with one change: **drops Scoria entirely.** Skipping protects against being wrong on a weak directional read while still losing nothing if Scoria does drop (we just don't capture the profit).

## TL;DR vs v5

| Good | v5 | **v6** | Reason |
|---|---|---|---|
| Scoria paste | Sell 5% | **SKIP** | Signal too weak; fee 2,500 burns expected return |
| (everything else) | unchanged | unchanged | v5 sizing is well-calibrated |

## Math foundation (same as v4 / v5)

Budget `B = 1,000,000`. For allocation `x%` and expected directional move `r` (decimal):
- Fee = `100·x²`
- Net = `100·x·(100r − x)`
- Per-good optimum: `x* = 50r`
- Net at optimum: `25·(100r)²`

Optimum is reachable so long as `Σ x*_i ≤ 100`.

## Final orders

| Tradable Good        | Buy/Sell | Percentage |
|:---------------------|:---------|-----------:|
| Obsidian cutlery     | Sell     |        10% |
| Pyroflex cells       | Sell     |         8% |
| Thermalite core      | Buy      |        14% |
| Lava cake            | Sell     |        14% |
| Magma ink            | Buy      |         6% |
| Scoria paste         | —        |         0% |
| Ashes of the Phoenix | Sell     |         8% |
| Volcanic incense     | Sell     |         6% |
| Sulfur reactor       | Buy      |        10% |

**Total allocated: 76%.**

## Why drop Scoria (key disagreement with v5)

v5's thesis: "Scoria = Volcanic, both hype, both fade."

**This conflates two different setups:**

| Article | Price already moved? | Product fundamentals |
|---|---|---|
| Volcanic incense | YES — "extended rally", "accelerated buying concentrated within narrow time windows" | Hype/discretionary |
| Scoria paste | NO — only D. Ray's *call to action* | Industrial staple ("paste that keeps Ignith together") |

**Volcanic incense:** A pump is *in progress*; fading a confirmed rally is high-EV.
**Scoria paste:** A pump has been *attempted*, not confirmed in price. Plus, Scoria has genuine industrial demand providing a price floor.

The compare-and-contrast argues these are the same trade because both authors share an archetype (hype influencer). But the mechanical setup is different:
- Fade-of-confirmed-pump (Volcanic): well-defined trade
- Pre-emptive contrarian (Scoria): bet against a not-yet-realized pump on a product with fundamentals → noisy signal

### EV math for Scoria SELL @ 5%

- Fee = 2,500 (guaranteed cost)
- For E[net] > 0 we need:
  - P(direction right) ≥ 0.65, AND
  - |r| ≥ 0.12

Both conditions weakly supported by article alone. Skipping kills a coin-flip and saves 2,500.

A small **BUY** has the same problem in reverse. Either way, conviction is too low to justify the fee. **Best move = skip.**

## Per-good reasoning (final)

| Good | Dir | % | Why |
|---|---|---|---|
| Obsidian cutlery | Sell | 10 | Production halted at one facility, contamination protocols, evacuation. Not yet industry-wide → r ≈ 0.20 → x* = 10. |
| Pyroflex cells | Sell | 8 | Tax cut ends tomorrow → effective levy doubles. Partially anticipatable → x* ≈ 8 (r ≈ 0.16). |
| Thermalite core | Buy | 14 | Users 1.43M → 3.09M, 16h42m daily use. Strongest bull. r ≈ 0.28. |
| Lava cake | Sell | 14 | Actual lava found → sales halt + lawsuits. Strongest bear. r ≈ 0.28. |
| Magma ink | Buy | 6 | Launched yesterday — partly priced in. r ≈ 0.12. |
| Scoria paste | SKIP | 0 | Signal too weak; fundamentals provide floor; pump not confirmed in price. |
| Ashes of the Phoenix | Sell | 8 | Public outcry, but company defended → sentiment-only. r ≈ 0.16. |
| Volcanic incense | Sell | 6 | Pump pattern observed in price action. Fade. r ≈ 0.12 (timing risk discount). |
| Sulfur reactor | Buy | 10 | Index inclusion → mechanical buying ahead of rebalance. r ≈ 0.20. |

## Fee table

| Good             |  % | Fee = 100·x² |
|:-----------------|---:|-------------:|
| Obsidian         | 10 |       10,000 |
| Pyroflex         |  8 |        6,400 |
| Thermalite       | 14 |       19,600 |
| Lava cake        | 14 |       19,600 |
| Magma ink        |  6 |        3,600 |
| Scoria           |  0 |            0 |
| Ashes            |  8 |        6,400 |
| Volcanic         |  6 |        3,600 |
| Sulfur           | 10 |       10,000 |
| **Total**        | **76** |    **79,200** |

vs v5: **−2,500** in guaranteed fees and removes one coin-flip trade.
vs v4: **−12,300** in guaranteed fees + flips Scoria from a contested BUY to a clean abstain.

## Caveats / risks

- **Scoria genuinely pumps anyway**: we miss profit, but no downside. Acceptable miss given low conviction.
- **Sulfur rebalance "later this cycle"**: if cycle is longer than a day, fund buying may not hit before our hold expires. Accepting that risk at 10% — the announcement itself often moves price ahead of mechanical flow.
- **Magma ink pop already captured**: launch was yesterday; we may be late. Sized small (6%).
- **Pyroflex tax already priced in**: announcement is public. Sized at 8% acknowledging partial anticipation.
- **24% unused budget**: zero opportunity cost (unused = expires worthless), and avoids fee tax on weak signals.

## Bottom line

**v5 > v4** on robustness, fee discipline, and Sulfur sizing.
**v6 = v5 minus Scoria** — single highest-EV improvement is removing the Scoria trade. Saves 2,500 in fees and removes a 50/50 directional bet from the portfolio.
