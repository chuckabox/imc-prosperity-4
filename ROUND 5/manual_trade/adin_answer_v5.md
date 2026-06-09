# Adin Answer v5 — Round 5 Manual

## Fee math

Budget `B = 1,000,000`. Allocation `x%` per good gives:
- Investment = `10,000 · x`
- Fee = `(x/100)² · B = 100 · x²`
- Gross = `r · 10,000 · x`, where `r` = expected directional move (decimal)
- **Net = `100 · x · (100r − x)`**
- Per-good optimum: **`x* = 50r`** (allocate half the expected move in percentage points)
- Net at optimum: `2,500 · r²` per percentage point of `r`²

So allocations should scale roughly with expected move, and double allocation → quadruples fee. Strong signals only, sized moderately.

## Signal classification

I split the nine articles into three buckets:

**Hard fundamental shocks (highest conviction):**
- *Lava cake* — actual lava in product, sales halted, lawsuits piling, vendors returning stock. Catastrophic. **SELL hard.**
- *Thermalite core* — projected user base 1.43M → 3.09M (>2×), daily use 16h42m. Forecasted demand explosion from a quarterly report. **BUY hard.**

**Mechanical / event-driven (high conviction):**
- *Sulfur reactor* — added to Elemental Index 118 → index funds mechanically buy at rebalance. **BUY.**
- *Pyroflex cells* — tax cut ends *tomorrow*, effective levy doubles. Article frames it as abrupt → not fully priced. **SELL.**
- *Obsidian cutlery* — manufacturing halted, contamination protocols, evacuation, industry-wide implications. **SELL.**

**Sentiment / PR (moderate conviction):**
- *Ashes of the Phoenix* — resurfaced video, public outcry. Company's "birds are immortal" defense limits damage but sentiment drops first. **SELL.**
- *Magma ink* — limited-edition launch, 6+ hour queues, "hot drop", post-merger product. Real demand event. **BUY.**

**Influencer pumps (contrarian):**
- *Volcanic incense* — "accelerated buying concentrated within narrow time windows coinciding with Nostralico's public appearances." Textbook pump pattern with retail piling in. **SELL** (fade the pump).
- *Scoria paste* — Lava D. Ray, dismissively framed as "self-proclaimed market medium" speaking during her "streaming marathon," urges stockpiling. Same archetype as Nostralico. The dismissive framing is the tell. **SELL** (contrarian on hype, smaller size since Scoria has real industrial demand).

The key call vs. v4 is treating **Scoria Paste as a SELL**, not a BUY. Both Lava D. Ray and Whiff Nostralico are hype characters — and the Ashflow Alpha author signals skepticism on D. Ray's credibility ("self-proclaimed", "streaming marathon"). Treating one as a pump-fade and the other as a buy is inconsistent. Fade both.

## Final orders

| Tradable Good        | Buy/Sell | Percentage |
|:---------------------|:---------|-----------:|
| Obsidian cutlery     | Sell     |        10% |
| Pyroflex cells       | Sell     |         8% |
| Thermalite core      | Buy      |        14% |
| Lava cake            | Sell     |        14% |
| Magma ink            | Buy      |         6% |
| Scoria paste         | Sell     |         5% |
| Ashes of the Phoenix | Sell     |         8% |
| Volcanic incense     | Sell     |         6% |
| Sulfur reactor       | Buy      |        10% |

**Total allocated: 81%** (19% intentionally unused — fee curve punishes weak-signal sizing more than it rewards leftover capital).

## Fee table

| Good             |  % | Fee = 100·x² |
|:-----------------|---:|-------------:|
| Obsidian         | 10 |       10,000 |
| Pyroflex         |  8 |        6,400 |
| Thermalite       | 14 |       19,600 |
| Lava cake        | 14 |       19,600 |
| Magma ink        |  6 |        3,600 |
| Scoria           |  5 |        2,500 |
| Ashes            |  8 |        6,400 |
| Volcanic         |  6 |        3,600 |
| Sulfur           | 10 |       10,000 |
| **Total**        | **81** |    **81,700** |

Total fees ≈ 8.2% of budget — the price of expressing nine independent directional views.

## Sizing logic

Sizes are tiered by conviction, not just direction:

- **Tier 1 (14%)**: Lava cake, Thermalite — hardest fundamental shocks, signals are explicit and quantified in the article.
- **Tier 2 (10%)**: Obsidian, Sulfur — strong but slightly less clear-cut (Obsidian: how big is the reputational blow? Sulfur: rebalance "later this cycle" — timing could miss the hold).
- **Tier 3 (8%)**: Pyroflex, Ashes — directional but partially anticipatable / partially priced.
- **Tier 4 (5–6%)**: Magma ink (already-launched, hype peak may be at launch), Volcanic (fading a rally — timing risk), Scoria (contrarian on a pump that has real fundamental support — lowest conviction sell).

No single position above 14% — the quadratic fee makes 14%→18% cost an extra 6,400 in fees for marginal signal strength.

## What I'd watch for as risk

- **Sulfur timing**: if the rebalance is more than one trading day away, the index buying may not hit before our hold expires. Sized smaller than ideal because of this.
- **Magma ink already up**: launch happened "yesterday" per the article, so we may be buying after the initial pop. Kept small.
- **Scoria contrarian**: the call relies on the fundamental ("paste that keeps Ignith together") being insufficient to offset hype reversal. If hype dominates and fundamentals add a floor, we lose moderately. Sized smallest of the sells for this reason.
- **Pyroflex priced in**: announcement is public. Sized at 8% rather than 12% in case the move is partially absorbed.
