Quantitative Trading Pipeline — SKILL.md
Version: Round 2 + MAF Edition

Phase I: High-Fidelity Signal Processing

Log-Geometric Differencing: Implementation of r(t)=ln⁡(p(t)/p(t−1))r(t) = \ln(p(t)/p(t-1))
r(t)=ln(p(t)/p(t−1)) for invariant scaling and time-additive properties.

Non-Parametric Normality Profiling: Utilizing Jarque-Bera (Third/Fourth Moment Analysis) to identify "Fat-Tail" (Leptokurtic) risk, moving beyond the limitations of Gaussian models. JB threshold = 6.0 (approx. 5% critical value).
CUSUM Regime Detection: Detecting cumulative sum deviations in standardised log-returns (two-sided, threshold = 4σ) to identify structural breaks in market volatility before they contaminate unit-root tests or VECM estimation.

Phase II: Order Identification & Stationarity

Manual VECM Solver: Implementing Vector Error Correction via the Normal Equation and Singular Value Decomposition (SVD) using NumPy, bypassing high-level library overhead for low-latency signal generation.
Johansen Equilibrium Logic: Identifying cointegrating vectors through Eigen-decomposition of the long-run covariance matrix to define the stable "Hedge Ratio" (β). Smallest eigenvalue → most stationary linear combination.
SVD-OLS Fallback: When Johansen is numerically degenerate, fall back to β_ols = VᵀΣ⁻¹Uᵀy via np.linalg.svd.
Half-Life Estimation: OLS alpha from Δspread(t) = α·spread(t−1) + ε. half_life = −ln(2)/α. Gate VECM signal when half_life > 80 ticks.

Phase III: Statistical Arbitrage Execution

Z-Score Execution Logic: High-speed triggers based on VECM residual extremes. Entry at |Z| ≥ 1.8, exit at |Z| ≤ 0.4, hard stop-loss flatten at |Z| ≥ 3.8.
Dynamic Risk Scaling: GARCH-inspired position sizing — quote sizes scaled ×0.5 under anchor drift, ×0.7 under CUSUM/fat-tail. VECM fair-value nudge scaled ×0.5 under fat tails.
MBIC-Penalized Optimization (Phase IV scope): Bayesian Information Criterion penalty to prevent over-parameterization of lag windows.
Hard Stop-Loss: Immediate full flatten at best bid/ask when |Z| ≥ Z_HARD_STOP. Non-negotiable. Designed to reduce blow-up rate from baseline 34.8%.

Phase IV: Walk-Forward PnL Loop Tester

Recursive Walk-Forward Loops: Autonomous Meta-Optimizer that continuously iterates through hyperparameter space (Thresholds, Lags, Hedge Ratios, MAF_BID_FRACTION) to hunt for maximum risk-adjusted PnL.
Persistent State Serialization: Model state and champion configurations managed via json.dumps/loads (bounded rolling windows to stay within exchange traderData limits ~10 KB).
Automated Statistical Auditing: Self-reporting analysis.md logs evaluating convergence speeds, stationarity scores, MAF win-rate estimates, and Sharpe ratios at every iteration.
Shadow Tester: Per-tick hyperparameter perturbation. If perturbed config yields higher Sharpe, crown it Champion. Once Mean PnL ≥ $200k, shift objective to BIC-penalized Sharpe stability.

Phase V: Market Access Fee (MAF) Auction Engine
The MAF is a blind competitive auction. Top 50% of bidders win +25% volume allocation for that tick. Others pay nothing and trade on original limits.
Core Decision Rule (per tick):
edge_per_unit(t)  = rolling mean |order_price − mid| per filled unit  [60-tick window]
extra_units       = position_limit × 0.25
EV_product(t)     = edge_per_unit(t) × extra_units
MAF_bid(t)        = Σ_products [ EV_product(t) × MAF_BID_FRACTION ]
MAF_BID_FRACTION = 0.35 (retain 65% of EV; adjust via walk-forward optimisation).
Kill-Switch Hierarchy (evaluated in order):
ConditionActionPre-warmup (< 100 ticks)MAF = 0Both products CUSUM + fat-tail activeMAF = 0Single product risk-flaggedEV for that product × 0.4OSMIUM half-life > 80 ticksOSMIUM EV × 0.3OSMIUM half-life 40–80 ticksOSMIUM EV × 0.7
Adaptive Bidding:
Track bid history (20 ticks). If bid monotonically rising for 5 ticks → multiply adapt by 1.10 (cap 2×). If bid stable/falling → multiply adapt by 0.92 (floor 0.5×). Self-calibrates toward the 50th-percentile clearing price.
MAF Return Slot:
run() returns (orders, maf_int, traderData). Exchange interprets the second return value as the MAF bid when > 0.
Optimisation Targets:

Walk-forward sweep of MAF_BID_FRACTION over {0.20, 0.25, 0.30, 0.35, 0.40, 0.50} to find value maximising P(win) × (EV − bid).
Once MAF feedback signal available (e.g. actual filled qty > LIMIT), switch adapt to direct Bayesian update on clearing threshold distribution.

Phase VI: Performance-Driven NumPy Engineering

Vectorized Backtesting Pipelines: O(1) time-complexity backtesting via NumPy broadcasting; no iterative loops in the hot path.
Manual Convergence Estimation: OLS-based Error Correction for half-life, ensuring exits timed to mean-reversion speed.
Memory Budget Discipline: All rolling windows strictly bounded. Total traderData target < 4 KB (hard limit ~10 KB).


Engineering Constraints (CRITICAL — never violate)

Allowed libraries only: numpy, pandas, math, typing, statistics, json. No statsmodels, scikit-learn, os, subprocess, jsonpickle in production (use json directly).
State via traderData: All persistence through state.traderData using json.dumps/loads.
Bounded windows: Every list appended to self.history must have a hard trim to prevent traderData string-length crashes.
No form tags in any artifact. Use onClick/onChange handlers only.
MAF is the third return value of run() — not a separate API call. return orders, maf_int, trader_data.