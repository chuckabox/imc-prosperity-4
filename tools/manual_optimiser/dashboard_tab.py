def render_manual_optimizer_tab():
    """Unified R2 Manual Challenge optimiser — all scenarios, one screen."""
    import numpy as np
    import pandas as pd
    import streamlit as st
    import json as _json

    try:
        import manual_optimiser as mo
        from manual_optimiser import plotting as moplot
        from manual_optimiser import scenarios as moscen
    except Exception as e:
        st.error(f"manual_optimiser import failed: {e}")
        return

    st.subheader("♟️ R2 Manual Challenge Optimiser")
    st.caption(
        "Budget = **50,000 XIRECs**. Each % invested costs **500 XIRECs**. "
        "Constraint: x+y+z ≤ 100. "
        "Net = Research(x) · Scale(y) · Speed(z) − 500·(x+y+z)."
    )

    with st.expander("📖 Pillars — what does each investment do?"):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("""
### Research (x)
**How strong is your edge?**
- Formula: `200,000 · ln(1+x) / ln(101)`
- Grows **logarithmically** 0 → 200k
- x=100 → edge value of 200k
- x=50 → ~124k
- Returns diminish (concave)
- **Insight:** diminishing returns; x ≈ 15-25 captures ~80% of value.
            """)
        with c2:
            st.markdown("""
### Scale (y)
**How many markets deploy across?**
- Formula: `0.07 · y`
- Grows **linearly** 0 → 7
- y=100 → scale multiplier of 7
- y=50 → 3.5x
- No diminishing returns; each % is equal
- **Insight:** scale is where the leverage is. y ≈ 40-50 is cheap PnL.
            """)
        with c3:
            st.markdown("""
### Speed (z)
**How often do you hit your target trades?**
- Formula: **rank-based** across all competitors
- Highest bidder → 0.9× hit rate
- Lowest → 0.1×
- Everyone in between: linear interpolation
- **Insight:** z is a **zero-sum game**. Depends entirely on *what others bid*. That's why we model 7 scenarios.
            """)

    # --- controls ---
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        n_iter = st.slider("MC iterations / scenario", 200, 3000, 1000, 100, key="mopt_iter")
    with c2:
        seed = st.number_input("Seed", 0, 10_000, 42, key="mopt_seed")
    with c3:
        safety_thr = st.slider("Safety speed threshold", 0.1, 0.9, 0.5, 0.05, key="mopt_thr")
    with c4:
        safety_prob = st.slider("Safety probability", 0.80, 0.99, 0.95, 0.01, key="mopt_prob")

    st.info(
        "🎲 **We run 7 scenarios simultaneously**. Each models a different "
        "assumption about how competitors bid speed. Pick the scenario closest to reality, "
        "or use the weighted recommendation to hedge across all."
    )

    # --- run all scenarios ---
    @st.cache_data(show_spinner="Running MC across 7 scenarios…")
    def _run_all(niter, seed_, thr):
        return mo.run_scenarios(
            moscen.ALL_SCENARIOS, n_iter=niter, seed=seed_,
            safety_threshold=thr, safety_prob=safety_prob,
            grid_step=1, max_total=100,
        )

    out = _run_all(int(n_iter), int(seed), float(safety_thr))
    sims = out["sims"]
    optima_per = out["optima"]
    robust = mo.robust_optimum(sims)
    names = list(sims.keys())

    # --- Table: all optima ---
    st.markdown("### 📊 Optimal allocation per scenario")
    rows = []
    for name, opt in optima_per.items():
        for which in ("global", "safety", "p05_max"):
            o = opt.get(which)
            if o is None:
                continue
            a = o["alloc"]
            rows.append({
                "Scenario": name, "Pick": which,
                "x": a[0], "y": a[1], "z": a[2],
                "Total": a[0] + a[1] + a[2],
                "Cost": f"{int(o['cost']):,}",
                "Mean": f"{o['mean_net']:,.0f}",
                "P05": f"{o['p05_net']:,.0f}",
                "Goal": "✅" if o["p05_net"] >= 200_000 else (
                    "⚠️" if o["mean_net"] >= 200_000 else "❌"),
            })
    df_table = pd.DataFrame(rows)
    st.dataframe(df_table, use_container_width=True, hide_index=True)
    st.caption("**Pick** = which optimum: global (max mean), safety (robust to speed variance), p05_max (max worst-case). **Goal** = hits 200k in worst case (✅) or average (⚠️) or misses (❌).")

    # --- Bar chart ---
    st.plotly_chart(
        moplot.scenario_comparison_bars(optima_per, pick_key="safety"),
        use_container_width=True,
    )

    # --- Robust picks ---
    st.markdown("### 🧊 Robust allocations (hedging across all scenarios)")
    rmm = robust["maximin_mean"]
    rmp = robust["maximin_p05"]
    c_robust1, c_robust2 = st.columns(2)
    with c_robust1:
        st.metric(
            "Maximin-Mean",
            f"**x={rmm['alloc'][0]}, y={rmm['alloc'][1]}, z={rmm['alloc'][2]}**",
            f"worst-case mean = {rmm['worst_case_mean_net']:,.0f}",
        )
        st.caption(
            "Allocation that maximizes the **worst mean Net across all 7 scenarios**. "
            "If you don't know which scenario is true, this is your fallback."
        )
        with st.expander("Per-scenario breakdown"):
            r1_df = pd.DataFrame(
                rmm["per_scenario_mean_net"].items(),
                columns=["Scenario", "Mean Net"],
            ).assign(**{"Mean Net": lambda d: d["Mean Net"].round()})
            st.dataframe(r1_df, use_container_width=True, hide_index=True)
    with c_robust2:
        st.metric(
            "Maximin-P05",
            f"**x={rmp['alloc'][0]}, y={rmp['alloc'][1]}, z={rmp['alloc'][2]}**",
            f"worst-case P05 = {rmp['worst_case_p05_net']:,.0f}",
        )
        st.caption(
            "Allocation that maximizes the **worst 5th-percentile Net** across all scenarios. "
            "For ultra-defensive play."
        )
        with st.expander("Per-scenario breakdown"):
            r2_df = pd.DataFrame(
                rmp["per_scenario_p05_net"].items(),
                columns=["Scenario", "P05 Net"],
            ).assign(**{"P05 Net": lambda d: d["P05 Net"].round()})
            st.dataframe(r2_df, use_container_width=True, hide_index=True)

    # --- Weighted recommendation ---
    st.markdown("### 🎯 Weighted Recommendation (your priors)")
    st.caption(
        "You likely don't believe all scenarios equally. "
        "Assign your subjective probability that each is reality. "
        "We return the allocation maximising **probability-weighted expected Net**."
    )

    defaults = {
        "Beta(2,5) - lazy market": 30,
        "Uniform(0,100) - chaos": 5,
        "Bimodal lazy+herd@40": 20,
        "Herd at midrange (mu=50)": 15,
        "Aggressive market (mu=70)": 5,
        "Exponential (scale=15)": 15,
        "Three camps (0/45/85)": 10,
    }
    wcols = st.columns(len(names))
    weights = []
    for i, n in enumerate(names):
        with wcols[i]:
            w = st.number_input(f"{n.split(' ')[0]}", 0, 100, defaults.get(n, 10),
                                key=f"w_{i}", help=n)
        weights.append(float(w))
    wsum = sum(weights) or 1.0
    w = np.array(weights) / wsum

    stacked = np.stack([sims[n]["mean_net"] for n in names])  # (S, G)
    weighted = (w[:, None] * stacked).sum(axis=0)
    wi = int(np.argmax(weighted))
    grid = sims[names[0]]["grid"]
    a = grid[wi]
    cost = 500 * int(a.sum())
    per_scen = {n: float(sims[n]["mean_net"][wi]) for n in names}
    per_scen_p05 = {n: float(sims[n]["p05_net"][wi]) for n in names}

    st.success(
        f"💡 **RECOMMENDED: x={int(a[0])}, y={int(a[1])}, z={int(a[2])}**  \n"
        f"Weighted expected Net = **{weighted[wi]:,.0f}** | Cost = **{cost:,} XIRECs**"
    )
    rec_df = pd.DataFrame({
        "Scenario": names,
        "Prob": [f"{x:.1%}" for x in w],
        "Your Net": [f"{round(per_scen[n]):,}" for n in names],
        "P05 Net": [f"{round(per_scen_p05[n]):,}" for n in names],
        "Target": ["✅" if per_scen_p05[n] >= 200_000 else ("⚠️" if per_scen[n] >= 200_000 else "❌") for n in names],
    })
    st.dataframe(rec_df, use_container_width=True, hide_index=True)

    # --- Inspector: what if I bid x, y, z? ---
    st.markdown("### 🔬 Inspector: test any allocation")
    col_x, col_y, col_z = st.columns(3)
    with col_x:
        cur_x = st.slider("Research x", 0, 100, int(a[0]), key="insp_x",
                          help="Edge strength. Log curve: x≈15-25 captures 80% of 200k ceiling.")
    with col_y:
        cur_y = st.slider("Scale y", 0, 100 - cur_x, int(a[1]), key="insp_y",
                          help="Market breadth. Linear: each % = same marginal value. y≈40-50 is leverage.")
    with col_z:
        cur_z = st.slider("Speed z", 0, 100 - cur_x - cur_y,
                          min(int(a[2]), 100 - cur_x - cur_y), key="insp_z",
                          help="Zero-sum rank game. High z = expect rank boost IF others don't also bid high.")

    total_pct = cur_x + cur_y + cur_z
    cost_actual = 500 * total_pct
    unused = 50_000 - cost_actual
    st.metric(
        "Budget usage",
        f"{total_pct}% of 100% → **{cost_actual:,} XIRECs**",
        f"Unused: {unused:,} XIRECs (partial allocation OK)"
    )

    # Per-scenario lookup
    mask = (grid[:, 0] == cur_x) & (grid[:, 1] == cur_y) & (grid[:, 2] == cur_z)
    if mask.any():
        idx = int(np.where(mask)[0][0])
        insp_rows = []
        for n in names:
            sim = sims[n]
            mn = float(sim["mean_net"][idx])
            p5 = float(sim["p05_net"][idx])
            insp_rows.append({
                "Scenario": n.split(" ")[0],
                "Mean": f"{mn:,.0f}",
                "P05": f"{p5:,.0f}",
                "Status": "✅ SAFE" if p5 >= 200_000 else ("⚠️ RISKY" if mn >= 200_000 else "❌ MISS"),
            })
        st.dataframe(pd.DataFrame(insp_rows), use_container_width=True, hide_index=True)
    else:
        st.warning("That allocation is not on the grid (1% step). Slide to nearby value.")

    # --- Competitor distributions ---
    with st.expander("📈 Competitor markets per scenario"):
        st.caption(
            "Histograms show the *assumed* competitor speed bids under each scenario. "
            "Your red line shows where *you* bid. "
            "If most competitors bid left of you, your speed multiplier is high. If they bid right, low."
        )
        rng = np.random.default_rng(int(seed))
        scenario_tabs = st.tabs(names)
        for i, n in enumerate(names):
            with scenario_tabs[i]:
                pop = moscen.ALL_SCENARIOS[n](rng)
                cA, cB = st.columns(2)
                with cA:
                    st.plotly_chart(
                        moplot.competitor_histogram(pop, your_z=cur_z, title=f"{n} — your bid z={cur_z}"),
                        use_container_width=True,
                    )
                with cB:
                    st.plotly_chart(
                        moplot.speed_curve(pop, highlight_z=cur_z),
                        use_container_width=True,
                    )

    # --- Export ---
    payload = {
        "recommendation": {
            "alloc": [int(v) for v in a],
            "weighted_mean_net": float(weighted[wi]),
            "weights": {n: float(w[i]) for i, n in enumerate(names)},
            "per_scenario_mean_net": {n: float(per_scen[n]) for n in names},
            "per_scenario_p05_net": {n: float(per_scen_p05[n]) for n in names},
        },
        "robust_maximin_mean": robust["maximin_mean"],
        "robust_maximin_p05": robust["maximin_p05"],
        "optima_per_scenario": optima_per,
        "params": {
            "n_iter": int(n_iter), "seed": int(seed),
            "safety_threshold": float(safety_thr),
            "safety_prob": float(safety_prob),
            "budget_total": 50_000, "cost_per_point": 500,
        },
    }
    st.download_button(
        "💾 Download optimum_config.json",
        data=_json.dumps(payload, indent=2, default=str),
        file_name="optimum_config.json",
        mime="application/json",
    )
