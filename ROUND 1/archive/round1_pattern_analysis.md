# Round 1 Pattern Analysis — INTARIAN_PEPPER_ROOT & ASH_COATED_OSMIUM

**TL;DR** — The two Round 1 products behave completely differently and require
opposite strategies. Any "unified" approach (like v5's dual EMA market-maker
for both) structurally underperforms.

| Product                | True nature                          | Right play                                |
| :--------------------- | :----------------------------------- | :---------------------------------------- |
| `INTARIAN_PEPPER_ROOT` | Deterministic upward drift ~$1k/day  | Accumulate long, hold to close            |
| `ASH_COATED_OSMIUM`    | Hard anchor at 10,000, ~16-tick spread | Classic Resin-style market-making around 10k |

---

## 1. PEPPER_ROOT — the drift product

Raw mid prices (first tick vs last tick) over the 3 IMC historical days:

| Day  | Open    | Close    | Drift   | Min    | Max    | Std    |
| :--- | :------ | :------- | :------ | :----- | :----- | :----- |
| -2   | 9,998.5 | 11,001.5 | +1,003  | 9,998  | 11,002 | 287.92 |
| -1   | 10,998.5| 11,998.0 | +999.5  | 10,998 | 12,001 | 287.62 |
| 0    | 11,998.5| 13,000.0 | +1,001.5| 11,998 | 13,000 | 288.18 |

Every day gains almost exactly $1,000. Day N opens essentially where Day N-1
closed (there is no overnight mean-reversion).

### Monotonicity

| Window  | % up   | Mean return (ticks/step) |
| :------ | :----- | :----------------------- |
| 10 ticks  | 75 %   | +1.08 |
| 50 ticks  | 98 %   | +5.42 |
| 200 ticks | **100 %** | +21.7 |

Intraday quartile means on Day −2: **10,126 → 10,376 → 10,626 → 10,874**.
Perfectly linear — +250 per quarter, every quarter, every day.

### Why v5 loses money here

v5 uses `EMA(8)` as fair value and quotes symmetrically around it. On a
trend of +1.08 ticks/step, the EMA lags by ~8 ticks. That means v5's ask
is always ~8 ticks **below** the near-future real price, so the bot bids
fire into ticks that lift through the quote. Net: v5 is short the drift.
This is why Day −1 comes out at **−$2,948** despite trading ~hundreds of
times.

### Correct strategy

Never short. Buy up to the position limit (we use 40 in `_safe`, 80 in
`_agg`). Hold. At ~$1,000 drift × position, end-of-day mark-to-market is
`position × entry_edge + drift × position`. Even a clumsy entry around
mid gives `+80 × $500 = $40,000`; a clean entry near the day open gives
closer to `+80 × $1,000 = $80,000`.

The one regime this fails in: a reversed or flat drift day. The `_safe`
variant adds a cheap slope-guard (stop accumulating and flatten if the
last-20-step slope turns negative for 5 consecutive ticks). The `_agg`
variant accepts this tail risk for the higher expected value.

---

## 2. OSMIUM — the Resin clone

| Day  | Open    | Close   | Std   | Min    | Max    |
| :--- | :------ | :------ | :---- | :----- | :----- |
| -2   | 10,000  | 9,993.5 | 4.73  | 9,984  | 10,012 |
| -1   | 9,992   | 10,002  | 3.83  | 9,986  | 10,014 |
| 0    | 10,003  | 10,007  | 5.22  | 9,982  | 10,018 |

The price doesn't drift, doesn't trend, doesn't evolve. It sits at
10,000 ± ~5 ticks for the whole day.

### Book shape

| Day  | % bids < 10,000 | % asks > 10,000 | Median spread | % spread ≥ 4 |
| :--- | :-------------- | :-------------- | :------------ | :----------- |
| -2   | 97 %            | 88 %            | 16            | 100 %        |
| -1   | 95 %            | 97 %            | 16            | 100 %        |
| 0    | 88 %            | 94 %            | 16            | 100 %        |

Most-visited bid levels are 9988, 9989, 9986; most-visited ask levels
are 10005, 10009, 10010. The book literally forms a wall around 10,000.

### Correct strategy

Treat 10,000 as gospel (Timo Diehm's "WallMid"-style constant fair).

- **Take** anything ≤ 9998 on the ask, ≥ 10002 on the bid (2-tick edge).
- **Make** at 9999 / 10001 (pennying inside best bid/ask but never
  crossing the anchor). With a 16-tick resting spread and a 1-tick quote
  width, every fill is ~8 ticks of edge.
- **Flatten** large inventories at the anchor itself.

No EMA, no tape signal, no trend skew. The tape-contrarian adjustment in
v5 adds noise: trade counts on Osmium are 400-500/day with sizes 2-10 —
too small and too noisy to derive a fair-value correction.

---

## 3. The two-variant split (v6_safe / v6_agg)

| Knob                        | v6_safe           | v6_agg           |
| :-------------------------- | :---------------- | :--------------- |
| Pepper max long             | 40                | 80               |
| Pepper slope stop           | yes (5 neg ticks) | no               |
| Osmium take-edge            | 2 ticks           | 1 tick           |
| Osmium front-quote size     | 20                | 30               |
| Osmium inventory-skew start | `|pos| > 40`      | `|pos| > 20`     |
| Osmium flatten threshold    | `|pos| > 60`      | `|pos| > 60`     |

`_safe` is designed to never blow up on synthetic scenarios. `_agg` is
designed to maximize mean PnL on the real Prosperity 4 data, accepting
that a reversed-drift scenario will hurt.

---

## 4. What this replaces in v5

Dropped because they either add no signal or hurt on the current products:

- Dual-EMA (8/40) trend skew on Pepper → drift is deterministic, no indicator needed
- Tape contrarian signal on Osmium → noise, the anchor is the signal
- EMA(30) anchor on Osmium → loses to the true constant 10,000
- Range-volatility adaptive width → spread is already stably 16 ticks
- Second-level bid on Pepper → we want to accumulate volume, not save 1 tick of entry
