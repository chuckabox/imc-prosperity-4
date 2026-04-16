# Intarian Exchange Auction — Trade Analysis

## The Question

As a special welcoming event, the Intarians are organizing an exchange auction. You will have access to two stale order books: one for Dryland Flax and one for Ember Mushroom. You can put in one order per tradable good. When the auction clears, it will execute with price-time priority and there will be no more continuous trading to partake in. How might you turn this celebratory opportunity into profit?

---

### **Auction rules**

You have to submit a single limit order (price, quantity). When the auction ends, the exchange selects a single clearing price that:

1. maximizes total traded volume, then
2. breaks ties by choosing the higher price.

All bids with price ≥ clearing price and asks with price ≤ clearing price execute at the clearing price. Allocation is price priority, then time priority. Since you are last to submit, you are last in line at any price level you join.

### Guaranteed buyback after the auction

You will not trade these products in continuous trading. Instead, right after the auction the Merchant Guild will buy any inventory you trade at a fixed price:

- `DRYLAND_FLAX`: 30 per unit (no fees)
- `EMBER_MUSHROOM`: 20 per unit (fee: 0.10 per unit traded)

### Submit your orders

Choose a bid price and quantity for each product to maximize your profit. Enter your orders directly in the Manual Challenge Overview window and click the “Submit” button. You can re-submit new orders until the end of the trading round. When the round ends, the last submitted orders will be executed.

## Order Books

### DRYLAND FLAX

> Any Dryland Flax acquired will be sold directly after the auction closes for **30 XIRECs per piece**. No trading fees.

| Side | Volume | Price |
|------|--------|-------|
| BID  | 30k    | 30    |
| BID  | 5k     | 29    |
| BID  | 12k    | 28    |
| BID  | 28k    | 27    |
| ASK  | 40k    | 28    |
| ASK  | 20k    | 31    |
| ASK  | 20k    | 32    |
| ASK  | 30k    | 33    |

---

### EMBER MUSHROOM

> Any Ember Mushroom acquired will be sold directly after the auction closes for **20 XIRECs per piece**. Trading fees: 0.05 XIRECs per unit for buying and 0.05 XIRECs per unit for selling (0.10 total per unit).

| Side | Volume | Price |
|------|--------|-------|
| BID  | 43k    | 20    |
| BID  | 17k    | 19    |
| BID  | 6k     | 18    |
| BID  | 5k     | 17    |
| BID  | 10k    | 16    |
| BID  | 5k     | 15    |
| BID  | 10k    | 14    |
| BID  | 7k     | 13    |
| ASK  | 20k    | 12    |
| ASK  | 25k    | 13    |
| ASK  | 35k    | 14    |
| ASK  | 6k     | 15    |
| ASK  | 5k     | 16    |
| ASK  | 0      | 17    |
| ASK  | 10k    | 18    |
| ASK  | 12k    | 19    |

---

## Reasoning & Strategy

### Core Insight — Arbitrage Opportunity

Both order books present a **risk-free arbitrage**: asks are available at prices below the guaranteed post-auction exit price. The strategy is simply to buy as cheaply as possible and sell at the guaranteed price.

---

### DRYLAND FLAX Analysis

The book has a **crossed market**:
- Best bid: 30 XIRECs
- Best ask: 28 XIRECs

The ask at 28 is below the guaranteed sell price of 30, giving a clear **2 XIREC/unit profit**.

**Profit per unit = 30 (exit price) − 28 (buy price) = 2 XIRECs**

---

### EMBER MUSHROOM Analysis

**Profit formula per unit = 20 (exit price) − buy price − 0.10 (fees)**

All asks priced at 19 or below are profitable:

| Ask Price | Volume | Net Profit/unit | Level Profit | Cumulative Profit |
|-----------|--------|-----------------|-------------|-------------------|
| 12        | 20k    | 7.90            | 158,000     | 158,000           |
| 13        | 25k    | 6.90            | 172,500     | 330,500           |
| 14        | 35k    | 5.90            | 206,500     | 537,000           |
| 15        | 6k     | 4.90            | 29,400      | 566,400           |
| 16        | 5k     | 3.90            | 19,500      | 585,900           |
| 18        | 10k    | 1.90            | 19,000      | 604,900           |
| 19        | 12k    | 0.90            | 10,800      | 615,700           |

Since every level adds positive profit, **more volume always means more total profit** — the optimal strategy is to buy as much volume as possible at the lowest prices.

---

## Volume Constraint Discovery

### Initial Answer (No Volume Cap)

Before volume constraints were known, the optimal order for Ember Mushroom was:

- **BUY 113,000 units at limit 19** — sweeping all profitable ask levels (20k + 25k + 35k + 6k + 5k + 10k + 12k = 113k)
- **BUY 40,000 units of Dryland Flax at limit 28**

### Revised Answer (After Volume Cap Introduced)

A volume cap was then introduced:
- **Dryland Flax: max 30,000 units**
- **Ember Mushroom: max 43,000 units**

With the 43k cap on Ember Mushroom, the optimal approach is to fill the **cheapest ask levels first**:

| Fill   | Volume | Net/unit | Profit  |
|--------|--------|----------|---------|
| @ 12   | 20k    | 7.90     | 158,000 |
| @ 13   | 23k    | 6.90     | 158,700 |
| **Total** | **43k** |       | **316,700** |

Setting the limit at **13 XIRECs** ensures we sweep the 12 and 13 levels only, without risk of filling at higher prices.

### Could Lower Volume or a Different Price Yield More Profit?

No. Since every additional unit purchased at any price ≤ 19 still yields positive profit, **buying the maximum volume at the lowest available prices is always optimal**. Reducing volume or increasing the limit price strictly reduces total profit.

---

## Final Orders

| Instrument     | Side | Price (Limit) | Volume  | Est. Profit     |
|----------------|------|---------------|---------|-----------------|
| Dryland Flax   | BUY  | 28 XIRECs     | 30,000  | 60,000 XIRECs   |
| Ember Mushroom | BUY  | 13 XIRECs     | 43,000  | 316,700 XIRECs  |
| **Total**      |      |               |         | **376,700 XIRECs** |

---

## Key Takeaways

1. **Crossed/mispriced order books** create risk-free arbitrage when a guaranteed exit price exists.
2. **Price-time priority** means setting your limit correctly is critical — too high and you risk overpaying; too low and you miss fills.
3. **Every profitable unit counts** — when all fills are net positive, maximum volume at minimum price is always the optimal strategy.
4. Volume constraints directly cap upside — the jump from 113k to 43k on Ember Mushroom reduced potential profit from ~615,700 to 316,700 XIRECs.