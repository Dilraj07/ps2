"""Routly — Streamlit Dashboard with dual-panel layout.

Left:  10x10 Plotly spatial grid (agents + orders + assignments)
Right: KPI cards + charts + Greedy vs Hungarian toggle

Usage: streamlit run dashboard.py
"""
import streamlit as st
import plotly.graph_objects as go
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main import run_simulation

st.set_page_config(page_title="Routly Dashboard", layout="wide")

st.markdown("""
<style>
.metric-card {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    border-radius: 12px; padding: 20px; text-align: center;
    border: 1px solid #0f3460; margin: 5px;
}
.metric-value { font-size: 2.2em; font-weight: 700; color: #e94560; }
.metric-label { font-size: 0.9em; color: #a0a0b0; margin-top: 4px; }
</style>
""", unsafe_allow_html=True)

st.title("Routly - Smart Dispatch Dashboard")
st.caption("Team Greater N0ida | 2nd Year | Event-Driven Hungarian Dispatch")

# Sidebar controls
with st.sidebar:
    st.header("Controls")
    mode = st.selectbox("Dispatch Mode", ["hungarian", "greedy"], index=0)
    run_comparison = st.checkbox("Run Greedy vs Hungarian Comparison", value=False)
    st.markdown("---")
    st.subheader("Scoring Weights")
    w_sla = st.slider("SLA Weight", 0.0, 1.0, 0.40, 0.05)
    w_travel = st.slider("Travel Weight", 0.0, 1.0, 0.30, 0.05)
    w_fair = st.slider("Fairness Weight", 0.0, 1.0, 0.20, 0.05)
    w_rating = st.slider("Rating Weight", 0.0, 1.0, 0.10, 0.05)
    total_w = w_sla + w_travel + w_fair + w_rating
    if abs(total_w - 1.0) > 0.01:
        st.warning(f"Weights sum to {total_w:.2f}, normalizing...")
        w_sla, w_travel, w_fair, w_rating = [w/total_w for w in [w_sla, w_travel, w_fair, w_rating]]
    weights = {"sla": w_sla, "travel": w_travel, "fairness": w_fair, "rating": w_rating}
    run_btn = st.button("Run Simulation", type="primary", use_container_width=True)

if run_btn or "result" not in st.session_state:
    with st.spinner("Running simulation..."):
        st.session_state["result"] = run_simulation(mode=mode, custom_weights=weights)
        if run_comparison:
            other = "greedy" if mode == "hungarian" else "hungarian"
            st.session_state["comparison"] = run_simulation(mode=other, custom_weights=weights)

result = st.session_state["result"]
summary = result["summary"]
breakdown = result["breakdown_by_priority"]
assignments = result.get("assignment_log", [])

# ── KPI Cards ──
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Orders Delivered", summary["total_orders"])
with col2:
    st.metric("SLA Compliance", f"{summary['sla_compliance_rate_percent']}%")
with col3:
    st.metric("Avg Delivery", f"{summary['average_delivery_time']:.1f} min")
with col4:
    st.metric("Avg SLA Margin", f"{summary['average_sla_margin']:.1f} min")
with col5:
    st.metric("Fairness StdDev", f"{summary['fairness_std_dev']:.2f}")

st.markdown("---")

# ── Dual Panel ──
left_col, right_col = st.columns([1, 1])

# LEFT: Spatial Grid
with left_col:
    st.subheader("10x10 Dispatch Grid")
    fig = go.Figure()

    # Draw grid lines
    for i in range(10):
        fig.add_shape(type="line", x0=i, x1=i, y0=0, y1=9,
                      line=dict(color="#333", width=0.5))
        fig.add_shape(type="line", x0=0, x1=9, y0=i, y1=i,
                      line=dict(color="#333", width=0.5))

    # Plot assignment lines
    colors_p = {"high": "#ef4444", "normal": "#f59e0b", "low": "#22c55e"}
    for a in assignments:
        fx, fy = a["agent_from"]
        tx, ty = a["order_location"]
        fig.add_trace(go.Scatter(
            x=[fx, tx], y=[fy, ty], mode="lines",
            line=dict(color=colors_p.get(a["priority"], "#666"), width=1, dash="dot"),
            opacity=0.3, showlegend=False, hoverinfo="skip",
        ))

    # Plot order destinations
    for p_name, marker, color in [("high", "triangle-up", "#ef4444"),
                                   ("normal", "square", "#f59e0b"),
                                   ("low", "diamond", "#22c55e")]:
        pts = [a for a in assignments if a["priority"] == p_name]
        if pts:
            fig.add_trace(go.Scatter(
                x=[p["order_location"][0] for p in pts],
                y=[p["order_location"][1] for p in pts],
                mode="markers", name=f"{p_name.title()} Orders",
                marker=dict(symbol=marker, size=10, color=color, line=dict(width=1, color="white")),
                text=[p["order_id"] for p in pts], hoverinfo="text",
            ))

    # Plot agent start positions (unique)
    agent_starts: dict[str, tuple] = {}
    for a in assignments:
        if a["agent_id"] not in agent_starts:
            agent_starts[a["agent_id"]] = a["agent_from"]
    if agent_starts:
        fig.add_trace(go.Scatter(
            x=[v[0] for v in agent_starts.values()],
            y=[v[1] for v in agent_starts.values()],
            mode="markers+text", name="Agents",
            marker=dict(symbol="circle", size=14, color="#3b82f6",
                        line=dict(width=2, color="white")),
            text=list(agent_starts.keys()),
            textposition="top center", textfont=dict(size=8, color="white"),
        ))

    fig.update_layout(
        xaxis=dict(range=[-0.5, 9.5], dtick=1, title="X"),
        yaxis=dict(range=[-0.5, 9.5], dtick=1, title="Y"),
        height=550, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=40, r=20, t=40, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

# RIGHT: Charts
with right_col:
    st.subheader("Delivery Time by Priority")
    prios = ["high", "normal", "low"]
    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        x=[p.title() for p in prios],
        y=[breakdown[p]["delivery_stats"]["mean"] for p in prios],
        marker_color=["#ef4444", "#f59e0b", "#22c55e"],
        text=[f"{breakdown[p]['delivery_stats']['mean']:.1f}" for p in prios],
        textposition="auto",
    ))
    fig_bar.update_layout(height=250, template="plotly_dark",
                          yaxis_title="Avg Time (min)", margin=dict(t=20, b=30))
    st.plotly_chart(fig_bar, use_container_width=True)

    st.subheader("Agent Workload Distribution")
    counts = summary["agent_assignment_counts"]
    fig_hist = go.Figure()
    fig_hist.add_trace(go.Histogram(
        x=counts, nbinsx=max(counts) - min(counts) + 1,
        marker_color="#8b5cf6",
    ))
    fig_hist.update_layout(height=250, template="plotly_dark",
                           xaxis_title="Assignments", yaxis_title="Agents",
                           margin=dict(t=20, b=30))
    st.plotly_chart(fig_hist, use_container_width=True)

# ── Comparison Panel ──
if run_comparison and "comparison" in st.session_state:
    st.markdown("---")
    st.subheader("Greedy vs Hungarian Comparison")
    comp = st.session_state["comparison"]
    cs = comp["summary"]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(f"SLA ({mode.title()})", f"{summary['sla_compliance_rate_percent']}%")
    with c2:
        st.metric(f"SLA (Other)", f"{cs['sla_compliance_rate_percent']}%")
    with c3:
        st.metric(f"Fairness ({mode.title()})", f"{summary['fairness_std_dev']:.2f}")
    with c4:
        st.metric(f"Fairness (Other)", f"{cs['fairness_std_dev']:.2f}")

# ── Pareto Frontier ──
pareto_path = os.path.join(os.path.dirname(__file__), "output", "pareto_results.json")
if os.path.exists(pareto_path):
    st.markdown("---")
    st.subheader("Pareto Frontier (Weight Optimization)")
    with open(pareto_path, "r") as f:
        pareto = json.load(f)
    all_c = pareto.get("all_configurations", [])
    front = pareto.get("pareto_frontier", [])
    if all_c:
        fig_p = go.Figure()
        fig_p.add_trace(go.Scatter(
            x=[c["sla_compliance"] for c in all_c],
            y=[c["fairness_std_dev"] for c in all_c],
            mode="markers", name="All Configs",
            marker=dict(size=6, color="#666", opacity=0.5),
        ))
        if front:
            fig_p.add_trace(go.Scatter(
                x=[c["sla_compliance"] for c in front],
                y=[c["fairness_std_dev"] for c in front],
                mode="markers+lines", name="Pareto Frontier",
                marker=dict(size=10, color="#e94560"),
                line=dict(color="#e94560", width=2),
            ))
        fig_p.update_layout(
            xaxis_title="SLA Compliance %", yaxis_title="Fairness StdDev (lower=better)",
            height=400, template="plotly_dark", margin=dict(t=20),
        )
        st.plotly_chart(fig_p, use_container_width=True)
        rec = pareto.get("recommended", {})
        if rec:
            st.success(f"Recommended: SLA={rec.get('sla_compliance')}% | "
                       f"Fairness={rec.get('fairness_std_dev'):.3f} | "
                       f"Weights: {rec.get('weights')}")

st.markdown("---")
st.caption("Routly v2.0 | Hungarian + Adaptive + Delay Buffer | Greater N0ida")
