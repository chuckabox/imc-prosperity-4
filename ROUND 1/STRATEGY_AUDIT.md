# 📊 Round 1 Strategy Audit: Scylla vs Charybdis

Documenting the evolution of Round 1 strategies. Target: Maximize PnL by optimizing fair value models for Amethysts and Starfruit.

---

## 🏁 Performance Summary
| File | Total PnL (3 Days) | Day -2 | Day -1 | Day 0 | Primary Logic |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `trader_peter.py` | **$56,554** | $17,040 | $23,823 | $15,691 | EMA + 10k Anchor |
| **`trader_peter2.py`** | **$78,170** | **$26,615** | **$29,089** | **$22,466** | **3-Lag Regression** |

---

## 🔍 Strategy Deep-Dives

### 🥈 1. `trader_peter.py` (Leaderboard Baseline)
*   **Concept**: Standard mean reversion using basic filters.
*   **Starfruit Logic**: Fair price is calculated using an **EMA (Alpha 0.15)**. It filters out short-term noise but lags during rapid price shifts.
*   **Amethyst Logic**: Fixed fair price at **10,000**.
*   **Pros**: Highly stable and proven in previous years.
*   **Cons**: Lags behind trends in Starfruit, leading to "toxic" fills when the price drifts before returning.

### 🥇 2. `trader_peter2.py` (Regression Enhanced)
*   **Concept**: Predictive market making using statistical lag analysis.
*   **Starfruit Logic**: Uses a **3-Lag Linear Regression** ($Next\_Price = 0.25 + 0.34P_t + 0.32P_{t-1} + 0.33P_{t-2}$). This weights the last three prices almost equally to predict the very next tick.
*   **Amethyst Logic**: Fixed **10,000 anchor** with tightened market-making bands and optimized inventory skewing (0.3).
*   **Pros**: Significantly higher capture rate on Starfruit price moves. Better inventory control prevents holding large losing positions during drifts.
*   **Cons**: Requires historical state management (history of last 3 prices).

---

## 🛠️ Audit Conclusion
The transition from EMA to Multi-Lag Regression in `trader_peter2.py` yielded a **+38% increase in PnL**. This suggests that Starfruit in Round 1 behaves like a short-memory process where recent price actions are highly predictive of the immediate future.

**Current Recommendation**: Deploy `trader_peter2.py` as the primary production bot.
