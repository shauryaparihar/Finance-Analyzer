FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY backend ./backend
COPY data/sample_transactions.csv ./data/sample_transactions.csv
COPY data/sample_descriptions_only.csv ./data/sample_descriptions_only.csv

# Run as a non-root user.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
# Apply any pending migrations (safe to repeat), then start the API. Hosts that set PORT (Render) override 8000.
CMD ["sh", "-c", "python -m backend.migrate && uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --log-config backend/logging_config.json --no-access-log"]
