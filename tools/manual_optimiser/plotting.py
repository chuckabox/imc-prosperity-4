"""Plotly figures. No Streamlit imports here."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

try:
    from .engine import speed_multiplier_vs_pop
except ImportError:
    from engine import speed_multiplier_vs_pop  # type: ignore


def heatmap_full_grid(grid: np.ndarray, mean_net: np.ndarray, z_fixed: int) -> go.Figure:
    """Mean Net over (x,y) at fixed z. Uses already-computed MC results."""
    mask = grid[:, 2] == z_fixed
    sub = grid[mask]
    vals = mean_net[mask]
    if sub.size == 0:
        return go.Figure()
    X = np.full((101, 101), np.nan)
    for (x, y, _), v in zip(sub, vals):
        X[int(y), int(x)] = v
    fig = go.Figure(
        data=go.Heatmap(
            z=X, colorscale="Viridis",
            colorbar={"title": "Mean Net PnL"},
            hovertemplate="x=%{x} y=%{y}<br>mean_net=%{z:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        title=f"Mean Net PnL surface — z={z_fixed}",
        xaxis_title="Research x", yaxis_title="Scale y", height=500,
    )
    return fig


def competitor_histogram(pop: np.ndarray, your_z: int | None = None,
                         title: str = "Competitor speed distribution") -> go.Figure:
    fig = go.Figure(
        data=go.Histogram(x=pop, nbinsx=50, marker_color="#5B8FF9", name="Competitors")
    )
    if your_z is not None:
        fig.add_vline(
            x=your_z, line_width=3, line_color="red",
            annotation_text=f"You: z={your_z}", annotation_position="top",
        )
    fig.update_layout(
        title=title,
        xaxis_title="Speed bid z", yaxis_title="# traders",
        bargap=0.02, height=320,
    )
    return fig


def speed_curve(pop: np.ndarray, highlight_z: int | None = None) -> go.Figure:
    zs = np.arange(0, 101)
    mults = [speed_multiplier_vs_pop(z, pop) for z in zs]
    fig = go.Figure(data=go.Scatter(x=zs, y=mults, mode="lines", name="Speed mult"))
    fig.add_hline(y=0.5, line_dash="dash", line_color="orange",
                  annotation_text="Safety 0.5")
    if highlight_z is not None:
        fig.add_vline(x=highlight_z, line_color="red")
    fig.update_layout(
        title="Speed bid → rank multiplier",
        xaxis_title="z", yaxis_title="Multiplier", height=320,
    )
    return fig


def pnl_distribution_analytical(mean: float, p05: float, p50: float, p95: float,
                                alloc: tuple) -> go.Figure:
    """Box-style summary since we now compose stats analytically."""
    fig = go.Figure(data=[go.Box(
        q1=[p05], median=[p50], q3=[p95], lowerfence=[p05], upperfence=[p95],
        mean=[mean], name=f"alloc={alloc}", boxmean=True,
    )])
    fig.add_vline(x=200_000, line_dash="dash", line_color="red",
                  annotation_text="200k goal")
    fig.update_layout(
        title=f"Net PnL spread — alloc={alloc} (mean {mean:,.0f})",
        xaxis_title="Net PnL", height=250, showlegend=False,
    )
    return fig


def scenario_comparison_bars(optima_per_scenario: dict, pick_key: str = "safety") -> go.Figure:
    """Bar of optimum Net PnL per scenario (mean + p05)."""
    names = list(optima_per_scenario.keys())
    means, p05s, allocs = [], [], []
    for n in names:
        o = optima_per_scenario[n][pick_key] or optima_per_scenario[n]["global"]
        means.append(o["mean_net"])
        p05s.append(o["p05_net"])
        allocs.append(tuple(o["alloc"]))
    fig = go.Figure()
    fig.add_bar(x=names, y=means, name="Mean Net",
                text=[f"{a}" for a in allocs], textposition="outside")
    fig.add_bar(x=names, y=p05s, name="P05 Net", opacity=0.7)
    fig.add_hline(y=200_000, line_dash="dash", line_color="red",
                  annotation_text="200k goal")
    fig.update_layout(
        title=f"Optimum Net PnL per scenario ({pick_key})",
        yaxis_title="Net PnL", barmode="group", height=420,
    )
    return fig
