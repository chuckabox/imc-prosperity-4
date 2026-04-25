# Alphas to investigate further based on live log analysis

## KEY FINDING: Hydrogel is 100%+ of PnL
The live log shows HYDROGEL_PACK = +11,389 (>100% of total 10,802).
VEV options combined = -83 (net NEGATIVE in the live run!).

## New Alpha Candidates

### Alpha #10: Hydrogel Aggressive Spread Capture
- Hydrogel spreads are wide (16-20 ticks at times). Our current maker edge is just 1 tick.
- We could widen our spread to capture more per trade.
- Need to test: does wider spread improve PnL or reduce fill rate?

### Alpha #11: HP Dynamic Anchor Adjustment  
- Current anchor is fixed at 9991.0 with 80% EWMA blend
- The live data shows HP oscillates between 9950-10030
- A tighter EWMA (faster adaptation) might improve edge detection

### Alpha #12: VEV Multi-Strike MM (extending SMM)
- Currently only MM on 5300/5400
- Could extend to 5200/5500 where alpha_hunter_v1 showed some opportunities
- VEV_5200: 420 sell opps with 0.70 edge

### Alpha #13: VFE Market Making Improvement
- VFE is NET NEGATIVE (-505). The hedging is too expensive.
- Options: reduce hedge frequency, widen hedge band, or add VFE-standalone alpha

### Rejected:
- Pure gamma scalping: Data shows net negative PnL at market IV
- Intrinsic violations: None found in the data
- Whale counterparty signals: Anonymized trade tape, no signatures
- Lead-lag VFE→VEV: Very weak signal, not actionable
- Time-of-day patterns: Spreads are uniform, no exploitable pattern
