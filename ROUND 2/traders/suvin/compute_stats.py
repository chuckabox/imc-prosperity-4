import pandas as pd
import numpy as np
import warnings
import statsmodels.api as sm
import stats_testing as st
import os

warnings.filterwarnings("ignore")

out_path = "stats.md"
with open(out_path, "w") as out:
    def emit(text=""):
        print(text)
        out.write(text + "\n")

    emit("# Comprehensive Statistical Analysis")
    emit("This document provides the results of the requested statistical tests applied to historical data for **INTARIAN_PEPPER_ROOT** and **ASH_COATED_OSMIUM**.")
    emit("\n*(Note: Data is sampled at 1/10th frequency to ensure computational stability for tests like ARMA/GARCH and VAR/VECM)*\n")

    # Load Data
    data_dir = "../../data_capsule"
    files = ["prices_round_2_day_-1.csv", "prices_round_2_day_0.csv", "prices_round_2_day_1.csv"]
    dfs = []
    for f in files:
        path = os.path.join(data_dir, f)
        if os.path.exists(path):
            dfs.append(pd.read_csv(path, sep=";"))

    if not dfs:
        emit("❌ **ERROR:** Data capsule files not found in standard directories.")
        exit(1)

    df = pd.concat(dfs, ignore_index=True)
    if "profit_and_loss" not in df.columns:
        df["profit_and_loss"] = 0.0 # Placeholder if missing

    # Set up symbols
    pep = df[df["product"] == "INTARIAN_PEPPER_ROOT"].copy()
    osm = df[df["product"] == "ASH_COATED_OSMIUM"].copy()
    
    # Sort and downsample
    pep = pep.sort_values(["day", "timestamp"]).reset_index(drop=True).iloc[::10]
    osm = osm.sort_values(["day", "timestamp"]).reset_index(drop=True).iloc[::10]

    # Align indexes
    min_len = min(len(pep), len(osm))
    pep = pep.iloc[:min_len].reset_index(drop=True)
    osm = osm.iloc[:min_len].reset_index(drop=True)

    cols_to_test = [
        "mid_price", "profit_and_loss", "timestamp",
        "bid_price_1", "ask_price_1", "bid_volume_1", "ask_volume_1",
        "bid_price_2", "ask_price_2", "bid_volume_2", "ask_volume_2",
        "bid_price_3", "ask_price_3", "bid_volume_3", "ask_volume_3"
    ]

    def safe_returns(series):
        # We use simple diffs instead of log returns for everything because prices can be zero/neg or timestamp behaves weirdly
        try:
            return st.compute_returns(series)["R(t)"] # Pct change
        except Exception:
            return series.diff().dropna()
            
    def run_tests(s, name):
        emit(f"### {name}")
        emit("| Test | Metric | Value | Interpretation (Graph Type) |")
        emit("| --- | --- | --- | --- |")
        
        # Returns
        r = s.diff().dropna() if s.min() <= 0 else safe_returns(s).dropna()
        if len(r) == 0: r = s.copy()
        
        # Jarque-Bera
        try:
            jb = st.distribution_summary(r)
            emit(f"| Jarque-Bera (returns) | JB Stat  | **{jb['jb_statistic']:.2f}** | Histogram: Tail density assessment |")
            emit(f"| Jarque-Bera (returns) | P-Value | **{jb['jb_pvalue']:.4e}** | Non-normal if < 0.05 |")
        except Exception as e: emit(f"| Jarque-Bera | Error | {e} | |")

        # Stationarity
        try:
            adf = st.stationary_panel(s)
            emit(f"| ADF (level) | P-Value | **{adf['adf_pvalue']:.4e}** | Line Graph: Stationary if < 0.05 |")
            adf_r = st.stationary_panel(r)
            emit(f"| ADF (returns) | P-Value | **{adf_r['adf_pvalue']:.4e}** | Line Graph: Stationary if < 0.05 |")
        except Exception as e: emit(f"| ADF | Error | {e} | |")

        # CUSUM
        try:
            X = np.arange(len(s))
            cusum = st.cusum_stability_test(s.values, X)
            emit(f"| CUSUM (level) | P-Value | **{cusum['pvalue']:.4e}** | Residual Plot: Structural break if < 0.05 |")
        except Exception as e: emit(f"| CUSUM | Error | {e} | |")
        
        # ARMA AIC/BIC
        try:
            sel = st.select_arma_order(r, max_ar=1, max_ma=1)
            emit(f"| ARMA AIC/BIC | Optimal Order | AR:{sel['aic'][0]} MA:{sel['aic'][1]} | ACF/PACF correlograms |")
        except Exception as e: emit(f"| ARMA | Error | {e} | |")

        # Ljung-Box
        try:
            lb, lb_sq = st.ljung_box_suite(r, m=10)
            lb_p = lb['lb_pvalue'].iloc[0]
            emit(f"| Ljung-Box | P-Value | **{lb_p:.4e}** | Line Graph: Autocorrelation present if < 0.05 |")
        except Exception as e: emit(f"| Ljung-Box | Error | {e} | |")

    # 1. Single Asset Tests
    emit("## 1. Single Asset Statistical Diagnostics\n")
    for col in cols_to_test:
        if col not in pep.columns: continue
        emit(f"---\n#### Field: `{col}`")
        s_pep = pep[col].dropna()
        s_osm = osm[col].dropna()
        
        if len(s_pep) > 100:
            run_tests(s_pep, "INTARIAN_PEPPER_ROOT")
        if len(s_osm) > 100:
            run_tests(s_osm, "ASH_COATED_OSMIUM")

    # 2. Pairs Trading Tests
    emit("\n---\n## 2. Pairs Trading Cointegration Diagnostics\n")
    for col in cols_to_test:
        if col not in pep.columns: continue
        
        # Only run pairs test on variables with variance
        if pep[col].std() == 0 or osm[col].std() == 0: continue
        
        emit(f"#### Field Pair: `{col}` (Pepper vs Osmium)\n")
        emit("| Pair Test | Metric | Value | Interpretation (Graph Type) |")
        emit("| --- | --- | --- | --- |")
        
        df_pair = pd.DataFrame({"pep": pep[col], "osm": osm[col]}).dropna()
        try:
            # VAR
            res, p, _ = st.fit_var_and_forecast(df_pair, maxlags=5, h=1)
            emit(f"| VAR (Vector Autoregression) | Optimal Lag (p) | **{p}** | Cross-correlation impact matrix |")
        except Exception as e: emit(f"| VAR | Error | {e} | |")

        try:
            # Granger
            g_p = st.check_granger_causality(df_pair, max_lag=2)
            emit(f"| Granger Causality | P-Value (F-test) | **{g_p:.4e}** | Leading Indicator graph (predictive) |")
        except Exception as e: emit(f"| Granger | Error | {e} | |")

        try:
            # Johansen
            joh = st.johansen_rank_test(df_pair, det_order=0, k_ar_diff=1)
            trace = joh['trace_stat'][0]
            crit = joh['trace_crit_vals'][0][1] # 5% critical value
            emit(f"| Johansen Cointegration | Trace Statistic | **{trace:.2f} (Crit: {crit:.2f})** | Cointegrated spread plot |")
        except Exception as e: emit(f"| Johansen | Error | {e} | |")
        
        try:
            # VECM Specification
            v_spec = st.select_vecm_spec(df_pair, maxlags=5, deterministic="co")
            emit(f"| Better VECM Select | Coint Rank / AR Diff | Rank: {v_spec['coint_rank']}, AR: {v_spec['k_ar_diff']} | Spread reversion curve |")
        except Exception as e: emit(f"| VECM Select | Error | {e} | |")
        
        emit("\n")

    emit("\n## Final Interpretation Summary")
    emit("- **Stationarity**: Strong stationarity (ADF < 0.05) implies the variables revert to a mean. Essential for passive market making.")
    emit("- **Cointegration**: If Johansen Trace > Critical Value, the assets move together, confirming the pairs trade strategy capability.")
    emit("- **Granger Causality**: Suggests movements in the field for one asset can reliably predict the next tick of the other asset.")
