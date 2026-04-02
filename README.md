# 💰 Personal Finance Analyzer & Expense Predictor

A production-quality, full-stack ML application that analyzes financial transaction data and provides automated insights including expense categorization, spending predictions, anomaly detection, and user segmentation.

## ✨ Features

| Feature | Description | Model |
|---------|-------------|-------|
| 🏷️ **Expense Categorization** | Automatically classifies transactions into categories | Logistic Regression, Random Forest, XGBoost |
| 🔮 **Spending Predictions** | Forecasts next 30 days of spending | Linear Regression, Random Forest, ARIMA |
| 🚨 **Anomaly Detection** | Flags unusual/suspicious transactions | Isolation Forest |
| 👥 **Spending Segmentation** | Groups monthly spending patterns | K-Means Clustering |
| ⚡ **High Performance** | Concurrency control efficiently processes 50,000+ row datasets in seconds | ThreadPoolExecutor |
| 🎨 **Strict UI System** | Premium Emerald/Slate design adhering to a strict 8-point grid | Custom CSS / Streamlit |

## 🏗️ Architecture

```
┌─────────────────────────────┐     ┌──────────────────────────────┐
│    Streamlit Frontend       │────▶│    FastAPI Backend            │
│    (Port 8501)              │     │    (Port 8000)               │
│                             │     │                              │
│  ┌──────────────────────┐   │     │  ┌────────────────────────┐  │
│  │ Dashboard Pages      │   │     │  │ ML Pipeline            │  │
│  │ • Overview           │   │     │  │ • Preprocessing        │  │
│  │ • Predictions        │   │     │  │ • Categorization       │  │
│  │ • Anomalies          │   │     │  │ • Prediction           │  │
│  │ • Segmentation       │   │     │  │ • Anomaly Detection    │  │
│  └──────────────────────┘   │     │  │ • Segmentation         │  │
└─────────────────────────────┘     │  └────────────────────────┘  │
                                    │                              │
                                    │  ┌────────────────────────┐  │
                                    │  │ SQLite Database        │  │
                                    │  └────────────────────────┘  │
                                    └──────────────────────────────┘
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Generate Sample Data

```bash
python scripts/generate_sample_data.py
```

### 3. Launch Both Servers

```bash
python run.py
```

This starts:
- **FastAPI API** at `http://127.0.0.1:8000` (docs at `/docs`)
- **Streamlit Dashboard** at `http://localhost:8501`

### Alternative: Start Separately

```bash
# Terminal 1: Backend
uvicorn backend.main:app --reload --port 8000

# Terminal 2: Frontend
streamlit run frontend/app.py --theme.base dark
```

## 📁 CSV Format

Your CSV file should contain these columns:

| Column | Required | Description |
|--------|----------|-------------|
| `date` | ✅ | Transaction date (any parseable format) |
| `amount` | ✅ | Transaction amount (positive=expense, negative=income) |
| `category` | Optional | Transaction category (for supervised learning) |
| `description` | Optional | Transaction description (for NLP categorization) |

## 🔧 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/upload` | Upload CSV and trigger ML pipeline |
| GET | `/api/uploads` | List all uploads |
| GET | `/api/status/{id}` | Check pipeline processing status |
| GET | `/api/results/{id}/{type}` | Get results (summary, categorization, prediction, anomaly, segmentation) |
| GET | `/api/transactions/{id}` | Get processed transactions |

## 📂 Project Structure

```
├── backend/
│   ├── api/          # FastAPI routes & schemas
│   ├── core/         # Config & database
│   ├── ml/           # ML pipeline modules
│   ├── models/       # Saved .pkl model files
│   └── utils/        # Helper functions
├── frontend/
│   ├── app.py        # Streamlit main app
│   ├── pages/        # Dashboard pages
│   └── components/   # Reusable chart & sidebar components
├── data/             # Sample data & uploads
├── scripts/          # Data generation scripts
├── run.py            # Launch script
└── requirements.txt  # Dependencies
```

## 🧪 Tech Stack

- **Backend**: FastAPI, SQLAlchemy, SQLite
- **Frontend**: Streamlit, Plotly
- **ML**: scikit-learn, XGBoost, statsmodels
- **Data**: pandas, NumPy
