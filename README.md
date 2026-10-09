# Personal Finance Analyzer and Expense Predictor

A production-quality, full-stack machine learning application that analyzes financial transaction data. It provides automated insights including expense categorization, spending predictions, anomaly detection, and user segmentation through a modern React dashboard.

**Live Demo**: [finance-analyzer-5n87ronca-shaurya-9039.vercel.app](https://finance-analyzer-5n87ronca-shaurya-9039.vercel.app)

## Features

| Feature | Description | Model |
|---------|-------------|-------|
| Expense Categorization | Automatically classifies transactions into categories | Logistic Regression, Random Forest, XGBoost |
| Spending Forecast | Forecasts the next 31 days; a lag-feature random forest is used only if it beats a seasonal-naive baseline in rolling backtests | Seasonal naive, Random Forest |
| Unusual Transaction Review | Ranks the top 10 expenses that stand out for their category, with a reason; you confirm or dismiss each (not fraud detection) | Category-relative robust deviation |
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
                                    │  │ PostgreSQL Database    │  │
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

### 2. Train the categorizer (optional: a trained model is already included)

```bash
python -m backend.ml.prepare_training_data   # download the synthetic training data
python -m backend.ml.train_categorizer       # train + evaluate + write backend/artifacts/categorizer/
```

See `docs/model_card.md` for what the model can and cannot do. All reported scores are on synthetic data.

### 3. Generate Sample Data

Create a baseline dataset for testing:
```bash
python scripts/generate_sample_data.py
```

### 4. Launch the Application

Start the backend server:
```bash
docker compose up -d db          # PostgreSQL
alembic upgrade head             # create/upgrade the database schema
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

All endpoints except register/login/health need `Authorization: Bearer <token>`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/auth/register | Create an account |
| POST | /api/auth/login | Get a short-lived access token |
| GET | /api/auth/me | Current user |
| POST | /api/uploads | Upload a CSV: 202 queued, or 200 `reused` if you already analysed the same file; optional `amount_convention` |
| GET | /api/uploads | List your uploads |
| GET | /api/uploads/{id} | Upload details |
| GET | /api/uploads/{id}/status | Overall status plus per-module status, timing and errors |
| GET | /api/uploads/{id}/summary | Spending summary |
| GET | /api/uploads/{id}/forecast | Spending forecast with backtest scores vs a baseline |
| GET | /api/uploads/{id}/budget-risk | Spent so far and projected month-end per budget |
| GET | /api/budgets | Your monthly budgets |
| PUT | /api/budgets/{category} | Create or update a monthly limit |
| DELETE | /api/budgets/{category} | Remove a budget |
| GET | /api/uploads/{id}/anomalies | Unusual-transaction review queue |
| PATCH | /api/transactions/{id}/anomaly-review | Confirm or dismiss a queued transaction |
| GET | /api/uploads/{id}/transactions | Transactions (`limit`, `offset`, `review_required`) |
| PATCH | /api/transactions/{id}/category | Set your own category for a transaction |
| DELETE | /api/uploads/{id} | Delete an upload and its data |
| GET | /healthz, /readyz | Liveness and readiness |

## Project Structure

- **src/**: React frontend source code (components, hooks, pages).
- **backend/**: FastAPI application, ML modules, and data models.
- **data/**: Local storage for uploads and sample datasets.
- **scripts/**: Utility scripts for data generation and testing.

## Tech Stack

- **Frontend**: React 18, Vite, Tailwind CSS, Recharts
- **Backend**: FastAPI, SQLAlchemy, Alembic, PostgreSQL
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
| `DATABASE_URL` | Render | PostgreSQL connection string (`postgresql+psycopg://...`; defaults to the local Docker database) |
| `VITE_API_URL` | Vercel | Backend URL for API calls |



## Operations

- Logs are one JSON object per line on stdout (event, request id, upload id, module, duration, status). Transaction text, passwords and tokens are never logged.
- `GET /healthz` is liveness; `GET /readyz` checks the database, the categorizer model and the job runner.
- Analyses run in a bounded in-process worker pool (`ANALYSIS_WORKERS`, default 2); a restart interrupts a running analysis and the next start marks it failed. See `.env.example` for the settings.
- `python -m backend.services.ops_report` prints aggregate job, failure, timing, model-version and forecast-method counts from the database.
