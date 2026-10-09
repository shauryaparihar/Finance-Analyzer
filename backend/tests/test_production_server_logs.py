"""
Runs a REAL server process in production mode (not just the formatter) and reads what it writes to its logs.
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from backend.tests.conftest import TEST_DATABASE_URL
from backend.tests.support.failing_server import SENSITIVE_MESSAGE

ROOT = Path(__file__).resolve().parents[2]
MERCHANT = "SECRETMERCHANT-PROD-77"
PASSWORD = "production-secret-password-1"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _csv() -> bytes:
    rows = "\n".join(f"2025-02-{1 + i % 27:02d},{20 + i},{MERCHANT} supermarket" for i in range(40))
    return f"date,amount,description\n{rows}\n".encode()


@pytest.fixture
def production_server(test_engine):
    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "ENVIRONMENT": "production",
        "JWT_SECRET": "p" * 48,
        "FRONTEND_URL": "https://app.example.com",
        "DATABASE_URL": TEST_DATABASE_URL,
        "TEST_PORT": str(port),
        "LOG_LEVEL": "INFO",
    }
    env.pop("LOG_EXCEPTION_MESSAGES", None)
    process = subprocess.Popen(
        [sys.executable, "-m", "backend.tests.support.failing_server"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            if httpx.get(f"{base}/healthz", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.25)
    else:
        process.kill()
        pytest.fail("the production-mode server did not start:\n" + process.communicate()[0][-2000:])
    yield base, process
    if process.poll() is None:
        process.terminate()


def _read_logs(process) -> str:
    try:
        return process.communicate(timeout=20)[0]
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate()[0]


def test_a_production_mode_server_logs_nothing_sensitive_even_when_a_step_crashes(production_server):
    base, process = production_server
    creds = {"email": "prod-user@example.com", "password": PASSWORD}
    assert httpx.post(f"{base}/api/auth/register", json=creds).status_code == 201
    token = httpx.post(f"{base}/api/auth/login", json=creds).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    upload = httpx.post(f"{base}/api/uploads", headers=headers, files={"file": ("data.csv", _csv(), "text/csv")})
    assert upload.status_code == 202
    upload_id = upload.json()["upload_id"]
    for _ in range(80):
        status = httpx.get(f"{base}/api/uploads/{upload_id}/status", headers=headers).json()
        if status["status"] not in ("queued", "processing"):
            break
        time.sleep(0.25)
    assert status["status"] == "partial"  # the forecast step really did crash, with a sensitive message
    assert "SECRET-EXC-MSG" not in json.dumps(status)  # nor does the client see it
    httpx.put(f"{base}/api/budgets/MY%20PRIVATE%20CATEGORY", headers=headers, json={"monthly_limit": 10})

    process.terminate()
    output = _read_logs(process)

    entries = []
    for line in output.splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            pass  # a plain-text startup banner line (tightened once startup logging is JSON too)
    assert entries, "the server wrote no logs"
    assert any(e["event"] == "app_started" and e.get("environment") == "production" for e in entries)
    crash = [e for e in entries if e.get("exc_type") == "RuntimeError"]
    assert crash and "crash" in crash[0]["stack"]  # still debuggable: the type and the stack frames are logged

    for forbidden in (
        SENSITIVE_MESSAGE, "SECRET-EXC-MSG", "COFFEE SHOP", "hunter2", "postgresql://", MERCHANT, PASSWORD,
        token, "prod-user@example.com", "PRIVATE CATEGORY", "p" * 48,
    ):
        assert forbidden not in output, forbidden
