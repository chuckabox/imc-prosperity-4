"""Altair-based figures for manual_optimiser. No Plotly dependency here."""

from __future__ import annotations
import numpy as np
import pandas as pd
import altair as alt

try:
    from .engine import speed_multiplier_vs_pop
except ImportError:
    from engine import speed_multiplier_vs_pop  # type: ignore

def heatmap_full_grid(grid: np.ndarray, mean_net: np.ndarray, z_fixed: int):
    """Mean Net over (x,y) at fixed z. Uses Altair."""
    mask = grid[:, 2] == z_fixed
    sub = grid[mask]
    vals = mean_net[mask]
    if sub.size == 0:
        return None
    
    df = pd.DataFrame({
        "x": sub[:, 0],
        "y": sub[:, 1],
        "mean_net": vals
    })
    
    chart = alt.Chart(df).mark_rect().encode(
        x=alt.X("x:O", title="Research x"),
        y=alt.Y("y:O", title="Scale y", sort="descending"),
        color=alt.Color("mean_net:Q", scale=alt.Scale(scheme="viridis"), title="Mean Net PnL"),
        tooltip=["x", "y", alt.Tooltip("mean_net:Q", format=",.0f")]
    ).properties(
        title=f"Mean Net PnL surface — z={z_fixed}",
        width=400,
        height=400
    )
    return chart

def competitor_histogram(pop: np.ndarray, your_z: int | None = None, title: str = "Competitor speed distribution"):
    df = pd.DataFrame({"Speed": pop})
    
    hist = alt.Chart(df).mark_bar(color="#5B8FF9").encode(
        x=alt.X("Speed:Q", bin=alt.Bin(maxbins=50), title="Speed bid z"),
        y=alt.Y("count():Q", title="# traders")
    )
    
    charts = [hist]
    if your_z is not None:
        vline = alt.Chart(pd.DataFrame({"z": [your_z]})).mark_rule(color="red", size=3).encode(x="z:Q")
        text = vline.mark_text(align="left", dx=5, dy=-150, text=f"You: z={your_z}", color="red").encode(x="z:Q")
        charts.extend([vline, text])
        
    return alt.layer(*charts).properties(title=title, width="container", height=320).interactive()

def speed_curve(pop: np.ndarray, highlight_z: int | None = None):
    zs = np.arange(0, 101)
    mults = [speed_multiplier_vs_pop(z, pop) for z in zs]
    df = pd.DataFrame({"z": zs, "Multiplier": mults})
    
    line = alt.Chart(df).mark_line().encode(
        x=alt.X("z:Q", title="z"),
        y=alt.Y("Multiplier:Q", title="Multiplier")
    )
    
    safety = alt.Chart(pd.DataFrame({"y": [0.5]})).mark_rule(strokeDash=[5,5], color="orange").encode(y="y:Q")
    
    charts = [line, safety]
    if highlight_z is not None:
        vline = alt.Chart(pd.DataFrame({"z": [highlight_z]})).mark_rule(color="red").encode(x="z:Q")
        charts.append(vline)
        
    return alt.layer(*charts).properties(title="Speed bid → rank multiplier", width="container", height=320).interactive()

def pnl_distribution_analytical(mean: float, p05: float, p50: float, p95: float, alloc: tuple):
    """Box-style summary using Altair."""
    # Altair mark_boxplot needs raw data or specific encoding. 
    # Since we have precomputed stats, we manual-build it.
    df = pd.DataFrame([{
        "min": p05,
        "max": p95,
        "median": p50,
        "mean": mean,
        "label": f"alloc={alloc}"
    }])
    
    base = alt.Chart(df).encode(y=alt.Y("label:N", title=None))
    
    bar = base.mark_bar(size=20).encode(
        x=alt.X("min:Q", title="Net PnL"),
        x2="max:Q"
    )
    
    tick = base.mark_tick(color="white", thickness=2).encode(x="median:Q")
    mean_pt = base.mark_point(color="red", filled=True, size=50).encode(x="mean:Q")
    
    goal = alt.Chart(pd.DataFrame({"x": [200000]})).mark_rule(strokeDash=[5,5], color="red").encode(x="x:Q")
    
    return alt.layer(bar, tick, mean_pt, goal).properties(
        title=f"Net PnL spread — alloc={alloc} (mean {mean:,.0f})",
        width="container",
        height=100
    )

def scenario_comparison_bars(optima_per_scenario: dict, pick_key: str = "safety"):
    names = list(optima_per_scenario.keys())
    data = []
    for n in names:
        o = optima_per_scenario[n][pick_key] or optima_per_scenario[n]["global"]
        data.append({"Scenario": n, "Type": "Mean Net", "Value": o["mean_net"], "Alloc": str(tuple(o["alloc"]))})
        data.append({"Scenario": n, "Type": "P05 Net", "Value": o["p05_net"], "Alloc": str(tuple(o["alloc"]))})
    
    df = pd.DataFrame(data)
    
    bars = alt.Chart(df).mark_bar().encode(
        x=alt.X("Type:N", title=None),
        y=alt.Y("Value:Q", title="Net PnL"),
        color=alt.Color("Type:N", scale=alt.Scale(scheme="set2")),
        column=alt.Column("Scenario:N", title=None),
        tooltip=["Scenario", "Type", alt.Tooltip("Value:Q", format=",.0f"), "Alloc"]
    )
    
    goal = alt.Chart(pd.DataFrame({"y": [200000]})).mark_rule(strokeDash=[5,5], color="red").encode(y="y:Q")
    
    return (bars + goal).properties(title=f"Optimum Net PnL per scenario ({pick_key})")
