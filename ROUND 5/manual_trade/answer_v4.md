# Answer v4 — Round 5 Manual

## Math foundation

Budget = 1,000,000 XIRECs. Fee per good = `(pct/100)² × budget = pct² × 100`.

For expected % price move `p` in our favor, allocation `x%`:
- Gross PnL = `100·x·p`
- Fee = `100·x²`
- **Net = `100·x·(p − x)`**
- Optimum: **`x* = p/2`** (allocate half the expected move)
- Net@optimum = `25·p²`

If `Σ(p_i / 2) ≤ 100`, the unconstrained per-good optimum is reachable.

## Final orders

| Tradable Good        | Buy/Sell | Percentage |
|:---------------------|:---------|:-----------|
| Obsidian cutlery     | Sell     | 12%        |
| Pyroflex cells       | Sell     | 7%         |
| Thermalite core      | Buy      | 15%        |
| Lava cake            | Sell     | 15%        |
| Magma ink            | Buy      | 7%         |
| Scoria paste         | Buy      | 5%         |
| Ashes of the Phoenix | Sell     | 10%        |
| Volcanic incense     | Sell     | 7%         |
| Sulfur reactor       | Buy      | 7%         |

**Total allocated: 85%** (15% unused — leaving headroom rather than over-sizing weak signals).

## Per-good reasoning

| Good | Dir | % | Why |
|---|---|---|---|
| Obsidian cutlery | Sell | 12 | Production halted, contamination protocols, evacuation. Industry experts warn about implications for other facilities. Hard bearish. |
| Pyroflex cells | Sell | 7 | Tax cut ends tomorrow → effective levy doubles. Demand will slow, upgrade cycles disrupted. May be partly priced in → smaller size. |
| Thermalite core | Buy | 15 | Active users 1.43M → 3.09M (>2x). 16h42m daily use shows sustained demand. Strongest bull signal of the board. |
| Lava cake | Sell | 15 | Actual lava found in product. Sales halted, lawsuits piling, vendors returning stock with lawyer letters. Strongest bear signal. |
| Magma ink | Buy | 7 | Limited-edition launch with 6h+ queues, "hot drop" hype, merger backing. Bullish but already-launched event → modest size. |
| Scoria paste | Buy | 5 | Influencer pump (Lava D. Ray) + genuine fundamentals ("paste that keeps Ignith together"). Article tone skeptical of influencer, so trim size. |
| Ashes of the Phoenix | Sell | 10 | Resurfaced video → public outcry. Brand damage despite company's "birds are immortal" defense. Sentiment-driven drop likely. |
| Volcanic incense | Sell | 7 | Textbook pump pattern: "accelerated buying concentrated within narrow time windows coinciding with Nostralico's public appearances." Pump→dump reversal play. |
| Sulfur reactor | Buy | 7 | Added to Elemental Index 118 → forced buying by index-tracking funds at next rebalance. Mechanical bid. |

## Expected outcome

If price-move estimates are right:
- **Gross profit:** ~174,600 XIRECs
- **Total fees:** ~91,500 XIRECs (sum of `pct² × 100` across all 9 entries: 14400+4900+22500+22500+4900+2500+10000+4900+4900 = 91,500)
- **Expected net:** ~83,100 XIRECs

Fee math:
| Good | % | Fee |
|---|---|---|
| Obsidian | 12 | 14,400 |
| Pyroflex | 7 | 4,900 |
| Thermalite | 15 | 22,500 |
| Lava cake | 15 | 22,500 |
| Magma ink | 7 | 4,900 |
| Scoria | 5 | 2,500 |
| Ashes | 10 | 10,000 |
| Volcanic | 7 | 4,900 |
| Sulfur | 7 | 4,900 |
| **Total** | **85** | **91,500** |

## Risk notes

- Fee structure punishes concentration quadratically — that's why no single position exceeds 15%.
- Two pump goods (Scoria, Volcanic incense) sized smallest — direction read could be wrong on either if pump persists past hold period.
- Pyroflex sized small relative to its bearish read because tax announcement may already be priced in by close.
- 15% budget left unused — better than over-sizing weak conviction trades (would just pay extra fees).
