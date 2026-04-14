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

| Strategy         | Total PnL    | Day -2  | Day -1  | Day 0   | Profile                      |
| :--------------- | :----------- | :------ | :------ | :------ | :--------------------------- |
| **Layered MM**   | **+$49,618** | +$18.2k | +$12.9k | +$18.4k | **Aggressive / High Volume** |
| **Simple Penny** | **+$24,418** | +$2.6k  | +$16.3k | +$5.4k  | Conservative / Maker-focused |
| **Fixed Anchor** | **-$86,657** | -$21.7k | -$26.2k | -$38.6k | High Risk / Drift Victim     |

---

## 🔍 Strategy deep-dives

### 🥈 1. `trader_peter.py` ($3,177 Baseline)

- **Strategy**: **Layered Market Making**.
- **Logic**: EMA tracking. Stable but slow.

### 🥇 2. `trader_peter2.py` ($3,340 Leader)

- **Strategy**: **3-Lag Regression Scalping**.
- **Logic**: Linear model ($Next\_Price \approx 0.34P_t + 0.32P_{t-1} + 0.33P_{t-2}$).
- **Verdict**: Still the most robust setup.

### 🥈 5. `trader_peter5.py` ($3,200 Balanced Risk)

### 🥈 8. `trader_peter8.py` ($3,200 Micro-Price)

- **Strategy**: **Passive Micro-Price**.
- **Logic**: 3-Lag Micro-price regression weights.
- **Verdict**: Proven stable, but in Round 1, the **Mid-price** actually provides a cleaner signal for mean reversion than the noisier Micro-price.

---

## 🛠️ Next Target: Use "Defense" to hit 10k

The leaderboard gap between 3.3k and 10k is likely about **Volume Capture**. If our regression is correct, we should be quoting **Full Size** at the predicted fair price. Version 9 will focus on **Size Escalation**.
