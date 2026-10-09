"""
Test harness only: start the real application, but make the forecast step crash with a message that contains
sensitive-looking text. Used to check what a production-mode server writes to its logs.
"""
import os

import uvicorn

import backend.ml.pipeline as pipeline

SENSITIVE_MESSAGE = "SECRET-EXC-MSG COFFEE SHOP 4.50 postgresql://admin:hunter2@db.internal:5432/app"


def crash(df):
    raise RuntimeError(SENSITIVE_MESSAGE)


if __name__ == "__main__":
    # Only when run as a server process: importing this module (for SENSITIVE_MESSAGE) must change nothing.
    pipeline.run_forecast = crash
    uvicorn.run(
        "backend.main:app", host="127.0.0.1", port=int(os.environ["TEST_PORT"]),
        log_config="backend/logging_config.json", access_log=False,
    )
