# Comprehensive Statistical Analysis
This document provides the results of the requested statistical tests applied to historical data for **INTARIAN_PEPPER_ROOT** and **ASH_COATED_OSMIUM**.

*(Note: Data is sampled at 1/10th frequency to ensure computational stability for tests like ARMA/GARCH and VAR/VECM)*

## 1. Single Asset Statistical Diagnostics

---
#### Field: `mid_price`
### INTARIAN_PEPPER_ROOT
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **30952746.86** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **8.3785e-01** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **7.0777e-30** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **9.1424e-01** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **9.2710e-155** | Line Graph: Autocorrelation present if < 0.05 |
### ASH_COATED_OSMIUM
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **5573931.94** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **8.1350e-30** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **6.4217e-01** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **9.1251e-155** | Line Graph: Autocorrelation present if < 0.05 |
---
#### Field: `profit_and_loss`
### INTARIAN_PEPPER_ROOT
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **nan** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **nan** | Non-normal if < 0.05 |
| ADF | Error | Invalid input, x is constant | |
| CUSUM (level) | P-Value | **nan** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:0 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **nan** | Line Graph: Autocorrelation present if < 0.05 |
### ASH_COATED_OSMIUM
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **nan** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **nan** | Non-normal if < 0.05 |
| ADF | Error | Invalid input, x is constant | |
| CUSUM (level) | P-Value | **nan** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:0 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **nan** | Line Graph: Autocorrelation present if < 0.05 |
---
#### Field: `timestamp`
### INTARIAN_PEPPER_ROOT
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **279846467.66** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **1.2782e-01** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **1.1976e-48** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:1 MA:0 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **1.0000e+00** | Line Graph: Autocorrelation present if < 0.05 |
### ASH_COATED_OSMIUM
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **279846467.66** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **1.2782e-01** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **1.1976e-48** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:1 MA:0 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **1.0000e+00** | Line Graph: Autocorrelation present if < 0.05 |
---
#### Field: `bid_price_1`
### INTARIAN_PEPPER_ROOT
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **6043.92** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **9.8604e-01** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **2.0616e-16** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **3.5273e-81** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **1.1449e-142** | Line Graph: Autocorrelation present if < 0.05 |
### ASH_COATED_OSMIUM
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **2210.65** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **1.6023e-08** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **6.0883e-13** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:1 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **2.0027e-104** | Line Graph: Autocorrelation present if < 0.05 |
---
#### Field: `ask_price_1`
### INTARIAN_PEPPER_ROOT
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **6884.11** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **9.3156e-01** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **6.5425e-13** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **8.1929e-89** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **8.0479e-153** | Line Graph: Autocorrelation present if < 0.05 |
### ASH_COATED_OSMIUM
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **3356.94** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **5.8753e-08** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **2.4176e-15** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:1 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **7.4255e-109** | Line Graph: Autocorrelation present if < 0.05 |
---
#### Field: `bid_volume_1`
### INTARIAN_PEPPER_ROOT
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **54567.57** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **9.6932e-01** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **5.3258e-84** | Line Graph: Autocorrelation present if < 0.05 |
### ASH_COATED_OSMIUM
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **514132.47** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **4.3506e-01** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **4.1266e-32** | Line Graph: Autocorrelation present if < 0.05 |
---
#### Field: `ask_volume_1`
### INTARIAN_PEPPER_ROOT
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **25897.66** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **9.1239e-01** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **3.6089e-92** | Line Graph: Autocorrelation present if < 0.05 |
### ASH_COATED_OSMIUM
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **143753.62** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **9.9636e-01** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **7.2414e-43** | Line Graph: Autocorrelation present if < 0.05 |
---
#### Field: `bid_price_2`
### INTARIAN_PEPPER_ROOT
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **1882.15** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **9.9546e-01** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **5.9136e-54** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:1 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **4.8705e-15** | Line Graph: Autocorrelation present if < 0.05 |
### ASH_COATED_OSMIUM
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **727.55** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **1.0319e-158** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **2.7188e-08** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **9.6088e-10** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **1.7872e-14** | Line Graph: Autocorrelation present if < 0.05 |
---
#### Field: `ask_price_2`
### INTARIAN_PEPPER_ROOT
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **1907.51** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **3.2242e-01** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **9.8100e-11** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **6.2325e-92** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **6.3074e-23** | Line Graph: Autocorrelation present if < 0.05 |
### ASH_COATED_OSMIUM
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **51.76** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **5.7712e-12** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **9.1985e-08** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **2.0222e-30** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **2.2406e-12** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:1 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **9.0062e-12** | Line Graph: Autocorrelation present if < 0.05 |
---
#### Field: `bid_volume_2`
### INTARIAN_PEPPER_ROOT
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **3568.37** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **9.6820e-01** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **1.5763e-77** | Line Graph: Autocorrelation present if < 0.05 |
### ASH_COATED_OSMIUM
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **89913.20** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **9.8941e-01** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **2.1630e-58** | Line Graph: Autocorrelation present if < 0.05 |
---
#### Field: `ask_volume_2`
### INTARIAN_PEPPER_ROOT
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **4179.91** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **0.0000e+00** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **9.9949e-01** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:0 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **4.0737e-77** | Line Graph: Autocorrelation present if < 0.05 |
### ASH_COATED_OSMIUM
| Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| Jarque-Bera (returns) | JB Stat  | **4568.11** | Histogram: Tail density assessment |
| Jarque-Bera (returns) | P-Value | **0.0000e+00** | Non-normal if < 0.05 |
| ADF (level) | P-Value | **2.6233e-17** | Line Graph: Stationary if < 0.05 |
| ADF (returns) | P-Value | **8.0538e-24** | Line Graph: Stationary if < 0.05 |
| CUSUM (level) | P-Value | **8.9311e-01** | Residual Plot: Structural break if < 0.05 |
| ARMA AIC/BIC | Optimal Order | AR:1 MA:1 | ACF/PACF correlograms |
| Ljung-Box | P-Value | **6.9084e-63** | Line Graph: Autocorrelation present if < 0.05 |
---
#### Field: `bid_price_3`
---
#### Field: `ask_price_3`
---
#### Field: `bid_volume_3`
---
#### Field: `ask_volume_3`

---
## 2. Pairs Trading Cointegration Diagnostics

#### Field Pair: `mid_price` (Pepper vs Osmium)

| Pair Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| VAR (Vector Autoregression) | Optimal Lag (p) | **5** | Cross-correlation impact matrix |
| Granger Causality | P-Value (F-test) | **9.5830e-01** | Leading Indicator graph (predictive) |
| Johansen Cointegration | Trace Statistic | **1306.89 (Crit: 15.49)** | Cointegrated spread plot |
| Better VECM Select | Coint Rank / AR Diff | Rank: 2, AR: 5 | Spread reversion curve |


#### Field Pair: `timestamp` (Pepper vs Osmium)

| Pair Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| VAR | Error | 2-th leading minor of the array is not positive definite | |
| Granger Causality | P-Value (F-test) | **1.0000e+00** | Leading Indicator graph (predictive) |
| Johansen | Error | Singular matrix | |
| VECM Select | Error | 2-th leading minor of the array is not positive definite | |


#### Field Pair: `bid_price_1` (Pepper vs Osmium)

| Pair Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| VAR (Vector Autoregression) | Optimal Lag (p) | **5** | Cross-correlation impact matrix |
| Granger Causality | P-Value (F-test) | **6.9621e-01** | Leading Indicator graph (predictive) |
| Johansen Cointegration | Trace Statistic | **103.61 (Crit: 15.49)** | Cointegrated spread plot |
| Better VECM Select | Coint Rank / AR Diff | Rank: 1, AR: 5 | Spread reversion curve |


#### Field Pair: `ask_price_1` (Pepper vs Osmium)

| Pair Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| VAR (Vector Autoregression) | Optimal Lag (p) | **5** | Cross-correlation impact matrix |
| Granger Causality | P-Value (F-test) | **9.6185e-01** | Leading Indicator graph (predictive) |
| Johansen Cointegration | Trace Statistic | **124.52 (Crit: 15.49)** | Cointegrated spread plot |
| Better VECM Select | Coint Rank / AR Diff | Rank: 1, AR: 5 | Spread reversion curve |


#### Field Pair: `bid_volume_1` (Pepper vs Osmium)

| Pair Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| VAR | Error | index 0 is out of bounds for axis 0 with size 0 | |
| Granger Causality | P-Value (F-test) | **3.1695e-01** | Leading Indicator graph (predictive) |
| Johansen Cointegration | Trace Statistic | **2313.81 (Crit: 15.49)** | Cointegrated spread plot |
| Better VECM Select | Coint Rank / AR Diff | Rank: 2, AR: 1 | Spread reversion curve |


#### Field Pair: `ask_volume_1` (Pepper vs Osmium)

| Pair Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| VAR | Error | index 0 is out of bounds for axis 0 with size 0 | |
| Granger Causality | P-Value (F-test) | **3.6189e-01** | Leading Indicator graph (predictive) |
| Johansen Cointegration | Trace Statistic | **2233.47 (Crit: 15.49)** | Cointegrated spread plot |
| Better VECM Select | Coint Rank / AR Diff | Rank: 2, AR: 1 | Spread reversion curve |


#### Field Pair: `bid_price_2` (Pepper vs Osmium)

| Pair Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| VAR (Vector Autoregression) | Optimal Lag (p) | **1** | Cross-correlation impact matrix |
| Granger Causality | P-Value (F-test) | **8.3526e-01** | Leading Indicator graph (predictive) |
| Johansen Cointegration | Trace Statistic | **41.34 (Crit: 15.49)** | Cointegrated spread plot |
| Better VECM Select | Coint Rank / AR Diff | Rank: 1, AR: 1 | Spread reversion curve |


#### Field Pair: `ask_price_2` (Pepper vs Osmium)

| Pair Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| VAR (Vector Autoregression) | Optimal Lag (p) | **2** | Cross-correlation impact matrix |
| Granger Causality | P-Value (F-test) | **9.7493e-01** | Leading Indicator graph (predictive) |
| Johansen Cointegration | Trace Statistic | **46.24 (Crit: 15.49)** | Cointegrated spread plot |
| Better VECM Select | Coint Rank / AR Diff | Rank: 2, AR: 1 | Spread reversion curve |


#### Field Pair: `bid_volume_2` (Pepper vs Osmium)

| Pair Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| VAR | Error | index 0 is out of bounds for axis 0 with size 0 | |
| Granger Causality | P-Value (F-test) | **8.6091e-02** | Leading Indicator graph (predictive) |
| Johansen Cointegration | Trace Statistic | **1070.05 (Crit: 15.49)** | Cointegrated spread plot |
| Better VECM Select | Coint Rank / AR Diff | Rank: 2, AR: 1 | Spread reversion curve |


#### Field Pair: `ask_volume_2` (Pepper vs Osmium)

| Pair Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| VAR | Error | index 0 is out of bounds for axis 0 with size 0 | |
| Granger Causality | P-Value (F-test) | **7.3693e-01** | Leading Indicator graph (predictive) |
| Johansen Cointegration | Trace Statistic | **1038.27 (Crit: 15.49)** | Cointegrated spread plot |
| Better VECM Select | Coint Rank / AR Diff | Rank: 2, AR: 1 | Spread reversion curve |


#### Field Pair: `bid_price_3` (Pepper vs Osmium)

| Pair Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| VAR | Error | maxlags is too large for the number of observations and the number of equations. The largest model cannot be estimated. | |
| Granger | Error | Insufficient observations. Maximum allowable lag is 0 | |
| Johansen Cointegration | Trace Statistic | **nan (Crit: 15.49)** | Cointegrated spread plot |
| VECM Select | Error | zero-size array to reduction operation maximum which has no identity | |


#### Field Pair: `ask_price_3` (Pepper vs Osmium)

| Pair Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| VAR | Error | maxlags is too large for the number of observations and the number of equations. The largest model cannot be estimated. | |
| Granger | Error | Insufficient observations. Maximum allowable lag is -1 | |
| Johansen | Error | maxlag should be < nobs | |
| VECM Select | Error | zero-size array to reduction operation maximum which has no identity | |


#### Field Pair: `bid_volume_3` (Pepper vs Osmium)

| Pair Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| VAR | Error | maxlags is too large for the number of observations and the number of equations. The largest model cannot be estimated. | |
| Granger | Error | Insufficient observations. Maximum allowable lag is 0 | |
| Johansen Cointegration | Trace Statistic | **nan (Crit: 15.49)** | Cointegrated spread plot |
| VECM Select | Error | zero-size array to reduction operation maximum which has no identity | |


#### Field Pair: `ask_volume_3` (Pepper vs Osmium)

| Pair Test | Metric | Value | Interpretation (Graph Type) |
| --- | --- | --- | --- |
| VAR | Error | maxlags is too large for the number of observations and the number of equations. The largest model cannot be estimated. | |
| Granger | Error | Insufficient observations. Maximum allowable lag is -1 | |
| Johansen | Error | maxlag should be < nobs | |
| VECM Select | Error | zero-size array to reduction operation maximum which has no identity | |



## Final Interpretation Summary
- **Stationarity**: Strong stationarity (ADF < 0.05) implies the variables revert to a mean. Essential for passive market making.
- **Cointegration**: If Johansen Trace > Critical Value, the assets move together, confirming the pairs trade strategy capability.
- **Granger Causality**: Suggests movements in the field for one asset can reliably predict the next tick of the other asset.
