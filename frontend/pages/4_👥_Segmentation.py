"""
Segmentation Page — Spending pattern clusters.
"""
import streamlit as st
import requests
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from frontend.components.sidebar import render_sidebar
from frontend.components.charts import cluster_scatter_chart, elbow_chart, COLORS

st.set_page_config(page_title="Segmentation | Finance Analyzer", page_icon="👥", layout="wide")

st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
.stApp { background: linear-gradient(180deg, #0F172A 0%, #1E293B 100%); font-family: 'Inter', sans-serif; }
div[data-testid="stMetric"] { background: linear-gradient(135deg, rgba(245,158,11,0.1), rgba(16,185,129,0.05)); border: 1px solid rgba(245,158,11,0.2); border-radius: 12px; padding: 16px; }
div[data-testid="stMetric"]:hover { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(245,158,11,0.15); }
div[data-testid="stMetric"] label { color: #94A3B8 !important; }
div[data-testid="stMetric"] div[data-testid="stMetricValue"] { color: #F8FAFC !important; font-weight: 700 !important; }
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #1E293B 0%, #0F172A 100%); border-right: 1px solid rgba(148,163,184,0.1); }
.stButton > button { background: linear-gradient(135deg, #6366F1, #8B5CF6) !important; color: white !important; border: none !important; border-radius: 8px !important; }
#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
</style>""", unsafe_allow_html=True)

API_BASE = "http://127.0.0.1:8000/api"

upload_id, status = render_sidebar()

st.markdown("""
<h1 style="color: #F0F6FC; font-size: 2rem; font-weight: 500; margin-bottom: 8px;">
    Spending Segmentation
</h1>
<p style="color: #8B949E; margin-bottom: 24px;">Discover your monthly spending patterns through K-Means clustering</p>
""", unsafe_allow_html=True)

if not upload_id:
    st.info("Upload a CSV file to see spending segmentation.")
    st.stop()

# Fetch segmentation results
try:
    r = requests.get(f"{API_BASE}/results/{upload_id}/segmentation", timeout=10)
    if r.status_code != 200:
        st.warning("Segmentation results not available yet.")
        st.stop()
    seg_data = r.json()["data"]
except requests.ConnectionError:
    st.error("Cannot connect to the API.")
    st.stop()
except Exception as e:
    st.error(f"Error: {e}")
    st.stop()

if "error" in seg_data:
    st.warning(seg_data["error"])
    st.stop()

# KPIs
st.markdown("")
c1, c2, c3 = st.columns(3)
c1.metric("Optimal Clusters", str(seg_data.get("best_k", "N/A")))
c2.metric("Silhouette Score", f"{seg_data.get('silhouette_score', 0):.3f}")
c3.metric("Months Analyzed", str(len(seg_data.get("scatter_data", []))))

st.markdown("---")

# Charts
col1, col2 = st.columns(2)

with col1:
    if seg_data.get("scatter_data"):
        fig = cluster_scatter_chart(seg_data["scatter_data"])
        st.plotly_chart(fig, width="stretch")

with col2:
    elbow = seg_data.get("elbow_data", {})
    if elbow:
        fig = elbow_chart(
            elbow["k_values"], elbow["inertias"], elbow["silhouettes"],
            seg_data["best_k"]
        )
        st.plotly_chart(fig, width="stretch")

# Cluster profiles
st.markdown("---")
st.markdown("""
<h3 style="color: #F0F6FC; font-size: 1.25rem; font-weight: 500; margin-bottom: 24px;">Cluster Profiles</h3>
""", unsafe_allow_html=True)

profiles = seg_data.get("cluster_profiles", [])
if profiles:
    # FinSight-aligned color mapping to maintain discipline while differentiating clusters slightly.
    cluster_colors = ["#00D4C8", "#58A6FF", "#A371F7", "#FFA657", "#F85149", "#00B3A6", "#408BE8", "#8957E5"]

    cols = st.columns(min(len(profiles), 4))
    for i, profile in enumerate(profiles):
        color = cluster_colors[i % len(cluster_colors)]
        with cols[i % len(cols)]:
            label = profile.get("label", f"Cluster {profile['cluster_id']}")
            # Pre-format to avoid IDE linter bugs with inline specifiers
            avg_sp_fmt = f"${profile['avg_total_spending']:,.2f}"
            avg_tx_fmt = f"{profile['avg_transactions']:.0f}"
            avg_tx_sz_fmt = f"${profile['avg_transaction_size']:,.2f}"

            html_content = """
                <div style="background: #161B22; border: 1px solid #30363D; border-radius: 8px; padding: 24px; margin-bottom: 16px; transition: border-color 0.2s ease;" 
                onmouseover="this.style.borderColor='#00D4C8'" onmouseout="this.style.borderColor='#30363D'">
                <div style="display: inline-block; background: {c}15; color: {c}; padding: 4px 12px; border-radius: 16px; font-size: 0.75rem; font-weight: 600; margin-bottom: 16px;">Cluster {c_id}</div>
                <h4 style="color: #F0F6FC; margin-bottom: 16px; font-size: 1.125rem; font-weight: 500;">{lbl}</h4>
                <div style="display: grid; gap: 16px;">
                <div><span style="display: block; color: #8B949E; font-size: 0.875rem; margin-bottom: 4px;">Months</span>
                <span style="color: #F0F6FC; font-weight: 500;">{n_mon}</span></div>
                <div><span style="display: block; color: #8B949E; font-size: 0.875rem; margin-bottom: 4px;">Avg Monthly Spending</span>
                <span style="color: #F0F6FC; font-weight: 500;">{avg_sp}</span></div>
                <div><span style="display: block; color: #8B949E; font-size: 0.875rem; margin-bottom: 4px;">Avg Transactions/Month</span>
                <span style="color: #F0F6FC; font-weight: 500;">{avg_tx}</span></div>
                <div><span style="display: block; color: #8B949E; font-size: 0.875rem; margin-bottom: 4px;">Avg Transaction Size</span>
                <span style="color: #F0F6FC; font-weight: 500;">{avg_tx_sz}</span></div>
                </div></div>
            """.format(
                c=color,
                c_id=profile["cluster_id"],
                lbl=label,
                n_mon=profile["num_months"],
                avg_sp=avg_sp_fmt,
                avg_tx=avg_tx_fmt,
                avg_tx_sz=avg_tx_sz_fmt
            )
            st.markdown(html_content, unsafe_allow_html=True)

# Interpretation
st.markdown("---")
st.markdown("""
<div style="
    background: #161B22;
    border: 1px solid #30363D;
    border-radius: 8px;
    padding: 24px;
">
    <h4 style="color: #00D4C8; margin-bottom: 12px; font-weight: 500;">How to Read This</h4>
    <p style="color: #8B949E; font-size: 0.875rem; line-height: 1.6;">
        The segmentation analysis groups your monthly spending patterns into clusters using K-Means.
        Each cluster represents a distinct spending behavior — for example, months with high spending vs. low spending.
        The <strong style="color: #F0F6FC;">silhouette score</strong> (range -1 to 1) indicates how well-separated the clusters are.
        Higher scores mean more distinct spending patterns. The <strong style="color: #F0F6FC;">PCA scatter plot</strong> 
        visualizes these clusters in 2D space, where proximity indicates similar spending behavior.
    </p>
</div>
""", unsafe_allow_html=True)
