"""
Sidebar component for the Streamlit dashboard.
"""
import streamlit as st
import requests
import time
from typing import Optional, Tuple

API_BASE = "http://127.0.0.1:8000/api"


def apply_custom_theme():
    """Apply the unified Finsight emerald/slate design system."""
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
        background: #0D1117 !important;
        border-right: 1px solid #30363D !important;
    }
    
    [data-testid="stSidebarNav"] {
        background-color: transparent !important;
        padding-top: 2rem !important;
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
        width: 100% !important;
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

    /* Hide Streamlit default branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


def render_sidebar() -> Tuple[Optional[int], Optional[str]]:
    """
    Render the sidebar with file upload and dataset selector.
    Returns: (selected_upload_id, upload_status)
    """
    with st.sidebar:
        # Logo / branding
        st.markdown("""
        <div style="padding: 16px 8px; margin-bottom: 24px; border-bottom: 1px solid #30363D;">
            <div style="font-size: 1.5rem; font-weight: 700; color: #00D4C8; margin-bottom: 4px;">
                <span style="margin-right: 8px;">💰</span>FinanceAI
            </div>
            <div style="font-size: 0.875rem; color: #8B949E; font-weight: 500;">Intelligent Expense Analysis</div>
        </div>
        """, unsafe_allow_html=True)

        # File upload
        st.markdown("### 📁 Upload Data")
        uploaded_file = st.file_uploader(
            "Upload CSV file",
            type=["csv"],
            help="Upload a CSV with columns: date, amount, category, description",
            key="csv_uploader",
        )

        if uploaded_file is not None:
            if st.button("🚀 Process File", width="stretch", type="primary"):
                with st.spinner("Uploading and processing..."):
                    try:
                        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "text/csv")}
                        response = requests.post(f"{API_BASE}/upload", files=files, timeout=30)

                        if response.status_code == 200:
                            result = response.json()
                            st.session_state["current_upload_id"] = result["upload_id"]
                            st.success(f"✅ Uploaded! Processing {result['num_rows']} rows...")

                            # Poll for completion
                            _poll_status(result["upload_id"])
                        else:
                            st.error(f"Upload failed: {response.json().get('detail', 'Unknown error')}")
                    except requests.ConnectionError:
                        st.error("⚠️ Cannot connect to the API server. Make sure the backend is running.")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")

        st.markdown("---")

        # Dataset selector
        st.markdown("### 📋 Previous Uploads")
        selected_upload_id = _render_upload_selector()

        st.markdown("---")

        # API status
        _render_api_status()

        return selected_upload_id, st.session_state.get("upload_status")


def _poll_status(upload_id: int, max_wait: int = 300):
    """Poll the API for pipeline completion."""
    progress = st.progress(0)
    status_text = st.empty()
    
    start = time.time()
    while time.time() - start < max_wait:
        try:
            r = requests.get(f"{API_BASE}/status/{upload_id}", timeout=5)
            if r.status_code == 200:
                status = r.json()["status"]
                st.session_state["upload_status"] = status

                if status == "completed":
                    progress.progress(100)
                    status_text.success("✅ Pipeline completed!")
                    time.sleep(1)
                    st.rerun()
                    return
                elif status == "failed":
                    progress.progress(100)
                    status_text.error("❌ Pipeline failed. Check logs.")
                    return
                else:
                    elapsed = time.time() - start
                    progress.progress(min(int(elapsed / max_wait * 90), 90))
                    status_text.info(f"⏳ Processing... ({int(elapsed)}s)")
        except Exception:
            pass
        time.sleep(2)

    status_text.warning("⏱ Processing is taking longer than expected. Check back later.")


def _render_upload_selector() -> Optional[int]:
    """Show dropdown of previous uploads."""
    try:
        r = requests.get(f"{API_BASE}/uploads", timeout=5)
        if r.status_code == 200:
            uploads = r.json()
            if uploads:
                options = {
                    f"{u['filename']} ({u['num_rows']} rows) - {u['status']}": u["id"]
                    for u in uploads
                }
                selected = st.selectbox(
                    "Select dataset",
                    options.keys(),
                    key="upload_selector",
                )
                if selected:
                    upload_id = options[selected]
                    st.session_state["current_upload_id"] = upload_id
                    return upload_id
            else:
                st.info("No uploads yet. Upload a CSV file above.")
    except requests.ConnectionError:
        st.warning("API not connected")
    except Exception:
        pass
    return st.session_state.get("current_upload_id")


def _render_api_status():
    """Show API connection status."""
    # API Status
    try:
        r = requests.get(f"{API_BASE}/health", timeout=2)
        status_color = "#00D4C8" if r.status_code == 200 else "#F85149"
    except Exception:
        status_color = "#F85149"

    st.markdown(f"""
        <div style="display: flex; align-items: center; padding: 8px 16px; background: #1A2035; border: 1px solid #30363D; border-radius: 8px; margin-bottom: 24px;">
            <div style="width: 8px; height: 8px; border-radius: 50%; background-color: {status_color}; margin-right: 12px; box-shadow: 0 0 8px {status_color}80;"></div>
            <span style="color: #8B949E; font-size: 0.875rem; font-weight: 500;">Engine Status</span>
        </div>
    """, unsafe_allow_html=True)
