# FinSight: budget risk and transaction review

Upload a CSV export of your bank transactions and FinSight shows where the money goes, warns when a monthly budget is on course to be exceeded, forecasts the next 31 days of spending, and queues the few expenses worth a second look. Every automatic decision can be overridden by you, and the app says plainly when it is unsure.

**Live demo:** https://finance-analyzer-nu.vercel.app (free hosting: the first request after a quiet period can take about a minute while the server wakes up). Use practice data, not your real statements.

**Status: a portfolio project, not production software.** The categorizer was trained on synthetic data and has not yet been measured on real statements (see [Limitations](#limitations)).

## What it does

| Screen | What you get | How it works |
|---|---|---|
| Upload and history | Validated upload, live progress per step, your past analyses, delete | A durable job queue stored in PostgreSQL |
| Overview and budgets | Totals, spending by category and month, monthly budgets with "projected month end" and a status | Plain aggregation plus a simple month-end projection |
| Forecast | Next 31 days of spending, with the backtest scores of the model and of a baseline | A lag-feature random forest is used **only if** it beats a seasonal-naive baseline in a rolling backtest |
| Unusual transactions | Up to 10 expenses that stand out for their category, each with a reason; you confirm or dismiss | Robust deviation from the category's typical amount; repeating charges (rent) are skipped. **Not fraud detection** |
| Category review | Rows with no category or an unsure guess, fixed from a list | TF-IDF + logistic regression, with a confidence threshold and an unrecognised-text guard |

## Architecture

```
Browser ──▶ Vercel (React app)
              │  /api/*  is forwarded to Render, so the login cookie stays on one site
              ▼
           Render (FastAPI in Docker) ──▶ PostgreSQL (Neon)
              │   • JWT access token (15 min, kept in memory) + rotating HttpOnly refresh cookie
              │   • upload ▶ validate ▶ queue a job row in PostgreSQL
              │   • worker threads claim jobs (FOR UPDATE SKIP LOCKED) and run:
              │       categorize ▶ forecast ▶ unusual-transaction ranking ▶ summary
              └── the model artifact (backend/artifacts/categorizer/) is trained offline and only loaded here
```

Data flow for one upload: the file is checked (size, rows, columns, dates, amounts), cleaned and saved as a queued job with its owner's id; a worker analyses it and saves each module's result or its error; the website polls the status and shows each screen as its result arrives. Every read and write is filtered by the logged-in user's id.

## Setup (local)

Requirements: Python 3.11, Node 22, Docker.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt     # backend + test tools (pinned model libraries)
npm ci                                   # frontend
cp .env.example .env                     # then adjust (see the table below)

docker compose up -d --wait db           # PostgreSQL
alembic upgrade head                     # create/upgrade the schema from an empty database
python -m uvicorn backend.main:app --reload --port 8000   # API  (http://127.0.0.1:8000/docs)
npm run dev                              # website (http://localhost:5173)
```

Or run the API in Docker too: `docker compose up --build` (applies migrations, serves on port 8000).

Open http://localhost:5173, create an account, and upload `data/sample_descriptions_only.csv` (no categories, so the model does the work) or `data/sample_transactions.csv` (categories filled in).

### Configuration (environment variables)

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | `development` (default) or `production` (Secure cookies, strict startup checks) |
| `DATABASE_URL` | PostgreSQL connection string (`postgres://` and `postgresql://` are accepted) |
| `JWT_SECRET` | Required in production: long random value; the built-in development secret is refused |
| `FRONTEND_URL` | The exact website origin allowed to use the cookie endpoints (no trailing slash) |
| `EXTRA_FRONTEND_ORIGINS` | Optional extra exact https origins, comma-separated, no wildcards |
| `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_DAYS`, `REFRESH_FAMILY_MAX_DAYS`, `COOKIE_SECURE` | Login session settings |
| `ANALYSIS_WORKERS`, `MAX_ACTIVE_JOBS`, `JOB_*` | Background-job settings |
| `LOG_LEVEL`, `LOG_EXCEPTION_MESSAGES` | Logging (exception messages stay off by default: they can echo user data) |

Full list with defaults: [`.env.example`](.env.example). Deployment settings: [`docs/deployment.md`](docs/deployment.md).

## CSV format

| Column | Required | Notes |
|---|---|---|
| `date` | Yes | `2025-03-15` preferred; mixed formats are parsed |
| `amount` | Yes | Positive = money spent, negative = money in, unless you tell the upload otherwise (`auto`, `expenses_positive`, `expenses_negative`; `auto` asks you to choose if the signs are too mixed to tell) |
| `description` | Optional | Without it a row stays "Uncategorized" for you to categorize |
| `category` | Optional | Your own label always wins over the model |

Limits: 5 MB and 50,000 rows per file; a few invalid rows are dropped and reported, many are refused.

## API summary

All endpoints except register, login, refresh, logout, session-check and the health checks need `Authorization: Bearer <access token>`. Interactive documentation: `/docs`.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login` | Create an account; log in (sets the HttpOnly refresh cookie) |
| POST | `/api/auth/refresh`, `/api/auth/logout`, `/api/auth/session-check` | Rotate the cookie and get a new access token; end the session; read-only cookie check |
| GET | `/api/auth/me` | Current user |
| POST | `/api/uploads` | Upload a CSV (202 queued, or 200 `reused` for the same file) |
| GET | `/api/uploads`, `/api/uploads/{id}`, `/api/uploads/{id}/status` | List, details, per-step status |
| GET | `/api/uploads/{id}/summary`, `/forecast`, `/budget-risk`, `/anomalies`, `/transactions` | Results |
| PATCH | `/api/transactions/{id}/category`, `/api/transactions/{id}/anomaly-review` | Your correction; confirm or dismiss an unusual transaction |
| DELETE | `/api/uploads/{id}` | Delete an upload and everything derived from it |
| GET/PUT/DELETE | `/api/budgets`, `/api/budgets/{category}` | Monthly budgets |
| GET | `/api/categories`, `/healthz`, `/readyz` | Category list; liveness; readiness (database and model) |

## Tests and checks

```bash
ruff check .                  # lint
pytest                        # backend: unit, API and end-to-end tests (needs the PostgreSQL container above)
npm run typecheck && npm test # frontend
npm run build                 # production build
python scripts/check_cookie_flow.py https://your-site --check-replay   # live login-cookie check
```

CI (`.github/workflows/ci.yml`) runs the same on every pull request and on `main`; `main` is protected: changes arrive through a pull request with both jobs green.

## Models and how they were evaluated

Details, numbers and limits are in [`docs/model_card.md`](docs/model_card.md). In short:

- **Categorizer:** TF-IDF + logistic regression, 17 categories, trained offline (`python -m backend.ml.prepare_training_data`, then `python -m backend.ml.train_categorizer`) on a **synthetic** public dataset. Grouped cross-validation macro-F1 is 0.942 ± 0.026 (held-out test set 0.972) **on synthetic data only**. Rows the model is unsure about, or whose text it does not recognise, are left "Uncategorized" for you.
- **Forecast:** rolling-origin backtest against a seasonal-naive baseline; the model is used only if its error is lower, and both scores are shown.
- **Unusual transactions:** a ranking aid built from a robust per-category deviation, tested on synthetic injected spikes (precision@10 about 0.89 at the shipped cut-off). The queue can be empty.

### Timing on a large upload

`python -m backend.benchmark` generates 50,000 deterministic synthetic rows and times the analysis (1 warm-up run discarded, 7 measured runs). Measured on an Apple-silicon Mac (macOS 15, 10 cores, Python 3.11.17, pandas 3.0.6, scikit-learn 1.9.1):

| Stage (50,000 rows) | Median | p95 (slowest of 7) |
|---|---|---|
| CSV parse and validation | 0.016 s | 0.016 s |
| Categorization (model inference) | 0.88 s | 0.91 s |
| Forecast (rolling backtest + fit) | 17.5 s | 17.6 s |
| Unusual-transaction ranking | 0.68 s | 0.69 s |
| Whole pipeline | 18.3 s | 18.3 s |

Not included: network time, login, database reads and writes, and the browser. The forecast dominates because it repeatedly fits a random forest during the backtest (its cost depends on the number of days of history, not on the number of rows). These numbers are for a local laptop; the free Render instance is much less powerful and was **not** measured.

## Security and privacy design

- Passwords are stored as Argon2 hashes. A short-lived access token is kept **in memory only**; the refresh token is a random secret in a `HttpOnly; SameSite=Strict; Secure` cookie limited to `/api/auth`, stored hashed, rotated on every use, with replay detection that revokes the whole session. Cookie endpoints also require a custom header and a known origin.
- Every upload, transaction and result belongs to a user id; a request for someone else's resource looks identical to a request for a missing one.
- Uploads are limited and validated; errors returned to the client never contain stack traces or file contents; transaction descriptions are not written to logs.
- Only the repository's own model artifact is ever loaded, after a checksum check; user files are never deserialised as models.
- Raw cleaned input is kept in the database only while its job is queued or running. Deleting an analysis removes its rows.
- Private test data lives in `data/private/` (gitignored, excluded from Docker, guarded by a test).

## Deployment

Website on Vercel, API in Docker on Render, PostgreSQL on Neon (all free tiers). The Dockerfile applies migrations when the container starts. See [`docs/deployment.md`](docs/deployment.md) for settings and the order of steps.

## Limitations

- **Synthetic training data.** Scores are for generated bank text. A check on real statements has not been completed, so real-world accuracy is unknown and likely lower.
- Plausible-looking made-up merchants still receive a guess; meaningless text is mostly (not always) caught.
- Email addresses are checked for shape only, there is no email verification and no password reset (version 2).
- Free hosting sleeps when idle; the forecast is slow on large histories (see the timing above); only one server instance is configured, and migrations run at container start.
- Unusual-transaction evaluation used injected amount spikes only; real-world precision is unknown. Repeating charges are matched by exact description text.
- Corrections you make are saved but are not used to retrain the model.

## Future work

Email verification and password reset; measure and report the categorizer on real labelled data; retrain from user corrections with review; cache or speed up the forecast backtest; a pre-deploy migration step and several API instances; optional AI summaries grounded in the computed numbers.
