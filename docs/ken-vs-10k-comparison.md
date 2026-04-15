# Round 1 Strategy Comparison

This document compares:

- `ken v6.1` vs `trader_10k`
- `ken v2` vs `trader_10k`
- `ken v2` vs `ken v6.1`

## Reference Results (local eval_trader)

| Trader | Day -2 | Day -1 | Day 0 | Total |
|---|---:|---:|---:|---:|
| `trader_ken_v6_1.py` | 100480.00 | 101713.00 | 99288.00 | **301481.00** |
| `trader_ken_v2.py` | 90885.00 | 92362.00 | 89595.00 | 272842.00 |
| `trader_10k.py` | 90885.00 | 92362.00 | 89595.00 | 272842.00 |

## 1) `ken v6.1` vs `trader_10k`

| Factor | `trader_10k` | `ken v6.1` | Practical Impact |
|---|---|---|---|
| Osmium fair model | `10000 + tape_adj` | `10000 + tape_adj + mid_pull` | `v6.1` tracks drift around anchor better |
| Tape sensitivity | `0.15`, cap `2.5` | `0.185`, cap `3.0` | `v6.1` reacts faster to flow |
| Take threshold | Fixed `2.5` | Adaptive (`2.25`/`2.65` + inventory penalty) | Better behavior in tight/wide spreads |
| Inventory skew | Fixed `0.05` | `0.05` normally, `0.085` when stretched | Faster de-risk at large positions |
| Passive sizing | One level, full remaining size | Two levels (~62/38 split) | More robust queue/fill behavior |
| Local total | 272842.00 | **301481.00** | `v6.1` clearly stronger in this harness |

## 2) `ken v2` vs `trader_10k`

| Factor | `trader_10k` | `ken v2` | Practical Impact |
|---|---|---|---|
| Osmium fair model | `10000 + tape_adj` | `10000 + tape_adj` | Equivalent |
| Tape sensitivity | `0.15`, cap `2.5` | `0.15`, cap `2.5` | Equivalent |
| Take threshold | Fixed `2.5` | Fixed `2.5` | Equivalent |
| Inventory skew | Fixed `0.05` | Fixed `0.05` | Equivalent |
| Passive sizing | One level | One level | Equivalent |
| Local total | 272842.00 | 272842.00 | Equivalent in local eval |

## 3) `ken v2` vs `ken v6.1`

| Factor | `ken v2` | `ken v6.1` | Practical Impact |
|---|---|---|---|
| Osmium fair model | Anchor + tape | Anchor + tape + `mid_pull` | `v6.1` better drift capture |
| Tape sensitivity | `0.15`, cap `2.5` | `0.185`, cap `3.0` | `v6.1` is more responsive |
| Take threshold | Fixed `2.5` | Spread-aware + inventory-aware | Better selectivity in `v6.1` |
| Inventory skew | Fixed `0.05` | Dynamic (`0.05`/`0.085`) | Better risk control in `v6.1` |
| Passive sizing | Single-level | Two-level split | Better fill distribution in `v6.1` |
| Local total | 272842.00 | **301481.00** | `v6.1` outperforms |

## Recommendation

- Use `ken v6.1` as the current production baseline.
- Treat `ken v2` and `trader_10k` as equivalent baselines for regression checks.
- If tuning further, keep `v6.1` Osmium execution structure and optimize parameters around it.
