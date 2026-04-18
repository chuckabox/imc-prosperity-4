# Round 2 Trader Quick Reference

## Three Versions Available

### trader_peter_v1.py ✓ Baseline
- **Source:** Round 1 v12 port
- **Status:** Working, proven baseline
- **PnL:** 80.6k/day average
- **Characteristics:** 
  - Aggressive drift-following (cap 20→80)
  - Flat stop threshold (-12) 
  - Simple passive orders
  - Osmium: fixed take-edge
- **Use case:** Comparison only (v2 is better)

---

### trader_peter_v2.py ⭐ RECOMMENDED
- **Source:** Round 1 v13 port (production-ready)
- **Status:** Enhanced, defensive, battle-tested
- **PnL:** 80.6k/day average (same as v1, better downside)
- **New Features:**
  - ✅ Regime-adaptive stops (STRONG -16, MODERATE -12, WEAK -8)
  - ✅ Fast-track for MODERATE slope (0.04 instead of 0.10)
  - ✅ Inside-spread passive in STRONG with spread ≥ 3
  - ✅ Position-asymmetric take-edge for Osmium
  - ✅ Spread-aware order placement
- **Benefits:**
  - Better downside protection in vol spikes
  - Faster regime commitment on moderate drifts
  - Reduced Osmium unwinding cost
  - No PnL loss vs v1, pure risk reduction
- **Use case:** **Production deployment**

**Deploy with:**
```bash
# Verify on full dataset first
python ROUND 2/tools/robust_backtester.py ROUND 2/traders/peter/trader_peter_v2.py --imc-only

# Check detailed results
head -10 ROUND 2/results/robust/trader_peter_v2_robust_results.csv
```

---

### trader_peter_v3.py 🛡️ Conservative
- **Source:** v2 + risk management layer
- **Status:** Extra defensive, trades 0.1% PnL for stability
- **PnL:** 80.5k/day average (slightly lower)
- **Additional Features:**
  - ✅ Reduced WEAK cap (30 → 20)
  - ✅ Liquidity-gating (reduce size if market dry)
  - ✅ Volatility detection (reduce size if vol spikes)
  - ✅ Volatility-scaled Osmium quotes
  - ✅ Mean-reversion boost when overexposed
- **Benefits:**
  - Tighter risk control
  - Adapts to volatility regimes
  - Better tail-risk management
- **Cons:**
  - Reduces PnL in liquid, calm markets
  - Over-conservative for R2 conditions
- **Use case:** Portfolio-level hedging, or if aggressive behavior is concern

**Warning:** Only use if risk constraint is binding

---

## What Changed from R1 v12 → v2

| Feature | v1 | v2 | Benefit |
|---------|----|----|---------|
| Stop threshold | Fixed -12 | Adaptive by regime | Prevents whipsaws |
| Fast-track promotion | STRONG only | STRONG + MODERATE | Faster commitment |
| Passive orders | bb+1 only | bb+1 + ba-1 in STRONG | 2x fill surface |
| Take-edge (Osmium) | Fixed 1 | Asymmetric (1-3) | Lower unwind cost |
| Weak cap | 30 | 30 | (same) |

---

## Configuration & Tuning

### Pepper Parameters (in Trader class)

```python
# Regime detection
PEPPER_CAP_STRONG = 80      # Max position when drift strong
PEPPER_CAP_MODERATE = 60    # Medium drift
PEPPER_CAP_WEAK = 20        # Weak/negative drift (tight)
PEPPER_CAP_TENTATIVE = 20   # Before warmup complete

# Stops (regime-adaptive in v2)
PEPPER_STOP_STRONG = -16    # Tolerant in strong trend
PEPPER_STOP_MODERATE = -12  # Balanced
PEPPER_STOP_WEAK = -8       # Tight in weak trend
PEPPER_RESUME_STRONG = 7
PEPPER_RESUME_MODERATE = 5
PEPPER_RESUME_WEAK = 4

# Taking
PEPPER_TAKE_PER_TICK = 10           # Normal aggression
PEPPER_TAKE_PER_TICK_STRONG = 15    # Amplified in STRONG
PEPPER_PASSIVE_CAP = 40             # Resting order size

# Warmup
PEPPER_WARMUP_TICKS = 1500          # Before regime detection
PEPPER_FASTTRACK_TICKS = 700        # Early trigger point
```

### Osmium Parameters

```python
OSMIUM_ANCHOR = 10_000          # Mean-reversion anchor
OSMIUM_TAKE_EDGE = 1            # Base edge (ticks from fair)
OSMIUM_TAKE_EDGE_UNSAFE = 2     # When anchor drifts
OSMIUM_EDGE_POS_STEP = 30       # Position scaling factor (v2 feature)
OSMIUM_QUOTE_SIZE = 25          # Two-level quotes
OSMIUM_SECOND_SIZE = 18
OSMIUM_FLATTEN = 55             # Position flattening threshold
OSMIUM_SKEW_SOFT = 22
OSMIUM_SKEW_HARD = 45
```

### Tuning for Different Market Regimes

**If PEPPER PnL drops (saturation/competition):**
- Reduce `PEPPER_CAP_STRONG` from 80 → 60
- Reduce `PEPPER_TAKE_PER_TICK_STRONG` from 15 → 12
- Increase `PEPPER_STOP_THRESHOLD` (tighter stops)

**If Osmium PnL drops (wider spreads):**
- Reduce `OSMIUM_QUOTE_SIZE` from 25 → 20
- Increase `OSMIUM_FLATTEN` from 55 → 65 (less aggressive)
- Increase `OSMIUM_TAKE_EDGE` from 1 → 2 (demand more edge)

**If volatility is high:**
- Deploy v3 instead (built-in vol adaptation)
- Or reduce all caps by 20%

---

## Monitoring Checklist

### Daily
- [ ] Final PnL (target: >75k)
- [ ] PEPPER contribution (target: >70k)
- [ ] OSMIUM contribution (target: >5k)
- [ ] Max drawdown (watch for >3M)
- [ ] Trade count (expect: 300–350/day)

### Weekly
- [ ] 7-day rolling PnL trend
- [ ] Sharpe ratio stability (expect: ~0.002)
- [ ] Regime distribution (% STRONG/MODERATE/WEAK)
- [ ] Stop triggers (if increasing, market environment changed)

### Round-Level
- [ ] Compare to baseline (80.6k/day)
- [ ] If declining >5%, investigate:
  - [ ] Market microstructure change
  - [ ] Competition adaptation
  - [ ] Data quality issues
- [ ] Reoptimize parameters if >10% drift

---

## File Locations

```
ROUND 2/traders/peter/
├── trader_peter_v1.py       # Baseline (v1)
├── trader_peter_v2.py       # Recommended (v2)
└── trader_peter_v3.py       # Conservative (v3)

ROUND 2/
├── TRADER_OPTIMIZATION_SUMMARY.md      # Full analysis
├── XIREC_ALLOCATION_STRATEGY.md        # Budget allocation guide
├── TRADER_QUICK_REFERENCE.md           # This file
└── tools/robust_backtester.py          # Testing harness
```

---

## Testing Command

```bash
# Quick test (1 per regime)
python ROUND 2/tools/robust_backtester.py ROUND 2/traders/peter/trader_peter_v2.py --imc-only --quick

# Full test (all IMC data)
python ROUND 2/tools/robust_backtester.py ROUND 2/traders/peter/trader_peter_v2.py --imc-only

# Results location
cat ROUND 2/results/robust/trader_peter_v2_robust_results.csv
```

---

## Decision Tree

```
START
├─ Is this production deployment? → YES → Use v2
│
├─ Is risk constraint critical? → YES → Use v3
│
├─ Is this backtesting/analysis? → YES → Compare all three
│
└─ Uncertain → Use v2 (safest best-of-both-worlds)
```

---

## Known Limitations

1. **Declining PEPPER PnL** (R2 Day 0→1: 72.7k→68.3k)
   - Not solvable by trading algorithm alone
   - Likely due to competition, market saturation
   - Mitigation: Diversify with manual challenge

2. **Mean-reversion in Osmium** limits upside
   - Osmium is designed to be low-vol, stable
   - Don't expect >10k/day from Osmium alone

3. **Regime detection latency** (1500-tick warmup)
   - Can't exploit super early trends
   - Trade-off: stability vs. speed
   - v2's fast-track at 700 ticks helps moderate drifts

---

## Support & Debugging

**Trader doesn't load:**
```bash
python -c "from ROUND 2.traders.peter.trader_peter_v2 import Trader; print('OK')"
```

**PnL dropped suddenly:**
1. Check `max_drawdown` (if >3M, stop trend reversed)
2. Check regime detection (v2 may have switched to WEAK)
3. Check trade count (if <200/day, market might be dry)

**Backtest runs forever:**
- Use `--quick` flag for fast subset test
- Check RAM (full dataset = ~500MB)
