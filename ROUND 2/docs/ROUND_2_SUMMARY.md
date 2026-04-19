# Round 2: The Interian Expansion - Trading Specification

This document provides a comprehensive overview of the second trading round on Intara, including new mechanics, asset behaviors, and algorithmic strategies for use as context in development.

## 1. Overview & Qualifiers
*   **Mission:** Final opportunity to reach the threshold of **200,000 XIRECs** before the leaderboard resets for Phase 2.
*   **Status:** Qualifications for the final mission are primary objectives for these first two rounds.
*   **Market State:** Acceleration in trading activity with increased competition for Ash-Coated Osmium and Intarian Pepper Root.

---

## 2. New Strategic Mechanics

### Market Access Fee (MAF)
A "blind auction" mechanism to secure additional market data and liquidity.
*   **Benefit:** Gain access to **25% more order book volume**.
*   **Mechanism:** Top 50% of bidders secure the extra flow.
*   **Outcome - Success:** Pay the bid price, receive 125% total quotes (80% base + 25% extra).
*   **Outcome - Failure:** Pay 0, continue with standard 80% volume allocation.
*   **Implementation:** Incorporate a `bid()` function into the `Trader` class.
*   **Game Theory:** Aim for the "median" bid; overpaying guarantees access but reduces final PnL.

### Growth Pillars
*   **Budget:** 50,000 XIRECs provided by XIREN.
*   **Task:** Distribute budget across three growth pillars to optimize outpost performance.

---

## 3. Asset Analysis & Strategy

### Intarian Pepper Root
*   **Behavior:** Non-stationary "straight-line" logic, adjusted for a **linear trend**.
*   **Observation:** Linear regression on `mid_price` (window ≈ 100 timesteps) yields decent predictive results.
*   **Strategy Insights:** 
    *   Avoid naive "buy as fast as possible" due to high transaction costs.
    *   **Pro Tip (@oats/April):** Significant value capture possible by reacting to the **increasing spread**.
    *   Ideal strategy: Sophisticated Buy and Hold or Trend-Following.

### Ash-Coated Osmium
*   **Behavior:** "Drifting" asset (similar to TOMATOES in tutorials).
*   **Primary Challenge:** Adapt a drift-adjusted mean reversion strategy.
*   **Optimal Approach:** A blend of Market Making (MM), Market Taking (MT) on mispricings, Mean Reversion (MR), and Drift Adjustment.
*   **Community Note:** Finding the perfect "quoting mix" was the main challenge discussed on Discord.

---

## 4. Research & Denoising Techniques
The following techniques showed significant benefit in signal quality:
*   **Mid-Price Backfilling:** Essential during moments with empty order books.
*   **Volume-Weighted Mid-Prices (VWAP):** Utilizing depth across the full order book rather than just the first level.
*   **Order Flow Imbalance:** Adjusting price signals based on significant imbalance periods.

---

## 5. Post-Mortem: Lessons from Previous Failures
> [!WARNING]
> Critical errors identified in previous implementations:

*   **Directional Errors:** Reversing Z-score entry/exit signals (buying on high price instead of selling).
*   **Negative Order Volumes:** Logic errors leading to "crossing the spread" against own orders.
*   **Inventory Management:** Subtracting flat volumes without checks (`max(0, quote)`), causing aggressive shorting on empty timestamps.
*   **Timing:** Shipping flawed code due to hard deadlines.

---

## 6. Development Roadmap
Future iterations focus on four primary pillars:

1.  **Gap Handling:** Robust logic for missing bids, asks, or mid-prices.
2.  **Time-Series Memory:** Maintaining a history of denoised mid-prices to filter temporary noise.
3.  **Trend Integration:** Micro-trend following to better time mean reversion entries.
4.  **Passive Liquidity:** Capturing spread with refined passive quote placement to avoid being "run over" by market moves.

---

## 7. Trader comparison (capsule, same harness)

All numbers use [`ROUND 2/tools/robust_backtester.py`](ROUND%202/tools/robust_backtester.py) (`run_backtest_on_csv`): same order-book simulation and PnL accounting for every row.

**IMC Round 2** — sum of `final_pnl` over the three files `prices_round_2_day_-1`, `_0`, `_1` under [`ROUND 2/data_capsule/`](ROUND%202/data_capsule/). Reproduce:  
`python "ROUND 2/tools/robust_backtester.py" "ROUND 2/traders/<file>.py" --r2 --imc-only`  
(MAF `bid()` values in source differ; the simulator does not apply the blind-auction fee.)

| Trader | IMC R2 Σ (3 days) | Source CSV under `ROUND 2/results/robust/` |
|--------|------------------:|---------------------------------------------|
| `peter_v1000.py` | **250,111** | `trader_peter_v1000_imc_robust_results.csv` |
| `Holy_grailll.py` (v10, three `l`) | **249,030** | `Holy_grailll_imc_r2_grailll_v10_robust_results.csv` |
| `ken/trader_ken_v5.py` | **248,343** | `trader_ken_v5_imc_r2_robust_results.csv` |
| `Holy_grail.py` (v8) | **248,150** | `Holy_grail_imc_r2_robust_results.csv` |
| `Holy_graill.py` (v9, two `l`) | **247,816** | `Holy_graill_imc_r2_graill_v9_robust_results.csv` |
| `chimera_safe.py` | **228,236** | `chimera_safe_imc_r1_r2_robust_results.csv` (R2 rows) |

**Stress: v_recovery_drift** — sum of `final_pnl` over `prices_v_recovery_drift_s0.csv`, `_s1`, `_s2` in [`ROUND 2/data_capsule/scenarios/`](ROUND%202/data_capsule/scenarios/) (category `scenario`, same `run_backtest_on_csv`).

| Trader | v_recovery_drift Σ (s0+s1+s2) |
|--------|------------------------------:|
| `Holy_graill.py` (v9) | **17,916** |
| `ken/trader_ken_v5.py` | **15,398** |
| `Holy_grailll.py` (v10) | **−24,051** |
| `Holy_grail.py` (v8) | **−24,298** |
| `peter_v1000.py` | **−24,635** |
| `chimera_safe.py` | **−51,331** |

**Readout:** On historical IMC R2 days, **peter_v1000** and **Holy_grailll** lead raw totals; **ken_v5** sits between them and **Holy_grail**/**Holy_graill**. On the three `v_recovery_drift` capsules, **Holy_graill (v9)** and **ken_v5** stay positive while the more aggressive Holy-family variants and **peter_v1000** go negative; **chimera_safe** gives up the most headline PnL there in exchange for its broader safety design.
