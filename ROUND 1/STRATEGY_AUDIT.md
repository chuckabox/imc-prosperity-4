# 📊 Round 1 Strategy Audit: Scylla vs Charybdis

# trader_peter.py ![3,177 PNL](image.png)
# trader_peter2.py ![3,340 PNL](image-1.png)
# trader_peter3.py ![3,100 PNL](image-2.png)
# trader_peter4.py ![3,248 PNL](image-3.png)
# trader_peter5.py ![3,200 PNL](image-4.png)
# trader_peter6.py ![300 PNL](image-5.png)
# trader_peter7.py ![WIPE OUT](image-6.png)
# trader_peter8.py ![3,200 PNL](image-5.png)

---

## 🏁 Summary Table (Original Audit)

| Strategy         | Total PnL (Backtest) | Day -2  | Day -1  | Day 0   | Profile                      |
| :--------------- | :----------- | :------ | :------ | :------ | :--------------------------- |
| **Layered MM**   | **+$49,618** | +$18.2k | +$12.9k | +$18.4k | **Aggressive / High Volume** |
| **Simple Penny** | **+$24,418** | +$2.6k  | +$16.3k | +$5.4k  | Conservative / Maker-focused |
| **Fixed Anchor** | **-$86,657** | -$21.7k | -$26.2k | -$38.6k | High Risk / Drift Victim     |

---

## 🔍 Strategy Deep-Dives

### 🥉 1. `trader_peter.py` ($3,177 Baseline)
- **Concept**: EMA-based Mean Reversion.
- **Verdict**: Solid starter bot, but too slow to react to Starfruit price shifts.

### 🥇 2. `trader_peter2.py` ($3,340 Leader)
- **Concept**: **3-Lag Regression**.
- **Logic**: Linear prediction using weighted history $[0.34, 0.32, 0.33]$.
- **Verdict**: **The Gold Standard**. Best stability-to-profit ratio.

### 🥈 3. `trader_peter3.py` ($3,100 Layered)
- **Concept**: **Multi-Layer Market Making**.
- **Logic**: Spread limit into 3 price levels (50/30/20).
- **Verdict**: Underperformed v2. Added layers increased probability of getting filled on "Toxic" drifts.

### 🥈 4. `trader_peter4.py` ($3,248 Alpha Sniper)
- **Concept**: **Micro-price + Sniper Take**.
- **Logic**: Aggressively hits mispriced orders using book imbalance.
- **Verdict**: Strong contender. Captures alpha missing from passive bots.

### 🥈 5. `trader_peter5.py` ($3,200 High-Aggression)
- **Concept**: **Zero-Buffer Sniper**.
- **Logic**: Lowered thresholds to 0.1 for high-frequency capture.
- **Verdict**: Good volume, but higher adverse selection.

### 💀 6. `trader_peter6.py` ($300 The Crash)
- **Concept**: **Leader-Spec Risk**.
- **Logic**: Reduced skew to 0.1 to hold max positions (±20).
- **Verdict**: **Catastrophic Failure**. Held massive losing positions during drift without a defensive exit.

### 💀 7. `trader_peter7.py` (WIPE OUT)
- **Concept**: **Active Exit Stop-Loss**.
- **Logic**: Market Taking to close positions when price moves against us.
- **Verdict**: **Total Wipeout**. Paid the spread too many times in "Panic Sells."

### 🥈 8. `trader_peter8.py` ($3,200 Refined Leader)
- **Concept**: **Micro-Price Passive**.
- **Logic**: strictly passive quotes using micro-price imbalance signal.
- **Verdict**: Stable and safe, but less profit density than the v2 Mid-Price model.

---

## 🚀 Next Step: Version 9 (Size Escalation)
We are merging the **Stability of v2** with the **Volume Capture of v4**. Version 9 will focus on **Spread Squeezing** to increase our Avg Fill from 5.5 to 6.3.
