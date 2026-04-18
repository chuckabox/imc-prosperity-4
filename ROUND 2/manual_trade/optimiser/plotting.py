"""Plotly figures. No Streamlit imports here."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from engine import (
    research_pnl,
    scale_multiplier,
    speed_multiplier_vs_pop,
    FIXED_COST,
)


def heatmap_research_vs_scale(pop: np.ndarray, z_fixed: int) -> go.Figure:
    # Grid over x,y with x+y<=100 (remainder uses z_fixed if consistent; else blank)
    xs = np.arange(0, 101)
    ys = np.arange(0, 101)
    Z = np.full((ys.size, xs.size), np.nan)
    m_fixed = speed_multiplier_vs_pop(z_fixed, pop)
    for i, y in enumerate(ys):
        for j, x in enumerate(xs):
            if x + y + z_fixed == 100 or x + y <= 100 - z_fixed:
                # only the slice where x+y == 100 - z_fixed is feasible
                if x + y == 100 - z_fixed:
                    Z[i, j] = research_pnl(x) * scale_multiplier(y) * m_fixed - FIXED_COST
    fig = go.Figure(
        data=go.Heatmap(
            x=xs, y=ys, z=Z,
            colorscale="Viridis",
            colorbar={"title": "Net PnL"},
            hovertemplate="x=%{x} y=%{y}<br>Net=%{z:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        title=f"Net PnL Heatmap — Speed z={z_fixed} fixed (feasible diagonal)",
        xaxis_title="Research x",
        yaxis_title="Scale y",
        height=500,
    )
    return fig


def heatmap_full_grid(grid: np.ndarray, mean_net: np.ndarray, z_fixed: int) -> go.Figure:
    # Slice to rows where z == z_fixed. Plot x vs y with Z=mean_net.
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
        title=f"MC Mean Net PnL — z={z_fixed}",
        xaxis_title="Research x", yaxis_title="Scale y", height=500,
    )
    return fig


def competitor_histogram(pop: np.ndarray, your_z: int | None = None) -> go.Figure:
    fig = go.Figure(
        data=go.Histogram(x=pop, nbinsx=50, marker_color="#5B8FF9", name="Competitors")
    )
    if your_z is not None:
        fig.add_vline(
            x=your_z, line_width=3, line_color="red",
            annotation_text=f"You: z={your_z}", annotation_position="top",
        )
    fig.update_layout(
        title="Competitor Speed Distribution — Beta(2,5) × 100",
        xaxis_title="Speed bid z", yaxis_title="# traders",
        bargap=0.02, height=380,
    )
    return fig


def speed_curve(pop: np.ndarray, highlight_z: int | None = None) -> go.Figure:
    zs = np.arange(0, 101)
    mults = [speed_multiplier_vs_pop(z, pop) for z in zs]
    fig = go.Figure(data=go.Scatter(x=zs, y=mults, mode="lines", name="Speed multiplier"))
    fig.add_hline(y=0.5, line_dash="dash", line_color="orange",
                  annotation_text="Safety threshold 0.5")
    if highlight_z is not None:
        fig.add_vline(x=highlight_z, line_color="red")
    fig.update_layout(
        title="Speed bid → rank multiplier",
        xaxis_title="z", yaxis_title="Multiplier",
        height=380,
    )
    return fig


def pnl_distribution(net_samples_col: np.ndarray, alloc: tuple) -> go.Figure:
    fig = go.Figure(data=go.Histogram(x=net_samples_col, nbinsx=40, marker_color="#61DDAA"))
    fig.add_vline(x=200_000, line_dash="dash", line_color="red",
                  annotation_text="200k goal")
    fig.add_vline(x=np.mean(net_samples_col), line_color="blue",
                  annotation_text=f"mean={np.mean(net_samples_col):,.0f}")
    fig.update_layout(
        title=f"Net PnL MC distribution — alloc={alloc}",
        xaxis_title="Net PnL", yaxis_title="# iters",
        height=380,
    )
    return fig
