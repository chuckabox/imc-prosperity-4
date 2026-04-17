# Quantitative Trading Pipeline

## Phase I: High-Fidelity Signal Processing
- **Log-Geometric Differencing:** Implementation of $r(t) = \ln(p(t)/p(t-1))$ for invariant scaling and time-additive properties.
- **Non-Parametric Normality Profiling:** Utilizing Jarque-Bera (Third/Fourth Moment Analysis) and Lilliefors to identify "Fat-Tail" (Leptokurtic) risk, moving beyond the limitations of Gaussian models.
- **CUSUM Regime Detection:** Detecting cumulative sum deviations to identify structural breaks in market volatility before they contaminate unit-root tests.

## Phase II: Order Identification & Stationarity
- **Manual VECM Solver:** Implementing Vector Error Correction via the Normal Equation and Singular Value Decomposition (SVD) using NumPy, bypassing high-level library overhead for low-latency signal generation.
- **Johansen Equilibrium Logic:** Identifying cointegrating vectors through Eigen-decomposition of the long-run covariance matrix to define the stable "Hedge Ratio" ($\beta$).

## Phase III: Statistical Arbitrage Execution
- **Z-Score Execution Logic:** Developing high-speed triggers based on VECM residual extremes, targeting entries and exits at 95% and 99% confidence intervals for mean-reversion strategies.
- **Dynamic Risk Scaling:** Implementing GARCH-inspired position sizing, where capital allocation is scaled inversely to rolling conditional variance $\sigma^2(t)$, ensuring survival during "Order Flow Toxicity" events.
- **MBIC-Penalized Optimization:** Utilizing the Bayesian Information Criterion (BIC) to strictly penalize over-parameterization, ensuring that model complexity (lags) is justified by predictive power.

## Phase IV: Walk-Forward PnL Loop Tester
- **Recursive Walk-Forward Loops:** Design and implementation of an Autonomous Meta-Optimizer that continuously iterates through hyperparameter space (Thresholds, Lags, Hedge Ratios) to hunt for maximum PnL targets. 
- **Persistent State Serialization:** Expertise in managing model state and champion configurations using `jsonpickle`, ensuring consistent performance tracking and recovery across long-running, asynchronous market ticks.
- **Automated Statistical Auditing:** Engineering a "Self-Reporting" system that generates `analysis.md` logs, evaluating convergence speeds and stationarity scores at every iteration to provide a transparent audit trail of the model's evolution.

## Phase V: Performance-Driven NumPy Engineering
- **Vectorized Backtesting Pipelines:** Expertise in building high-performance, $O(1)$ time-complexity backtesting engines using NumPy broadcasting, bypassing iterative loops for extreme-speed parameter search.
- **Manual Convergence Estimation:** Implementation of OLS-based Error Correction logic to manually derive Alpha (speed of adjustment), ensuring exits are perfectly timed to the half-life of the mean reversion.