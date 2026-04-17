# Peter Strategy Evolution Report
## Objective: Hardening the Sniper logic for Round 1

This report preserves the performance history of the "Peter" bot lineage across 46 robust datasets and 6 sync-mutated stress tests.

### 📊 Comparative Performance Matrix

| Version | Mean PnL | Win Rate | Max Drawdown | Robustness (Stress) | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **v2c** | $687,211 | 100% | $3,800 | 0/100 | **LEGACY (Conservative)** |
| **v2d** | **$703,244** | **100%** | **$2,100** | 12/100 | **CHAMPION (Maximum PnL)** |
| **v2e** | $401,952 | 92% | $18,400 | 45/100 | **STABLE (Mean Reversion)** |
| **v2f** | $32,694 | 61% | $470,711 | **88/100** | **ROBUST (Crash Tested)** |

---

### 🔍 Deep Dive: The "Alpha vs. Robustness" Trade-off

#### 👑 The Champion: Trader Peter v2d
- **Logic**: Combines an Elite Pepper Sniper with a Momentum-fading logic on Osmium.
- **Why it works**: It treats the 10,000.0 Osmium anchor as "God's Truth." It never doubts the peg, allowing it to capture every single tick of deviation as profit.
- **Risk**: If the IMC server ever actually moves the Osmium peg to 11,000, v2d will blow up by trying to "Short" the entire move.

#### 🛡️ The Guardian: Trader Peter v2f
- **Logic**: Uses an **Elastic Anchor** (EMA 20 + EMA 100).
- **Why it works**: In the "Stress Lab," when we randomly shuffled price segments (creating 500-tick gaps), v2f was the only bot that survived. It "saw" the gap and adjusted its anchor within 20 ticks.
- **Trade-off**: In standard markets, it is "too smart." It treats minor noise as a permanent price shift, missing out on mean-reversion profits.

### 🚀 Final Recommendation
For the **actual competition submission**, we recommend **`trader_peter_v2d.py`**. 
The Round 1 datasets are notoriously stable. Betting on the 10,000 anchor has historically yielded the highest Sharpe ratio. 

Use **`v2f`** only if you expect "Black Swan" events or permanent regime shifts during the live trading window.
