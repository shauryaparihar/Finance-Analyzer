"""
Anomalies Page — Suspicious transaction detection.
"""
import streamlit as st
import requests
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from frontend.components.sidebar import render_sidebar
from frontend.components.charts import anomaly_timeline_chart, anomaly_score_distribution, COLORS

st.set_page_config(page_title="Anomalies | Finance Analyzer", page_icon="🚨", layout="wide")



API_BASE = "http://127.0.0.1:8000/api"

upload_id, status = render_sidebar()

st.markdown("""
<h1 style="color: #F0F6FC; font-size: 2rem; font-weight: 500; margin-bottom: 8px;">
    Anomaly Detection
</h1>
<p style="color: #8B949E; margin-bottom: 24px;">AI-powered detection of unusual and suspicious transactions</p>
""", unsafe_allow_html=True)

if not upload_id:
    st.info("Upload a CSV file to detect anomalies.")
    st.stop()

# Fetch anomaly results
try:
    r = requests.get(f"{API_BASE}/results/{upload_id}/anomaly", timeout=10)
    if r.status_code != 200:
        st.warning("Anomaly results not available yet.")
        st.stop()
    anomaly_data = r.json()["data"]
except requests.ConnectionError:
    st.error("Cannot connect to the API.")
    st.stop()
except Exception as e:
    st.error(f"Error: {e}")
    st.stop()

if "error" in anomaly_data:
    st.warning(anomaly_data["error"])
    st.stop()

# KPIs
st.markdown("")
c1, c2, c3, c4 = st.columns(4)
c1.metric("📊 Total Transactions", f"{anomaly_data.get('total_transactions', 0):,}")
c2.metric("🚨 Anomalies Found", str(anomaly_data.get("total_anomalies", 0)))
c3.metric("📈 Anomaly Rate", f"{anomaly_data.get('anomaly_rate', 0)}%")

score_stats = anomaly_data.get("score_stats", {})
c4.metric("📏 Score Threshold", f"{score_stats.get('threshold', 0):.4f}")

st.markdown("---")

# Anomaly timeline
try:
    r = requests.get(f"{API_BASE}/transactions/{upload_id}", timeout=10)
    if r.status_code == 200:
        txns = r.json()["transactions"]
        if txns:
            txn_df = pd.DataFrame(txns)
            txn_df["date"] = pd.to_datetime(txn_df["date"])
            expenses_df = txn_df[txn_df["amount"] > 0].copy()
            if "is_anomaly" in expenses_df.columns:
                fig = anomaly_timeline_chart(expenses_df)
                st.plotly_chart(fig, width="stretch")
except Exception:
    pass

# Score distribution
col1, col2 = st.columns(2)

with col1:
    if anomaly_data.get("all_scores") and anomaly_data.get("all_labels"):
        fig = anomaly_score_distribution(anomaly_data["all_scores"], anomaly_data["all_labels"])
        st.plotly_chart(fig, width="stretch")

with col2:
    st.markdown("""
    <h3 style="color: #F0F6FC; font-size: 1.25rem; font-weight: 500; margin-bottom: 16px;">Score Statistics</h3>
    """, unsafe_allow_html=True)
    
    st.markdown(f"""
    <div style="
        background: #161B22;
        border: 1px solid #30363D;
        border-radius: 8px;
        padding: 24px;
    ">
        <div style="display: grid; gap: 24px;">
            <div>
                <span style="display: block; color: #8B949E; font-size: 0.875rem; margin-bottom: 4px;">Mean Normal Score</span>
                <span style="color: #00D4C8; font-size: 1.25rem; font-weight: 500;">{score_stats.get('mean_normal', 0):.4f}</span>
            </div>
            <div>
                <span style="display: block; color: #8B949E; font-size: 0.875rem; margin-bottom: 4px;">Mean Anomaly Score</span>
                <span style="color: #F85149; font-size: 1.25rem; font-weight: 500;">{score_stats.get('mean_anomaly', 0):.4f}</span>
            </div>
            <div>
                <span style="display: block; color: #8B949E; font-size: 0.875rem; margin-bottom: 4px;">Decision Threshold</span>
                <span style="color: #FFA657; font-size: 1.25rem; font-weight: 500;">{score_stats.get('threshold', 0):.4f}</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# Flagged transactions table
st.markdown("---")
st.markdown("""
<h3 style="color: #F0F6FC; font-size: 1.25rem; font-weight: 500; margin-bottom: 16px;">Flagged Suspicious Transactions</h3>
""", unsafe_allow_html=True)

flagged = anomaly_data.get("flagged_transactions", [])
if flagged:
    flagged_df = pd.DataFrame(flagged)
    flagged_df = flagged_df.rename(columns={
        "date": "Date",
        "amount": "Amount ($)",
        "category": "Category",
        "description": "Description",
        "anomaly_score": "Anomaly Score",
    })
    flagged_df["Amount ($)"] = flagged_df["Amount ($)"].round(2)
    flagged_df["Anomaly Score"] = flagged_df["Anomaly Score"].round(4)

    st.dataframe(
        flagged_df,
        width="stretch",
        height=400,
        column_config={
            "Amount ($)": st.column_config.NumberColumn(format="$%.2f"),
        },
    )
    st.caption(f"Showing {len(flagged)} flagged transactions, sorted by anomaly severity")
else:
    st.success("No anomalies detected in your transactions! 🎉")
