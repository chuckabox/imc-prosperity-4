"""Streamlit dashboard.

Run:
    cd "ROUND 2/manual_trade/optimiser"
    streamlit run app.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import streamlit as st

from engine import ProsperityOptimizer, sample_competitor_speeds, FIXED_COST
from simulation import monte_carlo, find_optima
import plotting as P


st.set_page_config(page_title="Prosperity R2 Manual Optimiser", layout="wide")


# ---------- cached expensive bits ----------
@st.cache_data(show_spinner=False)
def cached_pop(seed: int, n: int = 10_000) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return sample_competitor_speeds(n, rng=rng)


@st.cache_data(show_spinner="Running Monte Carlo…")
def cached_mc(n_iter: int, seed: int, safety_threshold: float) -> dict:
    return monte_carlo(n_iter=n_iter, seed=seed, safety_threshold=safety_threshold)


# ---------- 3-way slider with linked offsets ----------
def _init_state():
    if "x" not in st.session_state:
        # start at a reasonable safety default
        st.session_state.x = 55
        st.session_state.y = 20
        st.session_state.z = 25
        st.session_state._last = "x"


def _rebalance(changed: str):
    """Keep x+y+z=100 by redistributing to the other two proportionally."""
    vals = {"x": st.session_state.x, "y": st.session_state.y, "z": st.session_state.z}
    total = sum(vals.values())
    if total == 100:
        return
    others = [k for k in ("x", "y", "z") if k != changed]
    diff = 100 - vals[changed]  # target sum for the other two
    cur_other = vals[others[0]] + vals[others[1]]
    if cur_other <= 0:
        # split evenly
        a = diff // 2
        b = diff - a
        st.session_state[others[0]] = int(max(0, a))
        st.session_state[others[1]] = int(max(0, b))
    else:
        r = diff / cur_other
        a = int(round(vals[others[0]] * r))
        a = max(0, min(diff, a))
        b = diff - a
        st.session_state[others[0]] = a
        st.session_state[others[1]] = b
    # clamp
    for k in ("x", "y", "z"):
        st.session_state[k] = int(max(0, min(100, st.session_state[k])))
    s = st.session_state.x + st.session_state.y + st.session_state.z
    if s != 100:
        # absorb rounding into `changed`
        st.session_state[changed] += 100 - s


def on_change_x(): _rebalance("x")
def on_change_y(): _rebalance("y")
def on_change_z(): _rebalance("z")


# ---------- sidebar controls ----------
_init_state()

with st.sidebar:
    st.header("Simulation params")
    n_iter = st.slider("MC iterations", 100, 5_000, 1_000, step=100)
    pop_seed = st.number_input("Competitor pop seed", 0, 10_000, 42)
    safety_thr = st.slider("Safety speed threshold", 0.1, 0.9, 0.5, 0.05)
    safety_prob = st.slider("Safety probability", 0.80, 0.99, 0.95, 0.01)
    run_mc = st.button("Run / refresh Monte Carlo", type="primary")

    st.divider()
    st.caption("Current pnl: **179k**  |  Target: **≥200k**")


# ---------- main ----------
st.title("🏴‍☠️ Prosperity R2 Manual Challenge — Optimiser")

pop = cached_pop(int(pop_seed))
opt = ProsperityOptimizer(pop=pop)

col_a, col_b, col_c = st.columns(3)
with col_a:
    st.slider("Research x", 0, 100, key="x", on_change=on_change_x)
with col_b:
    st.slider("Scale y", 0, 100, key="y", on_change=on_change_y)
with col_c:
    st.slider("Speed z", 0, 100, key="z", on_change=on_change_z)

x, y, z = st.session_state.x, st.session_state.y, st.session_state.z
st.caption(f"Budget check: x+y+z = **{x+y+z}** (must be 100)")

pnl = opt.pnl(x, y, z)

# Live PnL readout
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Research R(x)", f"{pnl.research:,.0f}")
m2.metric("Scale ×(1+0.07y)", f"{pnl.scale_mult:.2f}×")
m3.metric("Speed M(z)", f"{pnl.speed_mult:.3f}×")
m4.metric("Gross PnL", f"{pnl.gross:,.0f}")
m5.metric("Net PnL (−50k)", f"{pnl.net:,.0f}",
          delta=f"{pnl.net - 200_000:,.0f} vs 200k")

if pnl.net >= 200_000:
    st.success(f"✅ Above 200k target by {pnl.net - 200_000:,.0f}")
elif pnl.net >= 179_000:
    st.warning(f"Above current 179k baseline by {pnl.net - 179_000:,.0f}, short of 200k by {200_000 - pnl.net:,.0f}")
else:
    st.error(f"Below 179k baseline by {179_000 - pnl.net:,.0f}")


# ---------- run MC ----------
if run_mc or "mc" not in st.session_state:
    st.session_state.mc = cached_mc(int(n_iter), int(pop_seed), float(safety_thr))

sim = st.session_state.mc
optima = find_optima(sim, safety_prob=float(safety_prob))

st.subheader("Optimiser results")
c1, c2 = st.columns(2)
with c1:
    st.markdown("### 🎯 Global Optimum (max mean Net PnL)")
    g = optima["global"]
    st.json(g)
    if st.button("Apply Global", key="apply_g"):
        st.session_state.x, st.session_state.y, st.session_state.z = g["alloc"]
        st.rerun()
with c2:
    st.markdown(f"### 🛡️ Safety Optimum (P(speed≥{safety_thr:.2f}) ≥ {safety_prob:.0%})")
    s = optima["safety"]
    if s is None:
        st.error("No allocation satisfies safety constraint. Lower threshold.")
    else:
        st.json(s)
        if st.button("Apply Safety", key="apply_s"):
            st.session_state.x, st.session_state.y, st.session_state.z = s["alloc"]
            st.rerun()


# ---------- plots ----------
st.subheader("Visual diagnostics")
tab1, tab2, tab3, tab4 = st.tabs(["Heatmap", "Competitor market", "Speed curve", "PnL distribution"])

with tab1:
    st.plotly_chart(P.heatmap_full_grid(sim["grid"], sim["mean_net"], z_fixed=z),
                    use_container_width=True)
    st.caption("Mean Net PnL across MC at current z. Bright cells = better.")

with tab2:
    st.plotly_chart(P.competitor_histogram(pop, your_z=z), use_container_width=True)

with tab3:
    st.plotly_chart(P.speed_curve(pop, highlight_z=z), use_container_width=True)

with tab4:
    # Find col index of current alloc
    grid = sim["grid"]
    idx = np.where((grid[:, 0] == x) & (grid[:, 1] == y) & (grid[:, 2] == z))[0]
    if idx.size:
        col = sim["net_samples"][:, int(idx[0])]
        st.plotly_chart(P.pnl_distribution(col, (x, y, z)), use_container_width=True)
        hit_200k = float(np.mean(col >= 200_000))
        hit_179k = float(np.mean(col >= 179_000))
        cc1, cc2, cc3 = st.columns(3)
        cc1.metric("P(Net ≥ 200k)", f"{hit_200k:.1%}")
        cc2.metric("P(Net ≥ 179k)", f"{hit_179k:.1%}")
        cc3.metric("5th pct Net", f"{np.percentile(col, 5):,.0f}")
    else:
        st.info("Current allocation not on grid.")


# ---------- export ----------
st.subheader("Export")
out_path = Path(__file__).parent / "optimum_config.json"
payload = {
    "current_alloc": {"x": x, "y": y, "z": z},
    "current_pnl": {
        "research": pnl.research, "scale_mult": pnl.scale_mult,
        "speed_mult": pnl.speed_mult, "gross": pnl.gross, "net": pnl.net,
    },
    "optima": optima,
    "params": {
        "n_iter": int(n_iter), "pop_seed": int(pop_seed),
        "safety_threshold": float(safety_thr), "safety_prob": float(safety_prob),
        "fixed_cost": FIXED_COST,
    },
}
if st.button("💾 Write optimum_config.json"):
    out_path.write_text(json.dumps(payload, indent=2))
    st.success(f"Wrote {out_path}")
st.download_button("Download JSON", json.dumps(payload, indent=2),
                   file_name="optimum_config.json")
