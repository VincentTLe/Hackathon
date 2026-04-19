"""
Guardian-Sleuth: Analyst Dashboard
====================================
Four-panel dark-theme Streamlit view for fraud analysts.

Layout:
  ┌─────────────────────┬─────────────────────────────┐
  │  Panel 1            │  Panel 2                    │
  │  TRUST SCORE        │  SYNDICATE GRAPH            │
  │  Gauge 0-100        │  Pyvis interactive network  │
  ├─────────────────────┼─────────────────────────────┤
  │  Panel 3            │  Panel 4                    │
  │  NCUA MACRO OVERLAY │  BEHAVIORAL RED FLAGS       │
  │  Dual-axis Plotly   │  Plain-English bullets      │
  └─────────────────────┴─────────────────────────────┘

Called by main.py after an account is submitted for analysis.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pyvis.network import Network

# Make sure sibling packages are importable when running directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.data_manager import DataManager
from core.models import AMLPipeline, generate_flags

# ---------------------------------------------------------------------------
# Colour palette (dark theme)
# ---------------------------------------------------------------------------

BG_DARK    = "#0e1117"
BG_CARD    = "#1c1f26"
RED        = "#ff4b4b"
AMBER      = "#ffa500"
GREEN      = "#00c853"
BLUE_ACCENT= "#4fc3f7"
TEXT_LIGHT = "#e0e0e0"

RISK_COLOR = {
    "HIGH":   RED,
    "MEDIUM": AMBER,
    "LOW":    GREEN,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _risk_color(score: float) -> str:
    if score >= 0.70:
        return RED
    elif score >= 0.40:
        return AMBER
    return GREEN


def _risk_label(score: float) -> str:
    if score >= 0.70:
        return "HIGH RISK"
    elif score >= 0.40:
        return "MEDIUM RISK"
    return "LOW RISK"


# ---------------------------------------------------------------------------
# Panel 1: Trust Score gauge
# ---------------------------------------------------------------------------

def render_trust_score(score: float) -> None:
    """Plotly gauge card showing 0-100 risk score."""
    pct = score * 100
    color = _risk_color(score)
    label = _risk_label(score)

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=pct,
        number={"suffix": "/100", "font": {"color": color, "size": 48}},
        title={"text": f"<b>{label}</b>", "font": {"color": color, "size": 18}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": TEXT_LIGHT, "tickwidth": 1},
            "bar": {"color": color, "thickness": 0.25},
            "bgcolor": BG_CARD,
            "bordercolor": BG_DARK,
            "steps": [
                {"range": [0,  40], "color": "#1b3a1b"},
                {"range": [40, 70], "color": "#3a2e00"},
                {"range": [70, 100], "color": "#3a0a0a"},
            ],
            "threshold": {
                "line": {"color": color, "width": 4},
                "thickness": 0.75,
                "value": pct,
            },
        },
    ))
    fig.update_layout(
        paper_bgcolor=BG_CARD,
        plot_bgcolor=BG_CARD,
        font={"color": TEXT_LIGHT},
        margin=dict(l=20, r=20, t=40, b=20),
        height=280,
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Panel 2: Syndicate Graph (Pyvis)
# ---------------------------------------------------------------------------

def _clique_color(clique_idx: int) -> str:
    palette = [
        "#e91e63", "#9c27b0", "#3f51b5", "#03a9f4",
        "#009688", "#ff9800", "#795548", "#607d8b",
    ]
    return palette[clique_idx % len(palette)]


def render_syndicate_graph(
    account_id: str,
    nodes_df:   pd.DataFrame,
    edges_df:   pd.DataFrame,
    cliques:    list[list[str]],
) -> None:
    """
    Interactive Pyvis network graph.
    - Target account: large gold node at centre
    - Clique members: shared colour per clique
    - Edge width ∝ log(total_amount)
    """
    net = Network(
        height="460px",
        width="100%",
        bgcolor=BG_CARD,
        font_color=TEXT_LIGHT,
        directed=False,
    )
    net.set_options(json.dumps({
        "physics": {
            "barnesHut": {"gravitationalConstant": -8000, "springLength": 150},
            "stabilization": {"iterations": 100},
        },
        "interaction": {"hover": True, "dragNodes": True},
        "nodes": {"borderWidth": 2},
        "edges": {"smooth": {"type": "continuous"}},
    }))

    # Assign clique colour per node
    node_color: dict[str, str] = {}
    for ci, clique in enumerate(cliques):
        col = _clique_color(ci)
        for n in clique:
            node_color[n] = col

    # Add nodes
    for _, row in nodes_df.iterrows():
        nid   = row["account_id"]
        score = float(row.get("risk_score", 0.5))
        is_target = nid == account_id
        color  = "#ffd700" if is_target else node_color.get(nid, BLUE_ACCENT)
        size   = 35 if is_target else max(10, min(25, int(score * 30)))
        label  = nid[:8] + "…" if len(nid) > 8 else nid
        title  = (
            f"<b>{nid}</b><br>"
            f"Risk: {score * 100:.0f}/100<br>"
            f"Tx count: {int(row.get('tx_count', 0))}"
        )
        net.add_node(
            nid, label=label, title=title,
            color=color, size=size,
            shape="dot" if not is_target else "star",
            borderWidthSelected=4,
        )

    # Add edges
    if not edges_df.empty:
        max_vol = edges_df["total_amount"].max() if len(edges_df) else 1
        for _, row in edges_df.iterrows():
            src, tgt = row["source"], row["target"]
            if src in nodes_df["account_id"].values and tgt in nodes_df["account_id"].values:
                width = max(1.0, float(np.log1p(row["total_amount"]) /
                                       np.log1p(max_vol) * 8))
                title = (
                    f"${row['total_amount']:,.0f} total<br>"
                    f"{int(row['tx_count'])} transactions"
                )
                net.add_edge(src, tgt, width=width, title=title, color="#888888")

    # Write to temp file and embed via iframe
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        net.save_graph(f.name)
        html_path = f.name

    with open(html_path, "r") as f:
        html_content = f.read()
    os.unlink(html_path)

    st.components.v1.html(html_content, height=470, scrolling=False)


# ---------------------------------------------------------------------------
# Panel 3: NCUA Macro Overlay (dual-axis Plotly)
# ---------------------------------------------------------------------------

def render_macro_overlay(monthly_df: pd.DataFrame) -> None:
    """
    Dual-axis line chart:
      Left Y  — account monthly transaction volume
      Right Y — NCUA average credit card interest rate (%)

    Vertical shaded bands mark months where BOTH metrics spike
    (rate delta > 0.3 AND tx_count > median).
    """
    if monthly_df.empty or "ncua_cc_rate" not in monthly_df.columns:
        st.info("Insufficient transaction history for macro overlay.")
        return

    df = monthly_df.copy()
    df["month"] = pd.to_datetime(df["month"])

    # Identify co-spike periods for shading
    rate_spike  = df["ncua_cc_rate"].diff().fillna(0) > 0.25
    tx_median   = df["tx_count"].median()
    tx_high     = df["tx_count"] > tx_median
    co_spike    = rate_spike & tx_high

    fig = go.Figure()

    # --- Transaction volume bars ---
    fig.add_trace(go.Bar(
        x=df["month"],
        y=df["tx_count"],
        name="Tx Volume",
        marker_color=BLUE_ACCENT,
        opacity=0.6,
        yaxis="y1",
    ))

    # --- NCUA rate line ---
    fig.add_trace(go.Scatter(
        x=df["month"],
        y=df["ncua_cc_rate"],
        name="NCUA CC Rate (%)",
        line={"color": RED, "width": 2.5},
        mode="lines+markers",
        yaxis="y2",
    ))

    # --- Co-spike bands ---
    for _, row in df[co_spike].iterrows():
        fig.add_vrect(
            x0=row["month"] - pd.Timedelta(days=15),
            x1=row["month"] + pd.Timedelta(days=15),
            fillcolor="rgba(255,75,75,0.12)",
            line_width=0,
            annotation_text="⚠",
            annotation_position="top left",
            annotation_font_color=RED,
        )

    fig.update_layout(
        paper_bgcolor=BG_CARD,
        plot_bgcolor=BG_DARK,
        font={"color": TEXT_LIGHT},
        legend={"orientation": "h", "y": 1.1, "font": {"color": TEXT_LIGHT}},
        margin=dict(l=40, r=60, t=30, b=40),
        height=300,
        xaxis={"gridcolor": "#2a2d35", "title": "Month"},
        yaxis={
            "title": "Transaction Count",
            "gridcolor": "#2a2d35",
            "title_font": {"color": BLUE_ACCENT},
            "tickfont": {"color": BLUE_ACCENT},
        },
        yaxis2={
            "title": "NCUA CC Rate (%)",
            "overlaying": "y",
            "side": "right",
            "title_font": {"color": RED},
            "tickfont": {"color": RED},
            "gridcolor": "rgba(0,0,0,0)",
        },
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    # Correlation callout
    if len(df) >= 4:
        corr = df["tx_count"].corr(df["ncua_cc_rate"])
        if not np.isnan(corr):
            st.caption(
                f"📊 Pearson correlation between tx volume and NCUA CC rate: **{corr:.3f}**  "
                + ("— strong co-movement" if abs(corr) > 0.5 else "— moderate co-movement" if abs(corr) > 0.3 else "")
            )


# ---------------------------------------------------------------------------
# Panel 4: Behavioural Red Flags
# ---------------------------------------------------------------------------

def render_flags(flags: list[str]) -> None:
    for flag in flags:
        emoji = flag[:2]
        msg   = flag[2:].strip()
        if "🔴" in emoji:
            color = RED
        elif "🟡" in emoji:
            color = AMBER
        else:
            color = BLUE_ACCENT

        st.markdown(
            f"""
            <div style="
                background:{BG_DARK};
                border-left: 4px solid {color};
                padding: 8px 12px;
                margin-bottom: 8px;
                border-radius: 4px;
                color: {TEXT_LIGHT};
                font-size: 0.9rem;
            ">
                {emoji} {msg}
            </div>
            """,
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Card wrapper helper
# ---------------------------------------------------------------------------

def _card(title: str) -> None:
    st.markdown(
        f"""
        <div style="
            background:{BG_CARD};
            border-radius:8px;
            padding: 12px 16px 4px 16px;
            margin-bottom: 4px;
        ">
            <span style="color:{BLUE_ACCENT}; font-size:0.75rem;
                         font-weight:700; letter-spacing:0.1em;
                         text-transform:uppercase;">
                {title}
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Main render entrypoint
# ---------------------------------------------------------------------------

def render(account_id: str, dm: DataManager, pipeline: AMLPipeline | None = None) -> None:
    """
    Render the full 4-panel analyst dashboard for a given account.

    Parameters
    ----------
    account_id : the account being investigated
    dm         : DataManager instance (shared via session state)
    pipeline   : trained AMLPipeline; if None, uses stored DuckDB risk score
    """
    # ---- Resolve risk score ----
    score_row = dm.get_risk_score(account_id)

    if score_row is None and pipeline is not None:
        # Run inference on the fly
        with st.spinner("Running FLHR-MCL model…"):
            bundle = dm.build_node_features(account_id)
            stat_vec = np.array(
                [bundle["stat_features"].get(f, 0.0)
                 for f in __import__("core.data_manager", fromlist=["_STAT_FEATURE_NAMES"])._STAT_FEATURE_NAMES],
                dtype=np.float32,
            )[None, :]
            temp_arr = bundle["temporal_seq"][None, :, :]
            tx_df    = dm._get_account_txs(account_id)
            cliques  = dm.get_cliques_for_account(account_id)
            risk     = pipeline.predict_single(
                account_id,
                bundle["stat_features"],
                bundle["temporal_seq"],
                bundle["tx_count"],
                tx_df,
                cliques,
            )
            monthly  = dm.get_monthly_activity(account_id)
            flags    = generate_flags(account_id, risk, bundle["stat_features"], cliques, monthly)
            dm.write_risk_score(account_id, risk, flags)
            score_row = dm.get_risk_score(account_id)

    if score_row is None:
        st.warning(
            f"Account **{account_id}** found in transaction graph, "
            "but no risk score is available yet. "
            "Please run the model first (upload PaySim data and click **Analyse**)."
        )
        return

    risk_score = score_row["risk_score"]
    flags      = score_row["flags"]
    analyzed   = score_row["analyzed_at"]

    # ---- Fetch graph and macro data ----
    nodes_df, edges_df = dm.get_ego_network(account_id, hops=2, max_nodes=80)
    cliques             = dm.get_cliques_for_account(account_id)
    monthly_df          = dm.get_monthly_activity(account_id)

    # ---- Header ----
    col_title, col_meta = st.columns([3, 1])
    with col_title:
        st.markdown(
            f"<h2 style='color:{TEXT_LIGHT}; margin:0;'>Investigation: "
            f"<span style='color:{_risk_color(risk_score)};'>{account_id}</span></h2>",
            unsafe_allow_html=True,
        )
    with col_meta:
        st.caption(f"Analysed: {analyzed}")
        if cliques:
            st.caption(f"Cliques detected: {len(cliques)}")

    st.markdown("<hr style='border-color:#2a2d35; margin:8px 0;'>", unsafe_allow_html=True)

    # ---- Top row: Panel 1 + Panel 2 ----
    col1, col2 = st.columns([1, 2])

    with col1:
        _card("Trust Score")
        render_trust_score(risk_score)

        # Quick stats below the gauge
        stat = dm.build_statistical_features(account_id)
        st.markdown(
            f"""
            <div style="background:{BG_CARD}; border-radius:8px;
                        padding:10px 16px; margin-top:4px;">
                <table style="color:{TEXT_LIGHT}; font-size:0.85rem; width:100%;">
                    <tr><td>Total Txs</td><td align='right'><b>{int(stat.get('tx_count',0)):,}</b></td></tr>
                    <tr><td>Counterparties</td><td align='right'><b>{int(stat.get('unique_counterparts',0)):,}</b></td></tr>
                    <tr><td>Avg Tx Size</td><td align='right'><b>${stat.get('avg_amount',0):,.0f}</b></td></tr>
                    <tr><td>Velocity</td><td align='right'><b>{stat.get('tx_velocity',0):.2f} tx/day</b></td></tr>
                    <tr><td>Clique Memberships</td><td align='right'><b>{len(cliques)}</b></td></tr>
                </table>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        _card("Syndicate Graph — 2-hop Ego Network")
        if nodes_df.empty:
            st.info("No connected accounts found in the transaction graph.")
        else:
            render_syndicate_graph(account_id, nodes_df, edges_df, cliques)

    # ---- Bottom row: Panel 3 + Panel 4 ----
    col3, col4 = st.columns([1, 1])

    with col3:
        _card("NCUA Macro-Economic Overlay")
        render_macro_overlay(monthly_df)

    with col4:
        _card("Behavioural Red Flags")
        if flags:
            render_flags(flags)
        else:
            st.info("No flags stored. Re-run the model to generate flags.")

    # ---- Divider ----
    st.markdown("<br>", unsafe_allow_html=True)
