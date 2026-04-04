# Personal Finance Analyzer and Expense Predictor

A production-quality, full-stack machine learning application that analyzes financial transaction data. It provides automated insights including expense categorization, spending predictions, anomaly detection, and user segmentation through a modern React dashboard.

## Features

| Feature | Description | Model |
|---------|-------------|-------|
| Expense Categorization | Automatically classifies transactions into categories | Logistic Regression, Random Forest, XGBoost |
| Spending Predictions | Forecasts next 30 days of spending | Linear Regression, Random Forest, ARIMA |
| Anomaly Detection | Flags unusual or suspicious transactions | Isolation Forest |
| Spending Segmentation | Groups monthly spending patterns | K-Means Clustering |
| High Performance | Concurrency control processes 50,000+ row datasets in seconds | ThreadPoolExecutor |
| Premium UI System | Modern Emerald/Slate design using a strict 8-point grid | React / Tailwind CSS |

## Architecture

```
┌─────────────────────────────┐     ┌──────────────────────────────┐
│       React Frontend        │────▶│       FastAPI Backend        │
│       (Vite / Port 5173)    │     │       (Port 8000)            │
│                             │     │                              │
│  ┌──────────────────────┐   │     │  ┌────────────────────────┐  │
│  │ Dashboard Pages      │   │     │  │ ML Pipeline            │  │
│  │ - Overview           │   │     │  │ - Preprocessing        │  │
│  │ - Predictions        │   │     │  │ - Categorization       │  │
│  │ - Anomalies          │   │     │  │ - Prediction           │  │
│  │ - Segmentation       │   │     │  │ - Anomaly Detection    │  │
│  └──────────────────────┘   │     │  │ - Segmentation         │  │
└─────────────────────────────┘     │  └────────────────────────┘  │
                                    │                              │
                                    │  ┌────────────────────────┐  │
                                    │  │ SQLite Database        │  │
                                    │  └────────────────────────┘  │
                                    └──────────────────────────────┘
```

## Quick Start

### 1. Install Dependencies

Install Python dependencies for the backend:
```bash
pip install -r requirements.txt
```

Install Node.js dependencies for the frontend:
```bash
npm install
```

### 2. Generate Sample Data

Create a baseline dataset for testing:
```bash
python scripts/generate_sample_data.py
```

### 3. Launch the Application

Start the backend server:
```bash
python -m uvicorn backend.main:app --reload --port 8000
```

In a separate terminal, start the React frontend:
```bash
npm run dev
```

The application will be available at:
- **Dashboard**: http://localhost:5173
- **API Documentation**: http://127.0.0.1:8000/docs

## CSV Format

Uploaded files should follow this structure:

| Column | Required | Description |
|--------|----------|-------------|
| `date` | Yes | Transaction date (Y-M-D format preferred) |
| `amount` | Yes | Transaction amount (positive for expenses) |
| `category` | Optional | Known category for training |
| `description` | Optional | Transaction details for NLP processing |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/upload | Upload CSV and trigger ML pipeline |
| GET | /api/status/{id} | Check pipeline processing status |
| GET | /api/results/{id}/{type} | Retrieve specific ML results |
| GET | /api/transactions/{id} | List all processed transactions |

## Project Structure

- **src/**: React frontend source code (components, hooks, pages).
- **backend/**: FastAPI application, ML modules, and data models.
- **data/**: Local storage for uploads and sample datasets.
- **scripts/**: Utility scripts for data generation and testing.

## Tech Stack

- **Frontend**: React 18, Vite, Tailwind CSS, Recharts
- **Backend**: FastAPI, SQLAlchemy, SQLite
- **ML**: Scikit-Learn, XGBoost, Statsmodels
- **Data**: Pandas, NumPy

## Deployment

This project is configured for deployment on **Render** (backend) + **Vercel** (frontend).

### Backend — Render

1. Push your repo to GitHub.
2. Go to [render.com](https://render.com) → **New Web Service** → Connect your repo.
3. Render will auto-detect `render.yaml`. If not, use these settings:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
4. Set the following environment variables in the Render dashboard:
   - `ENVIRONMENT` = `production`
   - `FRONTEND_URL` = your Vercel URL (e.g. `https://finance-analyzer.vercel.app`)
5. Deploy. Note down your Render URL (e.g. `https://finance-analyzer-api.onrender.com`).

### Frontend — Vercel

1. Go to [vercel.com](https://vercel.com) → **New Project** → Import your GitHub repo.
2. Set the framework preset to **Vite**.
3. Set the following environment variable:
   - `VITE_API_URL` = your Render backend URL (e.g. `https://finance-analyzer-api.onrender.com`)
4. Update the `vercel.json` rewrite destination to your Render URL.
5. Deploy.

### Environment Variables Reference

| Variable | Where | Description |
|----------|-------|-------------|
| `ENVIRONMENT` | Render | Set to `production` to restrict CORS |
| `FRONTEND_URL` | Render | Vercel domain for CORS allowlist |
| `DATABASE_URL` | Render | DB connection string (defaults to SQLite) |
| `VITE_API_URL` | Vercel | Backend URL for API calls |

