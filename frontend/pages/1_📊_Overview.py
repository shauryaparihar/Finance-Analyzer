"""
Overview Page — KPIs, category breakdown, spending trends.
"""
import streamlit as st
import requests
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from frontend.components.sidebar import render_sidebar, apply_custom_theme
from frontend.components.charts import (
    category_pie_chart, monthly_spending_chart, daily_spending_chart,
    model_comparison_chart, confusion_matrix_chart, COLORS,
)

st.set_page_config(page_title="Overview | Finance Analyzer", page_icon="📊", layout="wide")

# Apply unified Finsight theme
apply_custom_theme()

API_BASE = "http://127.0.0.1:8000/api"

upload_id, status = render_sidebar()

st.markdown("""
<h1 style="color: #F0F6FC; font-size: 2rem; font-weight: 500; margin-bottom: 24px;">
    Overview Dashboard
</h1>
""", unsafe_allow_html=True)

if not upload_id:
    st.info("Upload a CSV file to see your financial overview.")
    st.stop()

# Fetch summary
try:
    r = requests.get(f"{API_BASE}/results/{upload_id}/summary", timeout=10)
    if r.status_code != 200:
        st.warning("Summary not available yet. The pipeline may still be processing.")
        st.stop()
    summary = r.json()["data"]
except requests.ConnectionError:
    st.error("Cannot connect to the API. Make sure the backend is running.")
    st.stop()
except Exception as e:
    st.error(f"Error fetching data: {e}")
    st.stop()

# KPI Cards
st.markdown("")
c1, c2, c3, c4 = st.columns(4)
c1.metric("💳 Total Transactions", f"{summary.get('total_transactions', 0):,}")
c2.metric("💸 Total Spending", f"${summary.get('total_spending', 0):,.2f}")
c3.metric("💰 Total Income", f"${summary.get('total_income', 0):,.2f}")
c4.metric("📊 Avg Transaction", f"${summary.get('avg_transaction', 0):,.2f}")

st.markdown("")
c5, c6, c7, c8 = st.columns(4)
c5.metric("📈 Max Transaction", f"${summary.get('max_transaction', 0):,.2f}")
c6.metric("📉 Min Transaction", f"${summary.get('min_transaction', 0):,.2f}")
c7.metric("📏 Std Deviation", f"${summary.get('std_transaction', 0):,.2f}")
c8.metric("🏆 Top Category", summary.get("top_category", "N/A"))

st.markdown("---")

# Charts
col_left, col_right = st.columns(2)

with col_left:
    if summary.get("category_breakdown"):
        fig = category_pie_chart(summary["category_breakdown"])
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No category data available")

with col_right:
    if summary.get("monthly_spending"):
        fig = monthly_spending_chart(summary["monthly_spending"])
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No monthly data available")

# Categorization results
st.markdown("---")
st.markdown("""
<h2 style="color: #F0F6FC; font-size: 1.25rem; font-weight: 500;">🏷️ Expense Categorization Results</h2>
""", unsafe_allow_html=True)

try:
    r = requests.get(f"{API_BASE}/results/{upload_id}/categorization", timeout=10)
    if r.status_code == 200:
        cat_data = r.json()["data"]

        c1, c2, c3 = st.columns(3)
        c1.metric("Best Model", cat_data.get("best_model", "N/A"))
        c2.metric("Accuracy", f"{cat_data.get('best_accuracy', 0):.1%}")
        c3.metric("Models Tested", str(len(cat_data.get("model_comparison", {}))))

        col1, col2 = st.columns(2)
        with col1:
            if cat_data.get("model_comparison"):
                fig = model_comparison_chart(cat_data["model_comparison"], metric="accuracy", title="Model Accuracy Comparison")
                st.plotly_chart(fig, width="stretch")

        with col2:
            if cat_data.get("confusion_matrix") and cat_data.get("class_labels"):
                fig = confusion_matrix_chart(cat_data["confusion_matrix"], cat_data["class_labels"])
                st.plotly_chart(fig, width="stretch")
    else:
        st.info("Categorization results not available yet.")
except Exception as e:
    st.warning(f"Could not load categorization results: {e}")

# Transaction table
st.markdown("---")
st.markdown("""
<h2 style="color: #F0F6FC; font-size: 1.25rem; font-weight: 500;">📋 Transaction Details</h2>
""", unsafe_allow_html=True)

try:
    r = requests.get(f"{API_BASE}/transactions/{upload_id}", timeout=10)
    if r.status_code == 200:
        txns = r.json()["transactions"]
        if txns:
            df = pd.DataFrame(txns)
            display_cols = [c for c in ["date", "amount", "category", "description", "predicted_category", "is_anomaly"] if c in df.columns]
            st.dataframe(
                df[display_cols].head(100),
                width="stretch",
                height=400,
            )
            st.caption(f"Showing first 100 of {len(txns)} transactions")
except Exception:
    pass
