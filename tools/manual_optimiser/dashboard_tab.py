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

    # ========== HEADER & COST INFO ==========
    st.subheader("♟️ R2 Manual Challenge Optimiser")

    # Cost & Goal Summary
    cap_col, target_col, need_col = st.columns(3)
    with cap_col:
        st.metric("📊 Current", "**173,000** XIRECs", "")
    with target_col:
        st.metric("🎯 Target", "**200,000** XIRECs", "")
    with need_col:
        st.metric("💰 Shortfall", "**27,000** XIRECs", "Profit needed")

    st.caption(
        "**Budget = 50,000 XIRECs**. Don't use it all if risk isn't worth it. "
        "Each % allocated costs 500 XIRECs. Net PnL = Research × Scale × Speed − Cost."
    )

    with st.expander("📖 Pillars — what does each investment do?"):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("""
### Research (x) — Edge Strength 📈
**Your algorithm's quality**
- Formula: `200k · ln(1+x) / ln(101)`
- Grows **logarithmically** 0 → 200k at x=100
- x=50 → 124k | x=25 → 79k | x=10 → 33k
- **Diminishing returns:** each % adds less value
- **Insight:** x ≈ 15–25 captures ~80% of edge ceiling. Going 0→25 is worth 2x more than 75→100.
            """)
        with c2:
            st.markdown("""
### Scale (y) — Market Breadth 📊
**How many products you trade**
- Formula: `0.07 · y` (pure multiplier)
- Grows **perfectly linear** 0 → 7× at y=100
- y=50 → 3.5× | y=30 → 2.1× | y=10 → 0.7×
- **No diminishing returns:** all % equal value
- **Insight:** Scale is leverage. Y ≈ 40–50 is efficient. Multiplies your edge by 3.5–3.5×.
            """)
        with c3:
            st.markdown("""
### Speed (z) — Execution Rank 🏃
**Your speed vs competitors**
- Formula: **Rank-based** [0.1× to 0.9×]
- Bid z=80 but only 20% of field bids >80 → you get ~0.78×
- Bid z=10 and 90% bid >10 → you get ~0.18×
- **Zero-sum game:** others' bids directly hurt you
- **Insight:** Depends on scenario. Z is uncertain. Highest ROI variance.
            """)

    # ========== CONTROLS WITH INFO BUBBLES ==========
    st.subheader("⚙️ Simulation Parameters")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        n_iter = st.slider(
            "MC iterations / scenario", 200, 3000, 1000, 100,
            key="mopt_iter",
            help="How many samples per scenario to test allocation. Higher = more accurate but slower. 1000 ≈ balanced."
        )
    with c2:
        seed = st.number_input(
            "Seed", 0, 10_000, 42,
            key="mopt_seed",
            help="Random seed for competitor population. Same seed = reproducible results. Change to test different market conditions."
        )
    with c3:
        safety_thr = st.slider(
            "Speed threshold", 0.1, 0.9, 0.5, 0.05,
            key="mopt_thr",
            help="Min speed multiplier you want. E.g., 0.5 = 'I want ≥50% execution rate even in worst case.'"
        )
    with c4:
        safety_prob = st.slider(
            "Safety probability", 0.80, 0.99, 0.95, 0.01,
            key="mopt_prob",
            help="Confidence level. 95% = 'I want 95% chance of hitting speed threshold.' Higher = safer but lower profit."
        )

    # ========== SCENARIO EXPLANATIONS ==========
    with st.expander("🎲 The 7 Scenarios — What Does Each Mean?", expanded=True):
        st.caption(
            "We test your allocation against **7 different competitor speed distributions**. "
            "Each assumes competitors bid **differently** on speed. You don't know which is real, "
            "so we show results for all. Your job: pick the scenario closest to reality, or hedge across all."
        )

        scen_cols = st.columns(2)
        with scen_cols[0]:
            st.markdown("""
#### 🦥 **Beta(2,5) — Lazy Market** (default)
Most competitors bid low (0–20), few go high.
- Math: Beta distribution skewed left
- Real-world: Early competition, casual players, newcomers
- Your advantage: Your higher bid (z=50) beats 85% of field
- **Good scenario for:** aggressive speed bids
- *Recommended belief: 30%*

#### 🎰 **Uniform(0,100) — Chaos**
Everyone bids **evenly 0 to 100**. No pattern.
- Math: Random, flat
- Real-world: Unpredictable market, no consensus
- Your advantage: Minimal. You're just average.
- **Good for:** defensive allocations
- *Recommended belief: 5%*

#### 🐑 **Bimodal Lazy+Herd@40**
40% bid ~0 (newcomers), 60% cluster at 40 (copy-cats).
- Math: Two peaks
- Real-world: Split market—casuals vs experienced
- Your advantage: Depends on if you're above or below 40
- **Good for:** middle-ground z values (30–50)
- *Recommended belief: 20%*
            """)

        with scen_cols[1]:
            st.markdown("""
#### 👥 **Herd at Midrange (μ=50)**
Everyone clusters around **50** (obvious answer).
- Math: Normal distribution, center=50
- Real-world: Coordinated market, shared expectation
- Your advantage: Low if you bid ~50, high if you deviate
- **Good for:** testing edge cases
- *Recommended belief: 15%*

#### 🔥 **Aggressive Market (μ=70)**
Bidding war. Most invest heavily in speed, cluster ~70.
- Math: Normal distribution, center=70
- Real-world: Competitive late-stage, arms race
- Your advantage: Low unless you bid >70 (expensive!)
- **Good for:** risk-testing where you might lose speed
- *Recommended belief: 5%*

#### 📈 **Exponential (scale=15)**
Many bid low (0–20), **long tail** up to 100. Heavy skew.
- Math: Exponential decay
- Real-world: Power law—few mega-spenders, many frugal
- Your advantage: Moderate; similar to Beta but worse tail
- **Good for:** "tail risk" testing
- *Recommended belief: 15%*

#### ⛺ **Three Camps (0 / 45 / 85)**
Exactly **25% bid ~0, 50% bid ~45, 25% bid ~85**.
- Math: Three distinct clusters
- Real-world: Market segmentation—casuals / pros / whales
- Your advantage: Depends hard on your z choice
- **Good for:** discrete scenario testing
- *Recommended belief: 10%*
            """)

        st.info(
            "📌 **Seed** controls the random sample of competitors. Same seed = same population every time. "
            "Change seed to see different random markets, stress-test your allocation.\n\n"
            "💡 **Recommended** belief sums to 100%. Adjust them based on *your* view of market reality. "
            "We'll compute the allocation that maximizes expected profit weighted by your beliefs."
        )

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
    st.markdown("### 📊 Optimal allocations per scenario (3 strategies each)")

    st.markdown("""
**Strategy #1: Global** 🎲
Maximizes average profit. Best case expected value.
Use when: You're confident in your edge and can afford variance.

**Strategy #2: Safety** 🛡️
Robust to speed variance. Targets your safety threshold (95% chance of hitting speed limit).
Use when: You want to minimize downside risk while still chasing upside.

**Strategy #3: P05-Max** ⛑️
Maximizes worst-case (5th percentile). Most conservative.
Use when: You need to guarantee 200k hit even in worst market.
    """)

    rows = []
    for name, opt in optima_per.items():
        for which in ("global", "safety", "p05_max"):
            o = opt.get(which)
            if o is None:
                continue
            a = o["alloc"]
            rows.append({
                "Scenario": name.split("(")[0].strip(), "Strategy": which.replace("_", "-"),
                "x": int(a[0]), "y": int(a[1]), "z": int(a[2]),
                "Total%": int(a[0] + a[1] + a[2]),
                "Cost": f"{int(o['cost']):,}",
                "Mean PnL": f"{o['mean_net']:,.0f}",
                "P05 PnL": f"{o['p05_net']:,.0f}",
                "Status": "✅ SAFE" if o["p05_net"] >= 200_000 else (
                    "⚠️ RISKY" if o["mean_net"] >= 200_000 else "❌ MISS"),
            })
    df_table = pd.DataFrame(rows)
    st.dataframe(df_table, use_container_width=True, hide_index=True)
    st.caption(
        "**Total%** = x+y+z (allocation %). "
        "**Cost** = 500 × Total%. "
        "**Mean/P05** = expected PnL. "
        "**Status** = ✅ P05≥200k (safe) | ⚠️ Mean≥200k (lucky) | ❌ misses"
    )

    # --- Bar chart ---
    st.plotly_chart(
        moplot.scenario_comparison_bars(optima_per, pick_key="safety"),
        use_container_width=True,
    )

    # --- Robust picks ---
    st.markdown("### 🧊 Robust allocations (hedge against all scenarios equally)")

    st.markdown("""
**Maximin Strategy:** "Expect the worst."
Find the allocation that protects you against your worst-case scenario.
If market turns out to be any scenario, you still get decent profit.
**When to use:** You're totally uncertain which scenario is real. Want insurance.
    """)

    rmm = robust["maximin_mean"]
    rmp = robust["maximin_p05"]
    c_robust1, c_robust2 = st.columns(2)
    with c_robust1:
        st.markdown("#### **Maximin-Mean** 📊")
        st.metric(
            "Best allocation for worst scenario (mean)",
            f"**x={rmm['alloc'][0]}, y={rmm['alloc'][1]}, z={rmm['alloc'][2]}**",
            f"Worst-case mean across 7 scenarios = {rmm['worst_case_mean_net']:,.0f}",
        )
        st.caption(
            "Picks x,y,z such that even if market is in your worst scenario, "
            "average outcome is highest. Balanced offensive-defensive."
        )
        with st.expander("Per-scenario Mean breakout"):
            r1_df = pd.DataFrame(
                rmm["per_scenario_mean_net"].items(),
                columns=["Scenario", "Mean Net"],
            ).assign(**{"Mean Net": lambda d: d["Mean Net"].round().astype(int).apply(lambda x: f"{x:,}")})
            st.dataframe(r1_df, use_container_width=True, hide_index=True)
    with c_robust2:
        st.markdown("#### **Maximin-P05** ⛑️")
        st.metric(
            "Best allocation for worst scenario (worst 5%)",
            f"**x={rmp['alloc'][0]}, y={rmp['alloc'][1]}, z={rmp['alloc'][2]}**",
            f"Worst-case P05 across 7 scenarios = {rmp['worst_case_p05_net']:,.0f}",
        )
        st.caption(
            "Ultra-conservative. Picks x,y,z to guarantee you hit even worst 5% outcome "
            "across all 7 scenarios. Maximum downside protection."
        )
        with st.expander("Per-scenario P05 breakout"):
            r2_df = pd.DataFrame(
                rmp["per_scenario_p05_net"].items(),
                columns=["Scenario", "P05 Net"],
            ).assign(**{"P05 Net": lambda d: d["P05 Net"].round().astype(int).apply(lambda x: f"{x:,}")})
            st.dataframe(r2_df, use_container_width=True, hide_index=True)

    # --- Weighted recommendation ---
    st.markdown("### 🎯 Weighted Recommendation (your subjective beliefs)")
    st.caption(
        "You can't know which scenario is real. Assign % beliefs that each is true. "
        "Example: If you think lazy market is 40% likely, chaos is 10%, etc., adjust sliders. "
        "We compute the allocation that **maximizes expected profit weighted by your beliefs**."
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

    st.info(
        "🧠 **How to set beliefs:**\n"
        "- Do you think early competition is lazy? Raise Beta(2,5).\n"
        "- Do you expect a coordinated middle ground? Raise Herd@50.\n"
        "- Do you fear an arms race? Raise Aggressive(70).\n"
        "- Default = even spread. Fine if unsure. Values must sum to 100."
    )

    wcols = st.columns(len(names))
    weights = []
    for i, n in enumerate(names):
        with wcols[i]:
            w = st.number_input(
                f"{n.split(' ')[0]}", 0, 100, defaults.get(n, 10),
                key=f"w_{i}",
                help=f"What % chance that {n.lower()} is the true market condition?"
            )
        weights.append(float(w))
    wsum = sum(weights) or 1.0
    w = np.array(weights) / wsum

    if not np.isclose(wsum, 100):
        st.warning(f"Beliefs sum to {wsum:.0f}%. Adjusting to normalize...")

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
    st.caption(
        "This allocation maximizes expected profit given your belief distribution. "
        "Adjust beliefs and re-run to see how sensitive the recommendation is."
    )

    rec_df = pd.DataFrame({
        "Scenario": names,
        "Your Belief": [f"{x:.1%}" for x in w],
        "Mean Net": [f"{round(per_scen[n]):,}" for n in names],
        "P05 Net": [f"{round(per_scen_p05[n]):,}" for n in names],
        "Goal": ["✅ SAFE" if per_scen_p05[n] >= 200_000 else ("⚠️ RISKY" if per_scen[n] >= 200_000 else "❌ MISS") for n in names],
    })
    st.dataframe(rec_df, use_container_width=True, hide_index=True)

    # --- Inspector: what if I bid x, y, z? ---
    st.markdown("### 🔬 Inspector: test any allocation & see cost/profit math")
    col_x, col_y, col_z = st.columns(3)
    with col_x:
        cur_x = st.slider(
            "Research x", 0, 100, int(a[0]), key="insp_x",
            help="Edge strength (log curve). x=0→0k, x=25→79k, x=50→124k, x=100→200k. Best ROI at low x."
        )
    with col_y:
        cur_y = st.slider(
            "Scale y", 0, 100 - cur_x, int(a[1]), key="insp_y",
            help="Market multiplier (linear). y=10→0.7×, y=30→2.1×, y=50→3.5×, y=100→7×. Leverage play."
        )
    with col_z:
        cur_z = st.slider(
            "Speed z", 0, 100 - cur_x - cur_y,
            min(int(a[2]), 100 - cur_x - cur_y), key="insp_z",
            help="Rank multiplier. Depends on scenario. z=50 vs lazy market→0.8×, vs aggressive→0.3×."
        )

    # ========== COST & PROFIT BREAKDOWN ==========
    total_pct = cur_x + cur_y + cur_z
    cost_actual = 500 * total_pct
    unused_budget = 50_000 - cost_actual

    # Show budget usage
    budget_col1, budget_col2, budget_col3, budget_col4 = st.columns(4)
    with budget_col1:
        st.metric("Allocation %", f"{total_pct}%", f"of 100%")
    with budget_col2:
        st.metric("Cost (XIRECs)", f"{cost_actual:,}", f"of 50,000")
    with budget_col3:
        pct_used = int(100 * cost_actual / 50_000)
        st.metric("Budget Used", f"{pct_used}%", f"Room: {unused_budget:,} XIRECs")
    with budget_col4:
        st.metric("Risk Level", "🟢 LOW" if total_pct <= 30 else ("🟡 MID" if total_pct <= 60 else "🔴 HIGH"),
                  help="LOW=conservative | MID=balanced | HIGH=aggressive")

    # Profitability math
    st.markdown("#### 💡 Profitability Math")
    profit_cols = st.columns(4)

    with profit_cols[0]:
        st.write(f"**Cost to allocate:** {cost_actual:,} XIRECs")
        st.caption(f"You spend {cost_actual:,} to pursue this allocation")

    with profit_cols[1]:
        breakeven_profit = cost_actual
        st.write(f"**Breakeven profit:** {breakeven_profit:,} XIRECs")
        st.caption(f"Need {breakeven_profit:,} to stay at 173k")

    with profit_cols[2]:
        extra_for_target = 27_000
        total_profit_needed = cost_actual + extra_for_target
        st.write(f"**Profit for 200k:** {total_profit_needed:,} XIRECs")
        st.caption(f"Need {total_profit_needed:,} to hit 200k target")

    with profit_cols[3]:
        margin = "Good margin" if total_profit_needed <= 80_000 else ("Tight" if total_profit_needed <= 120_000 else "High risk")
        st.write(f"**Feasibility:** {margin}")
        st.caption(f"Is {total_profit_needed:,} realistic? See scenarios below.")

    st.markdown(
        f"""
**📌 Your profit math:** If you allocate {total_pct}%, you pay {cost_actual:,} XIRECs.
To reach 200k, you need gross PnL of **≥{total_profit_needed:,}** (cost + target delta).
Check the scenarios below to see your mean/P05 across all market conditions.
        """.strip()
    )

    # Per-scenario lookup
    st.markdown("#### 📊 Per-Scenario Results for x={}, y={}, z={}".format(cur_x, cur_y, cur_z))
    st.caption(
        "**Mean** = average profit across all 1000 market simulations. "
        "**P05** = worst 5% of outcomes (95% of time you'll do better). "
        "**Status**: ✅ P05≥200k (you're safe) | ⚠️ Mean≥200k (you're lucky) | ❌ Miss (too risky)"
    )

    mask = (grid[:, 0] == cur_x) & (grid[:, 1] == cur_y) & (grid[:, 2] == cur_z)
    if mask.any():
        idx = int(np.where(mask)[0][0])
        insp_rows = []
        for n in names:
            sim = sims[n]
            mn = float(sim["mean_net"][idx])
            p5 = float(sim["p05_net"][idx])

            # Determine status
            if p5 >= 200_000:
                status_icon = "✅ SAFE"
            elif mn >= 200_000:
                status_icon = "⚠️ RISKY"
            else:
                status_icon = "❌ MISS"

            insp_rows.append({
                "Scenario": n.split(" ")[0],
                "Mean Net": f"{mn:,.0f}",
                "P05 Net": f"{p5:,.0f}",
                "Status": status_icon,
            })

        df_insp = pd.DataFrame(insp_rows)
        st.dataframe(df_insp, use_container_width=True, hide_index=True)

        # Summary row
        avg_mean = np.mean([float(sims[n]["mean_net"][idx]) for n in names])
        avg_p05 = np.mean([float(sims[n]["p05_net"][idx]) for n in names])
        st.markdown(
            f"**Across all 7 scenarios:** "
            f"Average Mean = {avg_mean:,.0f} | Average P05 = {avg_p05:,.0f}"
        )

        safe_count = sum(1 for n in names if float(sims[n]["p05_net"][idx]) >= 200_000)
        risky_count = sum(1 for n in names if float(sims[n]["mean_net"][idx]) >= 200_000 and float(sims[n]["p05_net"][idx]) < 200_000)
        miss_count = len(names) - safe_count - risky_count

        st.markdown(
            f"**Verdict:** {safe_count}/7 scenarios are **safe** (P05≥200k), "
            f"{risky_count} are **risky** (mean≥200k), {miss_count} **miss** target."
        )
    else:
        st.warning("That allocation is not on the grid (1% step). Slide to nearby value.")

    # --- Competitor distributions ---
    with st.expander("📈 Competitor speed distributions (histogram per scenario)"):
        st.caption(
            "**Left graph:** Histogram of competitor speed bids. Your red line shows where you bid (z={cur_z}). "
            "**Right graph:** Speed multiplier curve. Point at z={cur_z} shows your expected multiplier. "
            "**Key insight:** If you bid z=50 in lazy market, 85% bid lower → you get 0.8×. "
            "Same z=50 in aggressive market? Only 15% bid lower → you get 0.3×. That's why scenarios matter."
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
                # Add interpretation
                if len(pop) > 0:
                    pct_lower = 100 * (pop < cur_z).sum() / len(pop)
                    multiplier_est = 0.9 - 0.8 * (1.0 - pct_lower / 100.0)
                    st.markdown(
                        f"💡 In **{n.split(' ')[0]}**: {pct_lower:.0f}% of competitors bid < {cur_z}. "
                        f"Your estimated speed multiplier ≈ {multiplier_est:.2f}×"
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
