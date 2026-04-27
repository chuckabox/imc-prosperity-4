## Raw-data-first Round 4 findings

This note was produced from the Round 4 raw CSVs first, without using the existing Round 4 findings docs as research input.

### What stands out from the raw data

- `HYDROGEL_PACK`
  - Strongest **clean mean-reversion** profile.
  - Large excursions relative to spread.
  - Best short-horizon conditional edge in the raw scan.

- `VELVETFRUIT_EXTRACT`
  - Not purely mean-reverting.
  - Day 3 early session is much closer to **sell-the-open / downtrend**, then rebound.
  - Days 1-2 also show an early drop, but weaker than day 3.

- `VEV_*`
  - `VEV_4000` / `VEV_4500`: mostly intrinsic + wide spread; more MM than directional.
  - `VEV_5200` / `VEV_5300` / `VEV_5400`: biggest directional response to VFE moves.
  - In day 3 first 10%, they all decay sharply along with VFE.

### Manual trade blotter from raw mid-price paths

#### Day 3, first 10% (`timestamp <= 100000`)

- **`VELVETFRUIT_EXTRACT` short**
  - Sell around `5300.0 @ 8300`
  - Cover around `5244.5 @ 43100`
  - Mid-path edge: `+55.5 / unit`
  - Why: opening strength fails immediately; clean early down-leg.

- **`VEV_5000` short**
  - Sell around `301.5 @ 8300`
  - Cover around `247.0 @ 43000`
  - Mid-path edge: `+54.5 / unit`
  - Why: strongest liquid voucher response to VFE early selloff.

- **`VEV_5200` short**
  - Sell around `122.5 @ 8100`
  - Cover around `83.5 @ 86400`
  - Mid-path edge: `+39.0 / unit`
  - Why: premium compresses hard when VFE softens.

- **`VEV_5300` short**
  - Sell around `60.5 @ 8300`
  - Cover around `36.0 @ 43000`
  - Mid-path edge: `+24.5 / unit`
  - Why: same opening decay pattern, slightly lower beta than `VEV_5000`.

- **`HYDROGEL_PACK` long**
  - Buy around `9993.0 @ 10900`
  - Sell around `10061.0 @ 60300`
  - Mid-path edge: `+68.0 / unit`
  - Why: classic early mean reversion after weak open.

#### Full-day swing structure

- **Day 1**
  - Early drop then rebound.
  - Big full-day trough around `~651500`, rebound into `~733900`.
- **Day 2**
  - Same broad shape, shifted slightly later.
  - Big trough around `~744200`, rebound into `~997900`.
- **Day 3**
  - Opening selloff is the cleanest directional opportunity.

### Candidate alphas

- **Alpha 1: HP mean reversion**
  - Trade `HYDROGEL_PACK` symmetrically around rolling fair.
  - Best raw conditional edge of the products.

- **Alpha 2: VFE opening weakness**
  - First 5-10% of day often opens near a local high, especially day 3.
  - Better modeled as a directional short than as symmetric MM.

- **Alpha 3: Mid-strike voucher beta**
  - `VEV_5000`, `VEV_5200`, `VEV_5300`, `VEV_5400` are the best directional amplifiers of VFE.

- **Alpha 4: Deep ITM voucher spread capture**
  - `VEV_4000`, `VEV_4500` mostly behave like intrinsic value with wide spread.
  - Better for cautious MM than for directional bets.

- **Alpha 5: Tape identity signal**
  - Repeating names (`Mark 01`, `Mark 14`, `Mark 38`, `Mark 49`, etc.) are not neutral.
  - Some counterparties correlate with weaker/stronger short-term forward returns.
  - Useful as a skew input, not strong enough alone.

### What the IMC-style simulator actually rewarded

- Large aggressive directional grabs did **not** convert well in `prosperity4bt`.
- The best-performing tested family was still **small-clip passive MM** with modest take-edge logic.
- Best current executable candidate from this session:
  - File: `ROUND 4/traders/quant_scaled_shelf.py`
  - `prosperity4bt` full-day results:
    - Day 1: `+14,126`
    - Day 2: `+4,728`
    - Day 3: `+10,575`
    - Total: `+29,429`
  - Day 3 first 10%:
    - `+1,624`

### Conclusion

- The **raw manual path** suggests much larger opportunity than the simulator realizes.
- The gap is mostly **execution realism**: visible depth + tape matching reduce how much of the mid-path move is actually capturable.
- Best next step is either:
  - keep improving passive execution around the same alphas, or
  - explicitly accept that the `20k` first-10%-ticks target looks **too high for the current matching model** and optimize for the best executable PnL instead.

