# Quantiative Trading Pipeline

## Goal 
Create the trader which can generate the most PNL while minimizing overfitting as much as possible.

## Before looking at the phases
When you test, I want you to create an analysis.md of the statistical values and evaluate if that implementation is necessary 

## Phase 1-2: Feature Engineering & Normality Diagnostics
- Logarithmic Differencing: Implementation of $r(t) = \ln(p(t)/p(t-1))$ to ensure time-series stationarity, additivity across horizons, and mitigation of price-level bias.
- Distributional Analytics (JB & Lilliefors): Advanced detection of skewness and kurtosis. Proficiency in identifying "Fat Tails," signaling the shift from Gaussian assumptions to Student’s t-distributions for robust risk modeling.

## Phase 3-4: Order Identification & Stationarity
- Regime Shift Detection (CUSUM): Expertise in identifying structural breaks to prevent "Parameter Drift." Running CUSUM prior to stationarity tests ensures unit root readings aren't contaminated by sudden market shifts.
- Information Criterion Optimization: Utilizing BIC to enforce a high penalty for complexity, minimizing the "Degrees of Freedom" problem and preventing the over-parameterization of the mean equation.

## Phase 5: Volatility Modeling & Tail Risk
- Heteroskedasticity Management (GARCH): Expertise in modeling conditional variance $\sigma^2(t)$. Applying ARCH-LM tests to identify volatility clustering and dynamic position sizing.
- Risk Quantization (VaR): Developing Value-at-Risk frameworks to define maximum permissible drawdown and protect capital during "Flash Crashes."

## Phase 6-7: Multivariate Dynamics
- Johansen Cointegration: Identifying the long-term equilibrium (the "leash") between non-stationary assets.
- VECM (Vector Error Correction Model): Distinguishing between short-term momentum and long-term mean reversion using Alpha (adjustment speed) and Beta (hedge ratio).

