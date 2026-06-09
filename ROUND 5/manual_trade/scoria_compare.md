# Scoria Up vs Scoria Down — Compare & Contrast

Two answer files, both built on the v5 base. Only one trade differs: **Scoria paste**.

| File | Scoria position | When this answer wins |
|---|---|---|
| [`answer_scoria_up.md`](answer_scoria_up.md) | **Buy 5%** | If Scoria moves UP > +5% |
| [`answer_scoria_down.md`](answer_scoria_down.md) | **Skip (0%)** | If Scoria moves down OR stays flat (≤ +5%) |

The other 8 trades are identical. Total fee burn:
- `scoria_up`: 81,700
- `scoria_down`: 79,200

---

## The Article

The exact text from `description.md` for Scoria Paste:

> ## LAVA D. RAY SAYS "GLORY DAYS ARE AHEAD" FOR IGNITH ECONOMY, URGES STOCKPILING OF SCORIA PASTE
>
> Lava D. Ray, creative multitalent and self-proclaimed market medium, appeared on BrewTube Live claiming she has studied current market dynamics, "took its temperature" and is confident the Ignith economy will reach an all-time high in the foreseeable future. Speaking during her latest streaming marathon, D. Ray advised households to "stock up on Scoria Paste before it becomes unaffordable," pointing to the compound's central role in daily maintenance across Ignith.
>
> Often referred to as "the paste that keeps Ignith together," Scoria Paste is used extensively in residential repairs and infrastructure upkeep, making it a familiar indicator for household conditions.

### What's actually in the article

| Element | Read |
|---|---|
| **Hard event?** | None — no policy, supply shock, earnings, lawsuit, or scandal |
| **Price action reported?** | None — article does NOT mention any current price movement |
| **Personality endorsement** | Yes — Lava D. Ray on BrewTube Live |
| **Editorial framing** | Skeptical — "self-proclaimed market medium", "took its temperature" (scare-quoted), "streaming marathon" (trivializing) |
| **Product fundamentals** | Real — "central role in daily maintenance", "the paste that keeps Ignith together" |

This is the **only good** in the 9-good lineup with no quantifiable event. Every other article has a hard catalyst (production halt, tax change, user growth, lawsuits, viral video, index inclusion, observed pump pattern, hot-drop launch).

---

## The Two Theses

### `scoria_up` (Buy 5%)

**Logic:**
1. D. Ray's recommendation publicized in the trusted news source itself triggers retail buying.
2. Product has industrial fundamentals → price floor → asymmetric upside.
3. Even if some readers fade the influencer, others follow → net buying pressure.
4. Optimal allocation at r = +0.10 is exactly 5%.

**Article evidence supporting this:**
- D. Ray claims Ignith economy reaches "all-time high" — bullish narrative for industrial staples.
- "Stock up before it becomes unaffordable" — scarcity framing primes buyers.
- "The paste that keeps Ignith together" — author validates the product's importance.
- "Familiar indicator for household conditions" — mainstream awareness, easy to FOMO into.

### `scoria_down` (Skip)

**Logic:**
1. The article gives no observable signal — only a personality endorsement.
2. Editorial tone is dismissive of D. Ray, reducing her credibility as a price catalyst.
3. Without a confirmed price move OR a hard event, both BUY and SELL are coin flips.
4. Skipping saves the 2,500 fee on a low-conviction trade.

**Article evidence supporting this:**
- "self-proclaimed market medium" — author doesn't endorse her credentials.
- "took its temperature" — scare quotes mock her methodology.
- "creative multitalent" — backhanded; she's not a market analyst.
- "streaming marathon" — frames her venue as entertainment, not finance.
- No price action is reported — unlike Volcanic incense ("rally", "accelerated buying"), Scoria's pump is *attempted*, not *observed*.

---

## Side-by-side EV table

Assuming the other 8 trades are identical (both portfolios capture ~79,200 from those):

| Scoria actual move | `scoria_up` net (Buy 5%) | `scoria_down` net (Skip) | Winner |
|---|---:|---:|---|
| +20% | **+7,500** | 0 | scoria_up by 7,500 |
| +15% | **+5,000** | 0 | scoria_up by 5,000 |
| +10% | **+2,500** | 0 | scoria_up by 2,500 |
| +5% | 0 | 0 | tie |
| flat (0%) | −2,500 | **0** | scoria_down by 2,500 |
| −5% | −5,000 | **0** | scoria_down by 5,000 |
| −10% | −7,500 | **0** | scoria_down by 7,500 |
| −15% | −10,000 | **0** | scoria_down by 10,000 |

**Break-even point: Scoria moves +5%.** Anything above → scoria_up wins. Anything below (including flat) → scoria_down wins.

---

## Comparison to v5 (Adin's Sell)

We're not comparing v5 here, but for completeness:

| Scoria actual | v5 (Sell 5%) | scoria_up (Buy 5%) | scoria_down (Skip) | Best |
|---|---:|---:|---:|---|
| +10% | −7,500 | **+2,500** | 0 | scoria_up |
| 0% | −2,500 | −2,500 | **0** | scoria_down |
| −10% | **+2,500** | −7,500 | 0 | v5 |

So:
- **v5 (Sell)** is best only if Scoria drops meaningfully (≥ +5% drop).
- **scoria_up (Buy)** is best if Scoria rises meaningfully (≥ +5% rise).
- **scoria_down (Skip)** is best if Scoria stays flat OR you're uncertain.

---

## Decision criteria

Pick **`scoria_up`** if:
- You read the article as a net positive — the recommendation publicized in a trusted news source matters more than the journalist's tone.
- You think household items get FOMO-bought when "scarcity" framing hits ("before it becomes unaffordable").
- Your subjective P(Scoria > +5%) ≥ 60% AND you expect magnitude ≥ +10%.
- You weigh fundamentals ("paste that keeps Ignith together") as a directional bias.

Pick **`scoria_down`** if:
- You read the journalist's mocking framing as the actual signal.
- You don't trust influencer-driven moves to materialize without observed price action first.
- You'd rather not pay 2,500 in fees to bet on a coin flip.
- You think P(direction right) < 65% on either side.

---

## Quick math reference

For any allocation `x%` and Scoria move `r%` (positive = up):

- **Buy net** = `100·x·(r − x)` if r > 0, or `100·x·(r − x)` (loses when r < 0)
- **Sell net** = `100·x·(−r − x)` (wins when r < 0)
- **Skip net** = 0
- **Fee** = `100·x²` (always, regardless of direction)

At x = 5%:
- Fee always = 2,500
- Need |r| > 5% (in correct direction) just to break even on the 2,500 fee
