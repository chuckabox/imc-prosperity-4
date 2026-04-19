"""Prosperity R2 Partial-Budget Profit Optimiser.

Sister app to `app.py`. The main app forces x+y+z=100 (full 50k spend).
This one lets the total float — we only commit budget when the marginal
return beats the marginal cost, and we explicitly flag allocations where
Net Profit fails to clear a user-set threshold (default 50k).

Run from the repo root:
    streamlit run tools/manual_optimiser/app_profit.py

Math recap:
    Research(x) = 200_000 * ln(1+x) / ln(101)
    Scale(y)    = 0.07 * y
    Speed(z)    rank-based vs competitor pop, in [0.1, 0.9]
    Cost        = 500 * (x+y+z)      # per-% point cost
    Net Profit  = Research(x) * Scale(y) * Speed(z) - Cost
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from engine import (
    BUDGET_TOTAL,
    COST_PER_POINT,
    ProsperityOptimizer,
    sample_competitor_speeds,
)
from simulation import monte_carlo
import plotting as P
import scenarios as S


st.set_page_config(page_title="R2 Partial-Budget Profit Optimiser", layout="wide")


@st.cache_data(show_spinner=False)
def cached_pop(seed: int, scenario: str, n: int = 10_000) -> np.ndarray:
    rng = np.random.default_rng(seed)
    sampler = S.ALL_SCENARIOS.get(scenario)
    if sampler is None:
        return sample_competitor_speeds(n, rng=rng)
    return sampler(rng)


@st.cache_data(show_spinner="Running Monte Carlo…")
def cached_mc(n_iter: int, seed: int, scenario: str) -> dict:
    sampler = S.ALL_SCENARIOS.get(scenario)
    return monte_carlo(n_iter=n_iter, seed=seed, sampler=sampler)


def _init_state():
    st.session_state.setdefault("px", 15)
    st.session_state.setdefault("py", 43)
    st.session_state.setdefault("pz", 42)


def _clamp_total():
    """If the three sliders exceed 100%, shrink the most recently moved one."""
    tx = st.session_state.px
    ty = st.session_state.py
    tz = st.session_state.pz
    total = tx + ty + tz
    if total <= 100:
        return
    last = st.session_state.get("_last_touched", "pz")
    others_sum = total - st.session_state[last]
    st.session_state[last] = max(0, 100 - others_sum)


def _touch(which: str):
    st.session_state._last_touched = which
    _clamp_total()


_init_state()


with st.sidebar:
    st.header("Simulation params")
    scen_name = st.selectbox(
        "Competitor scenario",
        list(S.ALL_SCENARIOS.keys()),
        index=0,
    )
    n_iter = st.slider("MC iterations", 100, 5_000, 1_000, step=100)
    pop_seed = st.number_input("Competitor pop seed", 0, 10_000, 42)
    min_profit = st.number_input(
        "Min profit threshold (XIRECs)",
        min_value=0, max_value=500_000, value=50_000, step=5_000,
        help=(
            "Playing is only 'worth it' if Net Profit clears this bar. "
            "Default 50k = the full budget granted to us."
        ),
    )
    run_mc = st.button("Run / refresh Monte Carlo", type="primary")
    st.divider()
    st.caption(
        "**Partial-budget mode.** Each % point costs 500 XIRECs. "
        "Total spend = 500 × (x+y+z)."
    )


st.title("💰 R2 Partial-Budget Profit Optimiser")
st.markdown(
    f"**Budget:** 50,000 XIRECs total — but we don't have to spend all of it. "
    f"We only commit capital where it grows Net Profit. Threshold currently set to "
    f"**{int(min_profit):,}**; allocations below that are flagged as not worth playing."
)


pop = cached_pop(int(pop_seed), scen_name)
opt = ProsperityOptimizer(pop=pop)

col_a, col_b, col_c = st.columns(3)
with col_a:
    st.slider("Research x", 0, 100, key="px", on_change=_touch, args=("px",))
with col_b:
    st.slider("Scale y", 0, 100, key="py", on_change=_touch, args=("py",))
with col_c:
    st.slider("Speed z", 0, 100, key="pz", on_change=_touch, args=("pz",))

x = int(st.session_state.px)
y = int(st.session_state.py)
z = int(st.session_state.pz)
total = x + y + z

pnl = opt.pnl(x, y, z)

mt1, mt2, mt3, mt4 = st.columns(4)
mt1.metric("Total allocation", f"{total}%", f"{100 - total}% unused")
mt2.metric("Budget spent", f"{int(pnl.cost):,}", f"{int(BUDGET_TOTAL - pnl.cost):,} saved")
mt3.metric("Gross PnL", f"{pnl.gross:,.0f}")
mt4.metric(
    "Net Profit",
    f"{pnl.net:,.0f}",
    delta=f"{pnl.net - min_profit:,.0f} vs {int(min_profit):,}",
)

if pnl.net <= 0:
    st.error(
        f"Don't play — Net Profit is {pnl.net:,.0f}. You'd burn budget for nothing."
    )
elif pnl.net < min_profit:
    st.warning(
        f"Net Profit {pnl.net:,.0f} is below the {int(min_profit):,} threshold — "
        f"consider a cheaper allocation or skipping entirely."
    )
else:
    st.success(
        f"Net Profit {pnl.net:,.0f} clears the {int(min_profit):,} threshold by "
        f"{pnl.net - min_profit:,.0f}."
    )

with st.expander("Pillar breakdown"):
    b1, b2, b3 = st.columns(3)
    b1.metric("Research R(x)", f"{pnl.research:,.0f}")
    b2.metric("Scale S(y)", f"{pnl.scale_value:.2f}")
    b3.metric("Speed M(z)", f"{pnl.speed_mult:.3f}×")


if run_mc or "mc_profit" not in st.session_state or st.session_state.get("mc_profit_scen") != scen_name:
    st.session_state.mc_profit = cached_mc(int(n_iter), int(pop_seed), scen_name)
    st.session_state.mc_profit_scen = scen_name

sim = st.session_state.mc_profit
grid = sim["grid"]
mean_net = sim["mean_net"]
p05_net = sim["p05_net"]
cost = sim["cost"]
totals_grid = grid.sum(axis=1)


st.subheader("Optimiser picks")
opt_cols = st.columns(3)


def _apply_alloc(alloc: np.ndarray, key_suffix: str):
    if st.button("Apply", key=f"apply_{key_suffix}"):
        st.session_state.px = int(alloc[0])
        st.session_state.py = int(alloc[1])
        st.session_state.pz = int(alloc[2])
        st.rerun()


def _summary(idx: int) -> dict:
    a = grid[idx]
    return {
        "alloc": [int(v) for v in a],
        "total_pct": int(a.sum()),
        "budget_used": int(cost[idx]),
        "mean_net_profit": round(float(mean_net[idx])),
        "p05_net_profit": round(float(p05_net[idx])),
    }


with opt_cols[0]:
    st.markdown("### 🎯 Max Net Profit")
    st.caption("Largest expected profit. May still use the full 50k if that wins.")
    gi = int(np.argmax(mean_net))
    st.json(_summary(gi))
    _apply_alloc(grid[gi], "max_profit")

with opt_cols[1]:
    st.markdown("### 💸 Cheapest clear")
    st.caption(f"Smallest spend whose mean Net Profit still ≥ {int(min_profit):,}.")
    mask_ok = mean_net >= min_profit
    if mask_ok.any():
        passing = np.where(mask_ok)[0]
        ci = int(passing[np.argmin(cost[passing])])
        st.json(_summary(ci))
        _apply_alloc(grid[ci], "cheap")
    else:
        st.info("No allocation clears the threshold under this scenario.")

with opt_cols[2]:
    st.markdown("### 📈 Max profit / XIREC")
    st.caption("Best capital efficiency (mean Net Profit ÷ Budget used, cost > 0).")
    with np.errstate(divide="ignore", invalid="ignore"):
        eff = np.where(cost > 0, mean_net / np.maximum(cost, 1.0), -np.inf)
    ei = int(np.argmax(eff))
    payload = _summary(ei)
    payload["profit_per_xirec"] = round(float(eff[ei]), 3)
    st.json(payload)
    _apply_alloc(grid[ei], "eff")


st.subheader("Partial-budget frontier")
st.caption(
    "For each total allocation level (0–100%), the best achievable mean Net Profit. "
    "The curve tells you whether spending MORE budget actually buys MORE profit — "
    "a flat or declining tail means extra spend is wasted."
)

frontier_step = 5
frontier_totals = np.arange(0, 101, frontier_step)
best_net = []
best_allocs = []
best_p05 = []
for t in frontier_totals:
    mask_t = totals_grid == t
    if mask_t.any():
        idx = np.where(mask_t)[0]
        bi = int(idx[np.argmax(mean_net[idx])])
        best_net.append(float(mean_net[bi]))
        best_p05.append(float(p05_net[bi]))
        best_allocs.append(tuple(int(v) for v in grid[bi]))
    else:
        best_net.append(0.0)
        best_p05.append(0.0)
        best_allocs.append((0, 0, 0))

df_front = pd.DataFrame(
    {
        "Total %": frontier_totals,
        "Budget used": frontier_totals * int(COST_PER_POINT),
        "Mean Net Profit": best_net,
        "P05 Net Profit": best_p05,
        "Best (x,y,z)": [str(a) for a in best_allocs],
    }
)

fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=df_front["Budget used"],
        y=df_front["Mean Net Profit"],
        mode="lines+markers",
        name="Mean Net Profit",
        hovertext=df_front["Best (x,y,z)"],
        hovertemplate="spend=%{x:,}<br>mean net=%{y:,.0f}<br>alloc=%{hovertext}<extra></extra>",
    )
)
fig.add_trace(
    go.Scatter(
        x=df_front["Budget used"],
        y=df_front["P05 Net Profit"],
        mode="lines+markers",
        name="P05 Net Profit",
        line={"dash": "dot"},
    )
)
fig.add_hline(y=0, line_color="red", line_dash="dash", annotation_text="Break-even")
fig.add_hline(
    y=min_profit,
    line_color="green",
    line_dash="dash",
    annotation_text=f"{int(min_profit):,} threshold",
)
fig.update_layout(
    xaxis_title="Budget used (XIRECs)",
    yaxis_title="Net Profit (XIRECs)",
    height=420,
    hovermode="x unified",
)
st.plotly_chart(fig, use_container_width=True)

st.dataframe(df_front, use_container_width=True, hide_index=True)


st.subheader("Visual diagnostics")
tab1, tab2, tab3 = st.tabs(["Heatmap @ current z", "Competitor market", "Speed curve"])

with tab1:
    st.plotly_chart(
        P.heatmap_full_grid(grid, mean_net, z_fixed=z),
        use_container_width=True,
    )
    st.caption("Mean Net Profit surface at current z. Only (x,y) with x+y+z ≤ 100 are feasible.")

with tab2:
    st.plotly_chart(P.competitor_histogram(pop, your_z=z), use_container_width=True)

with tab3:
    st.plotly_chart(P.speed_curve(pop, highlight_z=z), use_container_width=True)


st.subheader("Export")
out_path = Path(__file__).parent / "partial_profit_config.json"
payload = {
    "scenario": scen_name,
    "current_alloc": {"x": x, "y": y, "z": z, "total_pct": total},
    "current_breakdown": {
        "research": pnl.research,
        "scale_value": pnl.scale_value,
        "speed_mult": pnl.speed_mult,
        "gross": pnl.gross,
        "cost": pnl.cost,
        "net_profit": pnl.net,
    },
    "optima": {
        "max_net_profit": _summary(int(np.argmax(mean_net))),
    },
    "frontier": [
        {
            "total_pct": int(t),
            "budget_used": int(t) * int(COST_PER_POINT),
            "best_alloc": list(a),
            "mean_net_profit": round(v),
        }
        for t, a, v in zip(frontier_totals, best_allocs, best_net)
    ],
    "params": {
        "n_iter": int(n_iter),
        "pop_seed": int(pop_seed),
        "min_profit_threshold": int(min_profit),
    },
}

if st.button("💾 Write partial_profit_config.json"):
    out_path.write_text(json.dumps(payload, indent=2))
    st.success(f"Wrote {out_path}")
st.download_button(
    "Download JSON",
    json.dumps(payload, indent=2),
    file_name="partial_profit_config.json",
)
