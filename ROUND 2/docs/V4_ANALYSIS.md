# V4 Analysis + MAF Bid Decision

## V4 Changes
- **bid() = 50** (Market Access Fee bid, conservative)
- **Liquidity-scaled taking**: PEPPER take_per_tick × 1.2 if depth > 80, × 0.8 if dry
- **Passive scaling**: +15% passive size when book deep
- **Osmium opportunistic taker**: 2nd pass at edge-1 when book deep (pos < ±40)

## Backtest (split per data_handling_rules.md)

| Split | Days | v2 | v4 | Δ |
|---|---|---|---|---|
| **TRAIN** | R1 d-2,-1,0 | 244,382 | 244,154 | -228 |
| **VAL** | R2 d-1 | 83,852 | 83,748 | -104 |
| **TEST** [readonly] | R2 d0,1 | 155,502 | 154,900 | -602 |

→ V4 **slightly worse** in backtest (~-100/day).

## Why V4 Underperforms Here

Backtest runs **80% quotes, no extra access**. V4's liquidity-scaling triggers rarely hit (depth < 80 often). Opportunistic paths add no edge vs v2's base logic.

**But** real R2 with extra access = 125% quotes. V4's adaptive scaling **would** scale take when extra quotes appear. Backtest can't measure this.

## MAF Bid Decision

### Situation
- Budget: 173k. Need: 200k. Gap: **27k**
- Backtest baseline (v2): 80.6k/day × 3 days = **242k** (no access)
- Plus manual challenge (x=15,y=43,z=42 @ cost 50k): +170-220k
- Total expected **without** access: ~342-362k

### Extra Access Value
25% more quotes → ~10-15% PnL lift (position-cap bound on PEPPER, higher on OSMIUM):
- PEPPER: +3-5k/day × 3 = **+9-15k**
- OSMIUM: +1-2k/day × 3 = **+3-6k**
- **Total lift: +12-21k over round**

### Bid Math
- Cost if accepted: only the bid amount (one-time)
- Cost if rejected: 0
- Asymmetric: bid is **free option** below breakeven

### Game Theory
- Top 50% of bidders → need to beat median
- Many teams skip bid (risk aversion, budget pressure) → low median likely
- Strong bidders bid 500-2000 → tail
- Wiki hint: "*save a lot of XIRECs by bidding less*" → median is low

### Recommended: **BID 50**
- Very likely top 50% (most who bid will skip or bid <50)
- Cost vs gain: 50 vs 12-21k = **240-420× ROI**
- Even if median is 100+, worst case = miss access, cost 0

### Alternative: BID 100 (safer)
- Higher chance of making top 50%
- Cost vs gain: 100 vs 12-21k = **120-210× ROI**
- Still trivial cost on 173k budget

### Skip bid? **NO**
- Forgoes +12-21k closing 50-75% of 27k budget gap
- Downside of bid 50 is ≤50 XIREcs
- Clear asymmetric positive EV

## Final Plan

| Item | Value |
|---|---|
| Deploy trader | **v2** (best backtest) w/ `def bid(self): return 50` added |
| Manual challenge | x=15, y=43, z=42 (cost 50k) |
| MAF bid | **50** |
| Expected auto PnL (3-day) | 242k |
| Expected +access lift | +12-21k |
| Expected manual PnL | 170-220k |
| **Total expected** | **424-483k** |
| Budget use | 50k manual + 50 MAF = 50,050 |
| Remaining after round | 173k - 50k - 0-50 = 122.95k (if bid accepted) |

## Why Not Deploy V4?

V4 worse in backtest (~-300 over 3 days). Liquidity-scaling doesn't trigger on 80% quote data. **Better strategy: bolt bid() onto v2** (proven PnL) rather than untested v4 behavior.

### Action
Add to v2:
```python
def bid(self):
    return 50
```

**Deploy v2+bid. Skip v4.**

## Data Integrity
- Test set (R2 d0, R2 d1) observed but NOT used for tuning choice above
- Decision based on train (R1) + val (R2 d-1) only
- V4 tuning reviewed on val, rejected
