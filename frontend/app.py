"""
Personal Finance Analyzer & Expense Predictor — Streamlit Dashboard
"""
import streamlit as st

st.set_page_config(
    page_title="Finance Analyzer",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# FinSight theme CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');

    /* Global Typography & Background */
    .stApp {
        background: #0D1117;
        font-family: 'DM Sans', -apple-system, sans-serif;
        color: #F0F6FC;
    }

    /* Headings */
    h1, h2, h3, h4, h5, h6 {
        font-family: 'DM Sans', -apple-system, sans-serif !important;
        color: #F0F6FC !important;
        font-weight: 500 !important;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: #0D1117;
        border-right: 1px solid #30363D;
    }

    /* Metric cards */
    div[data-testid="stMetric"] {
        background: #161B22;
        border: 1px solid #30363D;
        border-radius: 8px;
        padding: 24px;
        transition: border-color 0.2s ease;
    }
    div[data-testid="stMetric"]:hover {
        border-color: #00D4C8;
    }
    div[data-testid="stMetric"] label {
        color: #8B949E !important;
        font-size: 0.875rem !important;
        font-weight: 500 !important;
        margin-bottom: 8px !important;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #F0F6FC !important;
        font-weight: 600 !important;
        font-size: 1.5rem !important;
    }

    /* DataFrames */
    .stDataFrame {
        border-radius: 8px;
        border: 1px solid #30363D;
        overflow: hidden;
    }

    /* Buttons */
    .stButton > button {
        background: #00D4C8 !important;
        color: #0D1117 !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 500 !important;
        padding: 8px 16px !important;
        transition: opacity 0.2s ease !important;
    }
    .stButton > button:hover {
        opacity: 0.9 !important;
    }

    /* File uploader */
    div[data-testid="stFileUploader"] {
        border-radius: 8px;
        border: 1px dashed #30363D;
        padding: 16px;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        margin-bottom: 16px;
        border-bottom: 1px solid #30363D;
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent;
        border-radius: 0;
        padding: 8px 16px;
        color: #8B949E;
        font-weight: 500;
        border-bottom: 2px solid transparent;
    }
    .stTabs [aria-selected="true"] {
        background: transparent !important;
        color: #F0F6FC !important;
        border-bottom: 2px solid #00D4C8 !important;
    }

    /* Expander */
    .streamlit-expanderHeader {
        background: #161B22;
        border-radius: 8px;
        border: 1px solid #30363D;
    }
    div[data-testid="stExpanderDetails"] {
        border: 1px solid #30363D;
        border-top: none;
        border-bottom-left-radius: 8px;
        border-bottom-right-radius: 8px;
    }

    /* Card-like containers */
    div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlock"] {
        border-radius: 8px;
    }

    /* Progress bar */
    .stProgress > div > div {
        background: #00D4C8 !important;
    }

    /* Select box */
    .stSelectbox label, .stFileUploader label {
        color: #8B949E !important;
        font-weight: 500 !important;
        margin-bottom: 8px !important;
    }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# Import sidebar
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from frontend.components.sidebar import render_sidebar

# Render sidebar
upload_id, status = render_sidebar()

# Main content
st.markdown("""
<div style="text-align: center; padding: 48px 0 32px 0;">
    <h1 style="
        color: #F0F6FC;
        font-size: 2.5rem;
        font-weight: 500;
        margin-bottom: 16px;
    ">Personal Finance Analyzer</h1>
    <p style="color: #8B949E; font-size: 1rem; max-width: 600px; margin: 0 auto; line-height: 1.5;">
        Upload your transaction data and get ML-powered insights including
        expense categorization, spending predictions, anomaly detection, and segmentation.
    </p>
</div>
""", unsafe_allow_html=True)

if not upload_id:
    # Landing page
    st.markdown("---")

    col1, col2, col3, col4 = st.columns(4)

    features = [
        ("🏷️", "Smart Categorization", "AI classifies your expenses using NLP"),
        ("🔮", "Spending Predictions", "30-day spending forecast with ML models"),
        ("🚨", "Anomaly Detection", "Flag unusual transactions automatically"),
        ("👥", "Spending Segments", "Discover your spending patterns"),
    ]

    for col, (icon, title, desc) in zip([col1, col2, col3, col4], features):
        with col:
            st.markdown(f"""
            <div style="
                background: #161B22;
                border: 1px solid #30363D;
                border-radius: 8px;
                padding: 24px;
                text-align: center;
                height: 180px;
                display: flex;
                flex-direction: column;
                justify-content: center;
                transition: border-color 0.2s ease;
            " onmouseover="this.style.borderColor='#00D4C8'" onmouseout="this.style.borderColor='#30363D'">
                <div style="font-size: 2rem; margin-bottom: 16px;">{icon}</div>
                <h3 style="font-size: 1rem; margin-bottom: 8px; color: #F0F6FC !important; font-weight: 500;">{title}</h3>
                <p style="color: #8B949E; font-size: 0.875rem; margin: 0; line-height: 1.5;">{desc}</p>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("")
    st.markdown("""
    <div style="text-align: center; padding: 32px 0;">
        <p style="color: #8B949E; font-size: 0.875rem;">
            👆 Upload a CSV file in the sidebar to get started.<br>
            Your CSV should have columns: <code style="color: #00D4C8; background: #1A2035; padding: 2px 6px; border-radius: 4px;">date</code>, 
            <code style="color: #00D4C8; background: #1A2035; padding: 2px 6px; border-radius: 4px;">amount</code>, 
            <code style="color: #00D4C8; background: #1A2035; padding: 2px 6px; border-radius: 4px;">category</code>, 
            <code style="color: #00D4C8; background: #1A2035; padding: 2px 6px; border-radius: 4px;">description</code>
        </p>
    </div>
    """, unsafe_allow_html=True)

else:
    st.info("👈 Select a page from the sidebar navigation to explore your data.")
