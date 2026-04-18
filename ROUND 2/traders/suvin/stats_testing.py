import matplotlib.pyplot as plt
import statsmodels.api as sm
import pandas as pd
import numpy as np
import datetime as dt
import warnings
from statsmodels.regression.rolling import RollingOLS
from scipy.stats import jarque_bera, skew, kurtosis, normaltest
from statsmodels.tsa.stattools import acf, pacf
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.stats.diagnostic import het_arch
from statsmodels.stats.diagnostic import lilliefors
from arch import arch_model
from statsmodels.tsa.stattools import adfuller, kpss
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.stats.diagnostic import breaks_cusumolsresid
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import grangercausalitytests
from statsmodels.tsa.vector_ar.vecm import coint_johansen
from statsmodels.tsa.vector_ar.vecm import VECM
from statsmodels.tsa.vector_ar.vecm import select_order, select_coint_rank
from statsmodels.tsa.stattools import arma_order_select_ic


# SINGLE PRICE COMPUTATION STATISTICS r(t)

# Percentage Change Test 
def compute_returns(prices: pd.Series) -> pd.DataFrame:
  # Drops null types (dropna)
  p = prices.astype(float).dropna()

  out = pd.DataFrame(index=p.index)
  out["R(t)"] = p.pct_change()
  out["r(t)"] = np.log(p).diff()
  out["p(t)"] = np.log(p)
  return out.dropna()


# Jarque-bera test 
def distribution_summary(x):
  x = x.dropna()
  jb = jarque_bera(x)
  return {
      "mean": x.mean(),
      "varience": x.var(ddof=1),
      "skewness": skew(x),
      "kurtosis": kurtosis(x, fisher=False, bias=False),
      "jb_statistic": jb.statistic,
      "jb_pvalue": jb.pvalue,
  }

# Autocorrelation Function (ACF)/ Partial Autocorrelation Function (PACF) with explicit lag control for identification test
def acf_pcf_diagnostics(r, nlags=20):
  r = r.dropna()
  acf_vals = acf(r, nlags=nlags, fft=True) #includes lag 0 till lags 20
  pacf_vals = pacf(r, nlags=nlags, method="ywm") #Yule Walker MLE variant
  return {
      "acf_vals": acf_vals,
      "pacf_vals": pacf_vals,
  }

# AIC/BIC test (preferred BIC because of overfitting)
def select_arma_order(r, max_ar=4, max_ma=4):
  y = r.dropna()
  sel = arma_order_select_ic(y, max_ar=max_ar, max_ma=max_ma, ic=["aic", "bic"], trend="c")
  return {
      "aic": sel.aic_min_order,
      "bic": sel.bic_min_order,
      "aic_table": sel.aic,
      "bic_table": sel.bic,
  }

# Autoregressive Moving Average (ARMA)
def fits_arma_and_forecast(r, p=1, q=1):
  model = ARIMA(r.dropna(), order=(p, 0, q))
  res = model.fit()
  mean_1step = float(res.get_forecast(steps=1).predicted_mean.iloc[0])
  return res, mean_1step

# Arch LM Test
def arch_lm(resid, nlags=10, ddof=0): #ddof means degree of freedom
  lm, lm_pvalue, fval, f_pvalue = het_arch(resid.dropna(), nlags=nlags, ddof=ddof)
  return {
      "lm_stat": lm, "lm_pvalue":lm_pvalue,
      "f_stat": fval, "f_pvalue": f_pvalue,
  }

# Liliefors Test
def innovation_checks(z):
  z = np.asarray(z, float)
  z = z[np.isfinite(z)]
  z_std = (z - z.mean()) / z.std(ddof=1)
  jb = jarque_bera(z_std)
  omni = normaltest(z_std)
  lf_stat, lf_p = lilliefors(z, dist="norm", pvalmethod="table")
  return {"jb_value": jb.pvalue, "omni_pvalue": omni.pvalue, "lilliefors_pvalue": lf_p}

# Conditional Variance (AR + GARCH test)
def fit_garch(r):
  am = arch_model(
      r.dropna(),
      mean="AR", lags=1,
      vol="GARCH", p=1, q=1,
      dist="normal"
  )

# Time Series Analysis Stationary Tests
def stationary_panel(x):
  x = x.dropna()
  adf = adfuller(x, regression="c", autolag="AIC")
  kps = kpss(x, regression="c", nlags="auto")
  return {
      "adf_stat": adf[0], "adf_pvalue": adf[1], "adf_usedlag": adf[2],
      "kps_stat": kps[0], "kps_pvalue": kps[1], "kps_usedlag": kps[2],
  }

# Ljung-box Tests
def ljung_box_suite(resid, m=20, model_df=0):
  r = resid.dropna()
  # Standardized Residual
  lb_resid = acorr_ljungbox(r, lags=[m], model_df=model_df, return_df=True)
  # Standardized Residual Squared
  lb_sq = acorr_ljungbox(r**2, lags=[m], model_df=model_df, return_df=True)
  return lb_resid, lb_sq

# CUSUM (Cumulative Sum)
def cusum_stability_test(y, X):
  Xc = sm.add_constant(X, has_constant="add")
  ols = sm.OLS(y, Xc).fit()

  n_params = int(ols.df_model) + int(ols.k_constant)
  sup_b, pvalue, crit = breaks_cusumolsresid(ols.resid, ddof=n_params)

  return {"cusum_stat": sup_b, "pvalue": pvalue, "critical_values": crit}

# PAIR TRADING p(t)

# VAR (Value At Risk) [2 Assets]
def fit_var_and_forecast(df, maxlags=12, h=5): # last 12 days, forecast for the next 5 days
  y = df.dropna()
  model = VAR(y)
  sel = model.select_order(maxlags=maxlags)
  p = int(sel.selected_orders["bic"])
  res = model.fit(p)
  fcst = res.forecast(y.values[-p:], steps=h)
  return res, p, fcst

# Granger Causality [2 Assets]
def check_granger_causality(df, max_lag=4):
  y = df.dropna()
  res = grangercausalitytests(y, maxlag=max_lag, verbose=False)

  p_value = res[max_lag][0]["ssr_ftest"][1]
  return p_value

# Johansen Approach (2 Assets)
def johansen_rank_test(df, det_order=0, k_ar_diff=1):
  y = df.dropna()
  joh = coint_johansen(y, det_order=det_order, k_ar_diff=k_ar_diff)
  return {
    "trace_stat": joh.trace_stat,
    "trace_crit_vals": joh.trace_stat_crit_vals,
    "max_eig_stat": joh.max_eig_stat,
    "max_eig_crit_vals": joh.max_eig_stat_crit_vals,
  }

# Vector Error Correction Model (2 Assets)
def fit_vcm(df, coint_rank=1, k_ar_diff=1, deterministic="co"):
  y = df.dropna()
  model = VECM(
      y,
      k_ar_diff=k_ar_diff,
      coint_rank=coint_rank,
      deterministic=deterministic
  )
  res = model.fit()
  return {"alpha": res.alpha, "beta": res.beta, "resid": res.resid}

# Better VECM Model to fit (2 Assets)
def _det_order(d):
  d = (d or "n").lower()
  if "li" in d or "lo" in d: return 1
  if "ci" in d or "co" in d: return 0
  return -1

def select_vecm_spec(df, maxlags=12, deterministic="co", signif=0.05):
  y = df.dropna()
  sel = select_order(y, maxlags=maxlags, deterministic=deterministic).selected_orders
  k_ar_diff = int(sel.get("bic") or sel.get("aic") or 1)
  rank = select_coint_rank(
      y, det_order=_det_order(deterministic),
      k_ar_diff=k_ar_diff, method="trace", signif=signif
  )
  return {"k_ar_diff": k_ar_diff, "coint_rank": rank.rank}