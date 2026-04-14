# 📊 Round 1 Strategy Audit: Scylla vs Charybdis

# trader_peter.py ![3,177 PNL](image.png)
# trader_peter2.py ![3,340 PNL](image-1.png)
# trader_peter3.py ![3,100 PNL](image-2.png)
# trader_peter4.py ![3,248 PNL](image-3.png)
# trader_peter5.py ![3,200 PNL](image-4.png)
# trader_peter6.py ![300 PNL](image-5.png)
# trader_peter7.py ![WIPE OUT](image-6.png)
# trader_peter8.py ![3,200 PNL](image-5.png)
# trader_peter10.py ![1,600 PNL](image-10.png)

---

## 🏁 Summary Table (Original Audit)

| Strategy         | Total PnL (Backtest) | Day -2  | Day -1  | Day 0   | Profile                      |
| :--------------- | :------------------- | :------ | :------ | :------ | :--------------------------- |
| **Layered MM**   | **+$49,618**         | +$18.2k | +$12.9k | +$18.4k | **Aggressive / High Volume** |
| **Simple Penny** | **+$24,418**         | +$2.6k  | +$16.3k | +$5.4k  | Conservative / Maker-focused |
| **Fixed Anchor** | **-$86,657**         | -$21.7k | -$26.2k | -$38.6k | High Risk / Drift Victim     |

---

## 🔍 Strategy Deep-Dives

### 🥈 1. `trader_peter.py` ($3,177 Baseline)
- **Concept**: EMA-based Mean Reversion.

### 🥇 2. `trader_peter2.py` ($3,340 Leader)
- **Concept**: **3-Lag Regression**.
- **Verdict**: Proven Signal, but hampered by incorrect 20-unit limits.

### 🥉 10. `trader_peter10.py` ($1,600 - Signal Mismatch)
- **Strategy**: **Tape-Aware Fragmented MM**.
- **Verdict**: **Underperformed (1.6k)**. Post-mortem revealed a "Signal Swap" catastrophe. We applied regression to the "Steady" Pepper Root and anchored the "Volatile" Osmium. Also used incorrect 20-unit limits.

---

## 🚀 Final Round 1 Strategy: Version 11 (XIREC Target)
Based on the official Intarian briefing, we are executing the **Signal Correction**:
1. **Osmium**: 3-Lag Regression (Solving the "Hidden Pattern").
2. **Pepper Root**: 10,000 fixed anchor (The "Steady" root).
3. **Limit Scale**: 80 Units per product.

This update should provide a **4x - 6x multiplier** to our existing leader-PnL.
