def render_manual_optimizer_tab():
    """Unified R2 Manual Challenge optimiser — simple + advanced modes."""
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

    # ========== HEADER & MODE TOGGLE ==========
    st.subheader("♟️ R2 Manual Challenge Optimiser")

    cap_col, target_col, need_col, mode_col = st.columns([2, 2, 2, 2])
    with cap_col:
        st.metric("📊 Current", "**173,000** XIRECs", "")
    with target_col:
        st.metric("🎯 Target", "**200,000** XIRECs", "")
    with need_col:
        st.metric("💰 Shortfall", "**27,000** XIRECs", "Profit needed")
    with mode_col:
        mode = st.radio("Mode", ["🟢 Simple", "⚙️ Advanced"], horizontal=True, key="opt_mode", label_visibility="collapsed")

    # ========== SHARED SETUP ==========
    @st.cache_data(show_spinner=False)
    def _get_sim_data(niter, seed_, thr):
        return mo.run_scenarios(
            moscen.ALL_SCENARIOS, n_iter=niter, seed=seed_,
            safety_threshold=thr, safety_prob=0.95,
            grid_step=1, max_total=100,
        )

    if mode == "🟢 Simple":
        render_simple_mode(_get_sim_data)
    else:
        render_advanced_mode(_get_sim_data)


# ============================================================================
# SIMPLE MODE — 3 presets, clear winners, no confusion
# ============================================================================
def render_simple_mode(get_sim_data):
    """Simple mode: just show 3 preset allocations."""
    import numpy as np
    import pandas as pd
    import streamlit as st

    st.markdown("---")
    st.markdown("""
    ## 🎯 Analyst Recommendations
    Based on your state: 173k → 200k (need +27k profit)
    """)

    # Show budget vs profit analysis
    budget_data = {
        "Spend": ["15,000", "30,000", "40,000", "50,000"],
        "Alloc": ["(8,18,4)", "(13,36,11)", "(16,46,18)", "(14,41,45)"],
        "Est Profit": ["8k", "40k", "74k", "131k"],
        "Hits 200k": ["0/8 ❌", "0/8 ❌", "1/8 ⚠️", "3/8 ✅"],
    }
    st.dataframe(pd.DataFrame(budget_data), use_container_width=True, hide_index=True)

    st.info(
        "💡 **Key insight:** Partial budgets (15-40k) won't hit target. "
        "You NEED to commit **50k** to have a real shot at 200k. "
        "Allocation (14,41,45) hits 200k in lazy/bimodal/exponential scenarios (3/8 most likely)."
    )

    st.markdown("""
    ## Pick Your Strategy
    **3 allocations tested across all 8 scenarios. No sliders, no confusion.**
    """)

    # Controls
    c1, c2, c3 = st.columns(3)
    with c1:
        n_iter = st.slider("Simulations", 200, 2000, 800, 100, key="simple_iter",
                          help="Higher = more accurate. 800 is balanced.")
    with c2:
        seed = st.number_input("Seed", 0, 10000, 42, key="simple_seed",
                              help="Change to test different market conditions.")
    with c3:
        safety_thr = st.slider("Safety threshold", 0.1, 0.9, 0.5, 0.1, key="simple_thr",
                              help="Min speed you want (0.5 = 50% execution)")

    # Run simulations
    out = get_sim_data(int(n_iter), int(seed), float(safety_thr))
    sims = out["sims"]
    names = list(sims.keys())
    grid = sims[names[0]]["grid"]

    # TOP RECOMMENDATION SECTION
    st.markdown("---")
    st.markdown("## ⭐ Top Analyst Picks (Ranked)")

    rec_cols = st.columns(3)

    with rec_cols[0]:
        st.markdown("""
        ### #1 — 🟢 BEST EXPECTED VALUE
        **Allocation:** x=14, y=41, z=45
        - **Cost:** 50,000 XIRECs
        - **Hits 200k in:** 3/8 scenarios ✅
        - **Worst case:** −3k (Aggressive market)
        - **Best case:** +240k (Exponential)

        **Pick this if:** You believe lazy/casual markets dominate.
        """)
        if st.button("Use This →", key="rec_1"):
            st.session_state.simple_inspect = "⭐ Analyst #1"

    with rec_cols[1]:
        st.markdown("""
        ### #2 — 🛡️ SAFEST PLAY
        **Allocation:** x=23, y=77, z=0
        - **Cost:** 50,000 XIRECs
        - **Hits 200k in:** 0/8 (lands ~197k)
        - **Worst case:** +24k (always profitable)
        - **Best case:** +35k (Bimodal)

        **Pick this if:** You want guaranteed no-loss.
        """)
        if st.button("Use This →", key="rec_2"):
            st.session_state.simple_inspect = "⭐ Analyst #2"

    with rec_cols[2]:
        st.markdown("""
        ### #3 — 💰 BUDGET-CONSCIOUS
        **Allocation:** x=16, y=46, z=18
        - **Cost:** 40,000 XIRECs (save 10k)
        - **Hits 200k in:** 1/8 (Exponential only)
        - **Worst case:** −350 (Aggressive)
        - **Best case:** +221k (Exponential)

        **Pick this if:** You want flexibility & believe Exponential.
        """)
        if st.button("Use This →", key="rec_3"):
            st.session_state.simple_inspect = "⭐ Analyst #3"

    st.markdown("---")
    st.markdown("## Or choose from preset templates below:")

    # Define 3 presets
    presets = {
        "🚀 Aggressive": {"x": 30, "y": 50, "z": 20, "desc": "Max profit. Higher risk."},
        "⚖️ Balanced": {"x": 25, "y": 35, "z": 40, "desc": "Good profit + safety. Recommended."},
        "🛡️ Conservative": {"x": 15, "y": 25, "z": 10, "desc": "Safest. Lower cost, less profit."},
    }

    # Evaluate all 3 against all scenarios
    results = {}
    for preset_name, alloc in presets.items():
        x, y, z = alloc["x"], alloc["y"], alloc["z"]
        cost = 500 * (x + y + z)
        results[preset_name] = {
            "alloc": (x, y, z),
            "cost": cost,
            "per_scenario": {},
        }

        for scen_name in names:
            sim = sims[scen_name]
            mask = (grid[:, 0] == x) & (grid[:, 1] == y) & (grid[:, 2] == z)
            if mask.any():
                idx = int(np.where(mask)[0][0])
                mean_net = float(sim["mean_net"][idx])
                p05_net = float(sim["p05_net"][idx])
            else:
                mean_net = p05_net = 0.0

            results[preset_name]["per_scenario"][scen_name] = {
                "mean": mean_net,
                "p05": p05_net,
            }

    # Display 3 columns
    cols = st.columns(3)
    for col_idx, (preset_name, data) in enumerate(presets.items()):
        with cols[col_idx]:
            x, y, z = data["x"], data["y"], data["z"]
            cost = results[preset_name]["cost"]
            per_scen = results[preset_name]["per_scenario"]

            # Header
            st.markdown(f"### {preset_name}")
            st.caption(data["desc"])

            # Allocation & Cost
            st.markdown(f"**Allocation:** x={x} | y={y} | z={z}")
            st.markdown(f"**Cost:** {cost:,} XIRECs (of 50,000)")

            # Safety count
            safe_count = sum(1 for v in per_scen.values() if v["p05"] >= 200_000)
            risky_count = sum(1 for v in per_scen.values() if v["mean"] >= 200_000 and v["p05"] < 200_000)
            miss_count = len(per_scen) - safe_count - risky_count

            if safe_count >= 6:
                verdict = "✅ SAFE"
            elif risky_count >= 4:
                verdict = "⚠️ RISKY"
            else:
                verdict = "❌ MISS"

            st.markdown(f"**Verdict:** {verdict}")
            st.caption(f"{safe_count}/8 safe | {risky_count} risky | {miss_count} miss")

            # Mini table
            rows = []
            for scen_name in names:
                v = per_scen[scen_name]
                rows.append({
                    "Scenario": scen_name.split("(")[0][:12],
                    "Mean": f"{v['mean']:,.0f}",
                    "P05": f"{v['p05']:,.0f}",
                })
            mini_df = pd.DataFrame(rows)
            st.dataframe(mini_df, use_container_width=True, hide_index=True, height=250)

            # Button to inspect
            if st.button(f"📊 Details", key=f"simple_details_{preset_name}"):
                st.session_state.simple_inspect = preset_name

    # Detailed inspector if clicked
    if "simple_inspect" in st.session_state and st.session_state.simple_inspect:
        preset_name = st.session_state.simple_inspect

        # Handle analyst recommendations
        analyst_picks = {
            "⭐ Analyst #1": (14, 41, 45),
            "⭐ Analyst #2": (23, 77, 0),
            "⭐ Analyst #3": (16, 46, 18),
        }

        if preset_name in analyst_picks:
            x, y, z = analyst_picks[preset_name]
            cost = 500 * (x + y + z)
            # Find in grid and get results
            mask = (grid[:, 0] == x) & (grid[:, 1] == y) & (grid[:, 2] == z)
            if mask.any():
                idx = int(np.where(mask)[0][0])
                per_scen = {}
                for scen_name in names:
                    sim = sims[scen_name]
                    per_scen[scen_name] = {
                        "mean": float(sim["mean_net"][idx]),
                        "p05": float(sim["p05_net"][idx]),
                    }
                results[preset_name] = {"cost": cost, "per_scenario": per_scen}
        else:
            alloc_data = presets[preset_name]
            x, y, z = alloc_data["x"], alloc_data["y"], alloc_data["z"]
            cost = results[preset_name]["cost"]

        st.markdown("---")
        st.markdown(f"## 📋 Details: {preset_name}")

        # Profit math
        profit_needed = cost + 27_000
        st.info(
            f"**Cost to allocate:** {cost:,} XIRECs  \n"
            f"**Breakeven:** Need {cost:,} profit to stay at 173k  \n"
            f"**To hit 200k:** Need {profit_needed:,} gross profit"
        )

        # Per-scenario table
        per_scen = results[preset_name]["per_scenario"]
        rows = []
        for scen_name in names:
            v = per_scen[scen_name]
            status = "✅ SAFE" if v["p05"] >= 200_000 else ("⚠️ RISKY" if v["mean"] >= 200_000 else "❌ MISS")
            rows.append({
                "Scenario": scen_name,
                "Mean": f"{v['mean']:,.0f}",
                "P05": f"{v['p05']:,.0f}",
                "Status": status,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        avg_mean = np.mean([v["mean"] for v in per_scen.values()])
        avg_p05 = np.mean([v["p05"] for v in per_scen.values()])
        st.markdown(f"**Average across all scenarios:** Mean={avg_mean:,.0f} | P05={avg_p05:,.0f}")


# ============================================================================
# ADVANCED MODE — Full control, all options
# ============================================================================
def render_advanced_mode(get_sim_data):
    """Advanced mode: detailed sliders, weighted beliefs, scenario selection."""
    import numpy as np
    import pandas as pd
    import streamlit as st
    import manual_optimiser as mo
    from manual_optimiser import scenarios as moscen

    st.markdown("---")

    # Controls
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        n_iter = st.slider("MC iterations", 200, 3000, 1000, 100, key="adv_iter")
    with c2:
        seed = st.number_input("Seed", 0, 10_000, 42, key="adv_seed")
    with c3:
        safety_thr = st.slider("Safety threshold", 0.1, 0.9, 0.5, 0.05, key="adv_thr")
    with c4:
        st.slider("Safety probability", 0.80, 0.99, 0.95, 0.01, key="adv_prob")

    with st.expander("📖 How the 3 pillars work"):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("""
**Research (x)** — Edge strength.
- Formula: 200k × ln(1+x)/ln(101)
- x=10 → 33k | x=25 → 79k | x=50 → 124k
- **Diminishing returns** (log curve)
- Insight: x=15-25 captures 80%
            """)
        with c2:
            st.markdown("""
**Scale (y)** — Market breadth.
- Formula: 0.07 × y
- y=10 → 0.7× | y=50 → 3.5× | y=100 → 7×
- **Linear**: all % equal value
- Insight: y=40-50 is efficient
            """)
        with c3:
            st.markdown("""
**Speed (z)** — Execution rank.
- Rank-based [0.1× to 0.9×]
- **Zero-sum**: depends on competitors
- Varies by scenario
- Insight: Most uncertain, most variance
            """)

    out = get_sim_data(int(n_iter), int(seed), float(safety_thr))
    sims = out["sims"]
    optima_per = out["optima"]
    robust = mo.robust_optimum(sims)
    names = list(sims.keys())
    grid = sims[names[0]]["grid"]

    # ========== SECTIONS ==========
    st.divider()
    st.markdown("## 🔍 Inspector — Test Any Allocation")
    st.markdown("### Test any allocation")

    col_x, col_y, col_z = st.columns(3)
    with col_x:
        cur_x = st.slider("Research x", 0, 100, 25, key="adv_x",
                        help="x=0→0k, x=25→79k, x=50→124k, x=100→200k")
    with col_y:
        remaining_y_max = 100 - cur_x
        cur_y = st.slider("Scale y", 0, remaining_y_max, min(35, remaining_y_max), key="adv_y",
                        help="Linear growth. y=50→3.5× multiplier")
    with col_z:
        remaining_z_max = 100 - cur_x - cur_y
        cur_z = st.slider("Speed z", 0, remaining_z_max, min(40, remaining_z_max), key="adv_z",
                        help="Depends entirely on competitors' bids")

    total_pct = cur_x + cur_y + cur_z
    cost_actual = 500 * total_pct
    unused_budget = 50_000 - cost_actual

    # Cost breakdown
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Allocation %", f"{total_pct}%", "of 100%")
    with m2:
        st.metric("Cost (XIRECs)", f"{cost_actual:,}", f"of 50,000")
    with m3:
        pct_used = int(100 * cost_actual / 50_000) if cost_actual > 0 else 0
        st.metric("Budget Used", f"{pct_used}%", f"Unused: {unused_budget:,}")
    with m4:
        risk = "🟢 LOW" if total_pct <= 30 else ("🟡 MID" if total_pct <= 60 else "🔴 HIGH")
        st.metric("Risk Level", risk, "")

    # Profitability math
    st.markdown("#### 💡 Profitability Math")
    profit_cols = st.columns(4)
    with profit_cols[0]:
        st.write(f"**Cost:** {cost_actual:,} XIRECs")
    with profit_cols[1]:
        st.write(f"**Breakeven:** {cost_actual:,}")
        st.caption("to stay at 173k")
    with profit_cols[2]:
        total_needed = cost_actual + 27_000
        st.write(f"**For 200k:** {total_needed:,}")
        st.caption("needed profit")
    with profit_cols[3]:
        feasibility = "Easy" if total_needed <= 60_000 else ("Tight" if total_needed <= 100_000 else "Hard")
        st.write(f"**Feasibility:** {feasibility}")

    # Per-scenario results
    st.markdown("#### 📊 Results across 8 scenarios")
    mask = (grid[:, 0] == cur_x) & (grid[:, 1] == cur_y) & (grid[:, 2] == cur_z)
    if mask.any():
        idx = int(np.where(mask)[0][0])
        rows = []
        for n in names:
            sim = sims[n]
            mn = float(sim["mean_net"][idx])
            p5 = float(sim["p05_net"][idx])
            status = "✅ SAFE" if p5 >= 200_000 else ("⚠️ RISKY" if mn >= 200_000 else "❌ MISS")
            rows.append({
                "Scenario": n.split("(")[0][:15],
                "Mean": f"{mn:,.0f}",
                "P05": f"{p5:,.0f}",
                "Status": status,
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        safe = sum(1 for r in rows if r["Status"] == "✅ SAFE")
        st.markdown(f"**Summary:** {safe}/8 scenarios are SAFE (P05≥200k)")
    else:
        st.warning("Allocation not on grid. Adjust sliders.")

    # ========== SECTION 2: Per-Scenario Optima ==========
    st.divider()
    st.markdown("## 📊 Per-Scenario Optima")
    st.markdown("### Optimal allocation per scenario (3 strategies each)")

    st.markdown("""
**Global**: Max average profit.
**Safety**: Robust to speed variance. (Recommended for balanced play)
**P05-Max**: Maximize worst 5%. (Ultra-conservative)
    """)

    rows = []
    for name, opt in optima_per.items():
        for which in ("global", "safety", "p05_max"):
            o = opt.get(which)
            if o is None:
                continue
            a = o["alloc"]
            rows.append({
                "Scenario": name.split("(")[0][:15],
                "Strategy": which.replace("_", "-"),
                "x": int(a[0]), "y": int(a[1]), "z": int(a[2]),
                "Cost": f"{int(o['cost']):,}",
                "Mean": f"{o['mean_net']:,.0f}",
                "P05": f"{o['p05_net']:,.0f}",
                "Goal": "✅" if o["p05_net"] >= 200_000 else ("⚠️" if o["mean_net"] >= 200_000 else "❌"),
            })

    df_opts = pd.DataFrame(rows)
    st.dataframe(df_opts, use_container_width=True, hide_index=True)

    # ========== SECTION 3: Robust Hedging ==========
    st.divider()
    st.markdown("## 🧊 Robust Hedging")
    st.markdown("### Robust allocations (hedge all scenarios equally)")

    rmm = robust["maximin_mean"]
    rmp = robust["maximin_p05"]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Maximin-Mean** (balanced hedge)  \nx={rmm['alloc'][0]}, y={rmm['alloc'][1]}, z={rmm['alloc'][2]}")
        st.metric("Worst-case mean", f"{rmm['worst_case_mean_net']:,.0f}")
        with st.expander("Per-scenario"):
            r1_df = pd.DataFrame(
                rmm["per_scenario_mean_net"].items(),
                columns=["Scenario", "Mean"],
            ).assign(**{"Mean": lambda d: d["Mean"].round().astype(int).apply(lambda x: f"{x:,}")})
            st.dataframe(r1_df, use_container_width=True, hide_index=True)

    with c2:
        st.markdown(f"**Maximin-P05** (ultra-safe)  \nx={rmp['alloc'][0]}, y={rmp['alloc'][1]}, z={rmp['alloc'][2]}")
        st.metric("Worst-case P05", f"{rmp['worst_case_p05_net']:,.0f}")
        with st.expander("Per-scenario"):
            r2_df = pd.DataFrame(
                rmp["per_scenario_p05_net"].items(),
                columns=["Scenario", "P05"],
            ).assign(**{"P05": lambda d: d["P05"].round().astype(int).apply(lambda x: f"{x:,}")})
            st.dataframe(r2_df, use_container_width=True, hide_index=True)

    # ========== SECTION 4: Scenario Distributions ==========
    st.divider()
    st.markdown("## 🎲 Scenario Distributions")
    st.markdown("### Competitor speed distributions")
    st.caption("See how your speed (z) ranks against competitors in each scenario.")

    try:
        from manual_optimiser import plotting as moplot
        rng = np.random.default_rng(int(seed))
        scen_tabs = st.tabs(names)
        for i, n in enumerate(names):
            with scen_tabs[i]:
                pop = moscen.ALL_SCENARIOS[n](rng)
                col_a, col_b = st.columns(2)
                with col_a:
                    st.plotly_chart(
                        moplot.competitor_histogram(pop, your_z=50, title=f"{n} (z=50 example)"),
                        use_container_width=True,
                    )
                with col_b:
                    st.plotly_chart(
                        moplot.speed_curve(pop, highlight_z=50),
                        use_container_width=True,
                    )
    except Exception as e:
        st.warning(f"Could not load scenario charts: {e}")
