"""
Predictions Page — Future spending forecasts and model comparison.
"""
import streamlit as st
import requests
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from frontend.components.sidebar import render_sidebar
from frontend.components.charts import prediction_chart, model_comparison_chart, COLORS

st.set_page_config(page_title="Predictions | Finance Analyzer", page_icon="🔮", layout="wide")



API_BASE = "http://127.0.0.1:8000/api"

upload_id, status = render_sidebar()

st.markdown("""
<h1 style="color: #F0F6FC; font-size: 2rem; font-weight: 500; margin-bottom: 8px;">
    Expense Predictions
</h1>
<p style="color: #8B949E; margin-bottom: 24px;">ML-powered forecasting of your future spending patterns</p>
""", unsafe_allow_html=True)

if not upload_id:
    st.info("Upload a CSV file to see spending predictions.")
    st.stop()

# Fetch prediction results
try:
    r = requests.get(f"{API_BASE}/results/{upload_id}/prediction", timeout=10)
    if r.status_code != 200:
        st.warning("Prediction results not available yet. The pipeline may still be processing.")
        st.stop()
    pred_data = r.json()["data"]
except requests.ConnectionError:
    st.error("Cannot connect to the API. Make sure the backend is running.")
    st.stop()
except Exception as e:
    st.error(f"Error: {e}")
    st.stop()

if "error" in pred_data:
    st.warning(pred_data["error"])
    st.stop()

# KPIs
st.markdown("")
c1, c2, c3, c4 = st.columns(4)
c1.metric("🏆 Best Model", pred_data.get("best_model", "N/A"))
c2.metric("📈 30-Day Forecast", f"${pred_data.get('total_predicted_30d', 0):,.2f}")
c3.metric("📊 Avg Daily Predicted", f"${pred_data.get('avg_predicted_daily', 0):,.2f}")

# Get best model metrics
model_comp = pred_data.get("model_comparison", {})
best_name = pred_data.get("best_model", "")
if best_name in model_comp:
    best_metrics = model_comp[best_name]
    c4.metric("📏 Best RMSE", f"${best_metrics.get('rmse', 0):,.2f}")

st.markdown("---")

# Prediction chart
if pred_data.get("test_dates") and pred_data.get("future_predictions"):
    fig = prediction_chart(
        test_dates=pred_data["test_dates"],
        test_actual=pred_data["test_actual"],
        test_predicted=pred_data["test_predicted"],
        future_predictions=pred_data["future_predictions"],
    )
    st.plotly_chart(fig, width="stretch")

st.markdown("---")

# Model comparison
col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    <h3 style="color: #F0F6FC; font-size: 1.25rem; font-weight: 500; margin-bottom: 16px;">Model Performance (RMSE)</h3>
    """, unsafe_allow_html=True)
    if model_comp:
        fig = model_comparison_chart(model_comp, metric="rmse", title="RMSE Comparison (Lower is Better)")
        st.plotly_chart(fig, width="stretch")

with col2:
    st.markdown("""
    <h3 style="color: #F0F6FC; font-size: 1.25rem; font-weight: 500; margin-bottom: 16px;">Model Performance (R²)</h3>
    """, unsafe_allow_html=True)
    if model_comp:
        fig = model_comparison_chart(model_comp, metric="r2", title="R² Score Comparison (Higher is Better)")
        st.plotly_chart(fig, width="stretch")

# Future predictions table
st.markdown("---")
st.markdown("""
<h3 style="color: #F0F6FC; font-size: 1.25rem; font-weight: 500; margin-bottom: 16px;">30-Day Forecast Details</h3>
""", unsafe_allow_html=True)

if pred_data.get("future_predictions"):
    future_df = pd.DataFrame(pred_data["future_predictions"])
    future_df.columns = ["Date", "Predicted Spending ($)"]
    future_df["Predicted Spending ($)"] = future_df["Predicted Spending ($)"].round(2)

    col1, col2 = st.columns([2, 1])
    with col1:
        st.dataframe(future_df, width="stretch", height=400)
    with col2:
        st.markdown(f"""
        <div style="
            background: #161B22;
            border: 1px solid #30363D;
            border-radius: 8px;
            padding: 24px;
        ">
            <h4 style="color: #00D4C8; margin-bottom: 24px; font-weight: 500;">Forecast Summary</h4>
            <div style="color: #F0F6FC; margin-bottom: 16px;">
                <span style="display: block; color: #8B949E; font-size: 0.875rem; margin-bottom: 4px;">Total 30-Day:</span>
                <span style="font-size: 1.5rem; font-weight: 500;">${pred_data.get('total_predicted_30d', 0):,.2f}</span>
            </div>
            <div style="color: #F0F6FC; margin-bottom: 16px;">
                <span style="display: block; color: #8B949E; font-size: 0.875rem; margin-bottom: 4px;">Daily Average:</span>
                <span style="font-size: 1.25rem; font-weight: 500;">${pred_data.get('avg_predicted_daily', 0):,.2f}</span>
            </div>
            <div style="color: #F0F6FC;">
                <span style="display: block; color: #8B949E; font-size: 0.875rem; margin-bottom: 4px;">Weekly Estimate:</span>
                <span style="font-size: 1.25rem; font-weight: 500;">${pred_data.get('avg_predicted_daily', 0) * 7:,.2f}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
