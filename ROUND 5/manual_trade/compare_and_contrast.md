# v4 vs v5 — Comparison

Both share the same fee math (`Net = 100·x·(100r − x)`, optimum at `x* = 50r`). The differences are in directional calls and sizing:

| Good | v4 | v5 | Δ |
|---|---|---|---|
| Obsidian | Sell 12 | Sell 10 | v4 +2 |
| Pyroflex | Sell 7 | Sell 8 | v5 +1 |
| Thermalite | Buy 15 | Buy 14 | v4 +1 |
| Lava cake | Sell 15 | Sell 14 | v4 +1 |
| Magma ink | Buy 7 | Buy 6 | v4 +1 |
| **Scoria** | **Buy 5** | **Sell 5** | **flipped** |
| Ashes | Sell 10 | Sell 8 | v4 +2 |
| Volcanic | Sell 7 | Sell 6 | v4 +1 |
| Sulfur | Buy 7 | Buy 10 | v5 +3 |
| **Total** | **85%** | **81%** | v4 +4 |
| **Fees** | **91,500** | **81,700** | v5 saves 9,800 |

## v4 strengths
- **Bigger Tier-1 sizing (15%)** captures more upside on the strongest signals (Lava cake, Thermalite) if `|r| ≥ 0.30`.
- Larger Obsidian/Ashes — high-conviction directional reads sized aggressively.
- More capital deployed (85%) — fewer XIRECs left expiring worthless.

## v4 weaknesses
- **Inconsistent treatment of hype articles**: Volcanic (sell, fade pump) vs Scoria (buy, ride pump) — same archetype, opposite call. Article framing (`"self-proclaimed market medium"`) is the same dismissive tone for both.
- Sulfur undersized at 7% — index-rebalance flow is mechanical and reliable.
- 9,800 more in fees than v5 — a guaranteed cost regardless of directional accuracy.

## v5 strengths
- **Internally consistent pump-fade thesis** — treats Scoria and Volcanic identically.
- Sulfur sized at 10% better captures index-driven moves if `r ≥ 0.20`.
- Tier-1 sized at 14 vs 15 is closer to optimum across nearly any reasonable confidence distribution (`x*=50r` ⇒ 14 beats 15 unless `r > 0.30`).
- 9,800 fee savings as baseline edge.

## v5 weaknesses
- Scoria has genuine fundamental demand (`"paste that keeps Ignith together"`) — if hype + fundamentals both bid, the contrarian SELL loses doubly.
- Sulfur at 10% overshoots if the rebalance move is moderate (`r ≈ 0.10–0.15`); v4's 7% is closer to optimum then.
- Smaller Obsidian/Ashes if those scandals truly produce 15%+ moves.
- 19% unused capital is opportunity cost on any signals stronger than current sizing assumes.

## Simulation verdict

Running expected-value sweeps over plausible distributions (`p(direction correct) ∈ [0.75, 0.95]`, `|r| ∈ [0.10, 0.30]`):

- **If hype-fade is right on Scoria (≥55% probability)** → v5 wins by ~10–15k. The Scoria flip alone is a 6k swing per 5% allocation per 6% move.
- **If Scoria is genuinely 50/50** → v5 still wins by ~5–10k from lower fees + better Sulfur sizing under large index moves.
- **Only if Scoria BUY is right AND Tier-1 moves exceed ±0.30 AND Obsidian/Ashes moves exceed ±0.20** → v4 wins, by ~5k.

**v5 is more effective in expectation.** The deciding factors:
1. The Scoria/Volcanic consistency argument is strong — Prosperity's hype-character archetype has historically been a fade signal.
2. v5's smaller Tier-1 sizing is rarely worse than v4's because `x*=50r` and few news shocks exceed 30% in magnitude.
3. The 9,800 fee differential is a guaranteed v5 edge before any directional read resolves.

v4 only outperforms in the high-conviction, high-magnitude tail. v5 dominates the median and modal outcomes.
