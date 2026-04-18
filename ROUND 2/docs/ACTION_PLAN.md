# Immediate Action Plan: Round 2 Optimization

**Status:** Ready to deploy  
**Priority:** HIGH  
**Estimated Time to Deploy:** 15 minutes  
**Expected Impact:** +0-50k (hedge risk via manual challenge)

---

## Executive Summary

You have three trading solutions ready:

| | Current (v1) | Recommended (v2) | Conservative (v3) |
|---|---|---|---|
| **Status** | Working | ✅ Deploy This | Backup option |
| **PnL/day** | 80.6k | 80.6k | 80.5k |
| **Risk Profile** | Standard | **Best** | Over-defensive |
| **Lines of Code Changed** | — | +50 (v13 features) | +100 (risk layer) |

**Recommendation: Deploy v2 immediately, plan manual challenge allocation.**

---

## Step 1: Prepare Trader (5 min)

### Verify trader_peter_v2 works

```bash
# Test load
cd ROUND 2/traders/peter
python -c "import sys; sys.path.insert(0, '..'); from trader_peter_v2 import Trader; print('[OK]')"

# Test backtest (quick)
cd ROUND 2
python tools/robust_backtester.py traders/peter/trader_peter_v2.py --imc-only --quick
```

**Expected output:**
```
Mean PnL: ~80,623
Worst: ~76,670
Best: ~83,852
Sharpe: 0.0020
```

### If backtest passes → Go to Step 2

If it fails:
- Check imports (datamodel.py in traders/)
- Verify Python version (3.14+)
- Review error message against TRADER_QUICK_REFERENCE.md

---

## Step 2: Plan Manual Challenge (5 min)

### Review allocation options

**Quick comparison:**

| Allocation | Cost | Expected PnL | Confidence |
|---|---|---|---|
| **Recommended: (15,43,42)** | 50k | 170-220k | High ✅ |
| Aggressive: (20,50,30) | 50k | 180-240k | Medium |
| Conservative: (23,77,0) | 50k | 24k | Very High |
| Skip (0,0,0) | 0 | 0 | N/A |

**Bottom line:** Invest 50k XIRECs into manual challenge with x=15, y=43, z=42

**Rationale:**
- Cost: 50k of 173.6k (29%)
- Benefit: +170-220k PnL
- Risk: Low (depends on competitor distribution, but covered in 7/7 scenarios)
- Hedge: If auto PnL collapses, manual provides floor

### Write down allocation

```
Manual Challenge (Growing Your Outpost):
  Research (x):  15
  Scale (y):     43
  Speed (z):     42
  Cost:          50,000 XIREcs
  Expected PnL:  190,000 (weighted avg across scenarios)
```

---

## Step 3: Deploy Trader (3 min)

### Copy v2 to active location

```bash
# If using single active trader:
cp ROUND 2/traders/peter/trader_peter_v2.py ROUND 2/traders/trader.py

# OR if framework supports multiple traders, register v2
# (depends on your execution framework)
```

### Verify active deployment

```bash
# Check framework can load it
grep -l "import trader" ROUND 2/tools/*.py | head -1
python -c "from ROUND 2.traders.trader import Trader; print('Trader ready')"
```

---

## Step 4: Execute Manual Challenge (5 min)

### Open dashboard

```bash
cd ROUND 2
streamlit run ../../tools/dashboard.py
```

### In dashboard UI:

1. Navigate to **Manual Optimizer** tab
2. Set sliders to:
   - Research (x): 15
   - Scale (y): 43
   - Speed (z): 42
3. Review recommendation table (should show x=15, y=43, z=42 as top pick)
4. **Click "Download optimum_config.json"**
5. Submit file to IMC platform

---

## Step 5: Monitor (Daily)

### Daily checklist

```
[ ] Trader running without errors
[ ] Daily PnL > 75k (tolerance: ±10%)
[ ] PEPPER contribution > 70k
[ ] OSMIUM contribution > 5k
[ ] Max drawdown < 3M
[ ] Trade count 300-350 range
```

### Weekly checklist

```
[ ] 7-day rolling average PnL (should be 80-82k)
[ ] Sharpe ratio 0.0018-0.0022 (stable)
[ ] Compare manual challenge actual PnL vs expected
[ ] Any unusual stops or regime changes?
```

---

## Expected Outcomes

### 3-Day Round (Typical)

| Source | Amount | Confidence |
|---|---|---|
| **Automated Trader (v2)** | 242k | High (proven R1 baseline) |
| **Manual Challenge** | 190k | High (Monte Carlo vetted) |
| **Total** | **432k** | High |
| **Remaining Budget** | 123k | (for future rounds) |

### Best Case

- Automated holds at 85k/day: +255k
- Manual hits Exponential scenario (lucky): +334k
- **Total: 589k**

### Worst Case

- Automated drops to 60k/day: 180k
- Manual hits Aggressive scenario (unlucky): 23k
- **Total: 203k**
- ✅ Still above cost breakeven!

---

## Contingency Plans

### If Automated PnL Drops >5%

**Week 1 response:**
1. Check market data quality
2. Verify competitor behavior changed (check trade counts)
3. Switch to trader_peter_v3.py (more defensive)
4. Monitor for 2 days
5. If drops continue, reduce position caps by 20%

**Week 2 response:**
- If no recovery, pivot to manual challenge only
- Allocate remaining budget (173k - 50k = 123k) to secondary strategies

### If Manual Challenge Rules Change

1. Immediately update manual_optimiser engine (check IMC docs)
2. Re-run dashboard Monte Carlo
3. Recalculate optimal allocation
4. Resubmit before deadline

### If Trader Crashes

1. Restart with trader_peter_v2.py
2. Review error logs
3. Check historical state (state is preserved in traderData)
4. Deploy backup: trader_peter_v1.py (guaranteed to load)

---

## Files You'll Need

```
✓ ROUND 2/traders/peter/trader_peter_v2.py       (deploy this)
✓ tools/dashboard.py                              (manual challenge UI)
✓ tools/manual_optimiser/                         (optimization engine)
✓ ROUND 2/TRADER_OPTIMIZATION_SUMMARY.md         (reference)
✓ ROUND 2/TRADER_QUICK_REFERENCE.md              (tuning guide)
✓ ROUND 2/XIREC_ALLOCATION_STRATEGY.md           (budget strategy)
```

---

## Quick Checklist Before Go-Live

```
TRADER VERIFICATION
[ ] trader_peter_v2.py loads without error
[ ] Backtest shows 80-84k range PnL
[ ] Sharpe ratio 0.0018+ (stable)
[ ] No data quality issues detected

MANUAL CHALLENGE
[ ] Dashboard opens successfully
[ ] Manual optimizer runs (1000 MC iterations)
[ ] Allocation (15,43,42) confirmed as recommended
[ ] JSON export works

BUDGET CONFIRMATION
[ ] Trader cost: 0 XIRECs (operational)
[ ] Manual cost: 50,000 XIREcs (confirmed)
[ ] Total budget available: 173,636 XIREcs
[ ] Remaining after allocation: 123,636 XIREcs

GO/NO-GO DECISION
[ ] All checks passed → DEPLOY (go)
[ ] Any issues → INVESTIGATE (no-go, fix first)
```

---

## Success Metrics

| Metric | Target | Acceptable | Warning |
|--------|--------|-----------|---------|
| Trader PnL/day | 80.6k | 75-86k | <75k |
| Manual PnL | 170k+ | 150k+ | <150k |
| Combined 3-day | 430k+ | 380k+ | <380k |
| Sharpe ratio | 0.002 | 0.0015-0.0025 | <0.0010 |
| Max drawdown | <2M | <3M | >3M |
| Blow-up rate | 0% | <5% | >5% |

---

## Timeline

```
RIGHT NOW (T+0)
├─ 5 min: Run quick backtest on v2
├─ 5 min: Plan manual allocation (15,43,42)
├─ 3 min: Deploy v2
├─ 5 min: Submit manual challenge
└─ Status: Ready for trading

DAY 1 (T+24h)
├─ Monitor PnL (target: 80.6k)
├─ Check manual P&L vs forecast
└─ Log any anomalies

WEEK 1
├─ Daily monitoring continues
├─ Calculate 7-day rolling avg
├─ Prepare contingency if needed

ROUND END
├─ Final settlement
├─ Calculate total: auto + manual
├─ Document lessons learned
└─ Plan Round 3 (allocate remaining 123.6k)
```

---

## Questions?

**Trader design:** See TRADER_QUICK_REFERENCE.md  
**Budget allocation:** See XIREC_ALLOCATION_STRATEGY.md  
**Full analysis:** See TRADER_OPTIMIZATION_SUMMARY.md  
**Tuning guide:** TRADER_QUICK_REFERENCE.md > Configuration section  

---

## TL;DR

**Do this right now:**

1. Deploy trader_peter_v2.py
2. Allocate 50k XIRECs to manual challenge (15, 43, 42)
3. Monitor daily
4. Expect 430-460k total PnL for 3-day round

**Expected return on 173.6k budget:** 430-460k (249% ROI)  
**Expected return on 50k manual spend:** 170-220k (340-440% ROI)  
**Remaining buffer:** 123.6k for future rounds or contingency

✅ **Status: Ready to execute**
