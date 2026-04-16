# 🛡️ Robust Analysis Guide (Round 1)

The **Robust Backtester** is the primary engine for institutional-grade strategy validation in this repository. Unlike basic backtesting which only looks at historical data, the robust analysis stress-tests your strategy against a diverse array of market regimes, real-world normalized data, and synthetic scenarios.

---

## 🏗️ The Core Tool: `robust_backtester.py`

This tool runs your trader against **ALL available data sources** to calculate a true "Robustness Score."

### Usage
```powershell
python "ROUND 1/tools/robust_backtester.py" "ROUND 1/traders/peter/trader_peter_v4.py" [FLAGS]
```

### The 4 Execution Modes
| Command | Mode | Data Sources | Best For |
| :--- | :--- | :--- | :--- |
| **Default** | Full Suite | IMC + Real + Scenarios | Final validation before deployment. |
| **`--imc-only`** | Historical | Days -2, -1, 0 | Quick verification against known past behavior. |
| **`--scenarios-only`** | Stress Test | Synthetic Regimes | Testing edge cases (Flash crashes, Trending, Volatility). |
| **`--quick`** | Smoke Test | Subset of all sources | Rapid iteration after code changes (uses 1 sample per regime). |

---

## 📊 Data Universes Tested

1.  **IMC Historical Data**: The standard "Gold Standard" days provided by the competition.
2.  **Real-World Normalized**: External market data (e.g., historical crypto or equity trends) mapped onto Osmium/Pepper pricing structures.
3.  **Synthetic Scenarios**: Algorithmically generated paths designed to break strategies (Mean Reversion, Strong Drift, High Noise, Low Liquidity).

---

## 📈 Interpreting the Robustness Summary

After the run, the tool outputs a comprehensive distribution. Focus on these **Target Benchmarks**:

| Metric | Pass Threshold | Red Flag (🚩) |
| :--- | :--- | :--- |
| **Mean PnL** | > $10,000 | < $5,000 (Weak Signal) |
| **5th Percentile** | > $0 | < -$5,000 (Fragile) |
| **Win Rate** | > 75% | < 60% (Inconsistent) |
| **Blow-up Rate** | 0.0% | > 1.0% (Risk of Catastrophe) |
| **Worst Drawdown** | < $2,000 | > $5,000 (Over-leveraged) |

---

## 🔄 The Recommended Workflow

1.  **Code Change**: Refine your entry/exit logic.
2.  **Quick Check**: `python tools/robust_backtester.py <trader> --quick`
    *   If any "BLOW UP" markers appear, stop and debug.
3.  **Stress Test**: `python tools/robust_backtester.py <trader> --scenarios-only`
    *   Ensure the strategy survives "Drift" and "High Vol" regimes.
4.  **Full Audit**: `python tools/robust_backtester.py <trader>`
    *   This is the final hurdle. The **Mean PnL** here is your most realistic performance estimate.

---

## ⚠️ Reality Check: Local vs. Live Performance

It is common to see **unrealistically high PnL** (e.g., $500k+) in local robust results. This is often "suspicious" for several reasons:

*   **Fill Model Exploitation**: Many local backtesters use a "Simple Taker" model where your orders are filled instantly if they touch the best opposite price. In the real IMC portal, you are competing with thousands of bots for the same 20-80 units of liquidity.
*   **Zero Market Impact**: Local tests assume you can buy/sell unlimited quantities without moving the market price. In reality, large "Taking" orders cause immediate price reversals against you.
*   **Latency & Slippage**: Local snapshots are static. On the live server, by the time your order arrives, the price has often moved (Slippage), turning a winning "Take" into a losing one.
*   **What is Realistic?**: 
    - **Live Portal**: A top-tier Round 1 bot usually earns **$2,000 – $15,000** per day.
    - **Local Robust**: A **Mean PnL of $10,000 – $30,000** is a very strong, realistic signal. If you see $500,000, your bot is likely "gaming" the drift in the datasets rather than trading a sustainable edge.

---

## 🚩 Robustness Killers (What to Fix)

*   **"BLOW UP" Marker**: The tool flags any scenario where you lose >$10,000. This usually means your position limits aren't being respected or you're "chasing" a price that isn't coming back.
*   **High Std Dev**: If your Mean is $10k but Std Dev is $15k, your strategy is gambling. Tighten your stop-losses or reduce your position skew.
*   **Low Win Rate in "Scenario" Category**: Your strategy might be "overfit" to the 3 IMC days and fails as soon as market dynamics shift.

---

*Goal: Deploy strategies that win in any market, not just the one we've already seen.* 🚀

