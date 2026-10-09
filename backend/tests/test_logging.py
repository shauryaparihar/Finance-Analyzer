import json
import logging

import pytest

import backend.main as main
from backend.core import config
from backend.core.logging import JsonFormatter, configure_logging, log_event, redact_text, request_id_var
from backend.ml import pipeline as pipeline_module
from backend.services import analysis_job
from backend.tests.conftest import PASSWORD, csv_file, register_and_login

SECRET_TEXT = "SECRETMERCHANT 99887"


def _lines(caplog):
    """The application's own log lines (not the HTTP test client's)."""
    formatter = JsonFormatter()
    return [json.loads(formatter.format(r)) for r in caplog.records if r.name.startswith("finsight")]


def _record(**fields):
    logger = logging.getLogger("finsight.test")
    return logger.makeRecord("finsight.test", logging.INFO, __file__, 1, "an_event", (), None, extra={"fields": fields})


def test_every_line_is_json_with_the_standard_fields():
    token = request_id_var.set("req-abc12345")
    try:
        entry = json.loads(JsonFormatter().format(_record(upload_id="u1", module="forecast", duration_ms=12, status="completed", error_code=None)))
    finally:
        request_id_var.reset(token)
    assert entry["event"] == "an_event" and entry["level"] == "INFO" and entry["request_id"] == "req-abc12345"
    assert entry["upload_id"] == "u1" and entry["module"] == "forecast" and entry["duration_ms"] == 12 and entry["status"] == "completed"
    assert entry["timestamp"].endswith("+00:00") and entry["logger"] == "finsight.test"


@pytest.mark.parametrize("name", ["password", "token", "access_token", "authorization", "database_url", "description", "descriptions", "email", "rows"])
def test_sensitive_field_names_are_never_written(name):
    entry = json.loads(JsonFormatter().format(_record(**{name: "VALUE-THAT-MUST-NOT-APPEAR", "ok": 1})))
    assert name not in entry and "VALUE-THAT-MUST-NOT-APPEAR" not in json.dumps(entry) and entry["ok"] == 1


def test_tokens_and_credentials_are_redacted_wherever_they_appear():
    jwt_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlMTIz"
    text = f"failed for Bearer {jwt_like} using postgresql+psycopg://admin:hunter2@db.example.com:5432/app and {jwt_like}"
    cleaned = redact_text(text)
    assert "hunter2" not in cleaned and "eyJhbGci" not in cleaned and "admin" not in cleaned
    entry = json.loads(JsonFormatter().format(_record(detail=text)))
    assert "hunter2" not in json.dumps(entry) and "eyJhbGci" not in json.dumps(entry)


def test_long_values_are_truncated():
    assert len(json.loads(JsonFormatter().format(_record(note="x" * 5000)))["note"]) <= 300


def _exception_record(message):
    try:
        raise ValueError(message)
    except ValueError:
        import sys

        return logging.getLogger("finsight.test").makeRecord("finsight.test", logging.ERROR, __file__, 1, "job_crashed", (), sys.exc_info())


@pytest.mark.parametrize("environment", ["development", "production", "test"])
def test_exception_messages_are_never_logged_by_default_in_any_environment(monkeypatch, environment):
    monkeypatch.setattr(config.settings, "environment", environment)
    entry = json.loads(JsonFormatter().format(_exception_record("bad value COFFEE SHOP 4.50")))
    assert entry["exc_type"] == "ValueError" and "error" not in entry and "COFFEE SHOP" not in json.dumps(entry)
    assert "test_logging.py" in entry["stack"]  # the stack frames stay: they are what you debug with


def test_the_exception_message_appears_only_when_explicitly_enabled_for_local_debugging(monkeypatch):
    monkeypatch.setattr(config.settings, "log_exception_messages", True)
    entry = json.loads(JsonFormatter().format(_exception_record("bad value COFFEE SHOP 4.50")))
    assert "COFFEE SHOP" in entry["error"]
    assert config.Settings().log_exception_messages is False  # the default


def test_configure_logging_is_idempotent():
    configure_logging()
    configure_logging()
    tagged = [h for h in logging.getLogger().handlers if getattr(h, "_finsight_json_handler", False)]
    assert len(tagged) == 1


def test_log_event_carries_fields_through_the_standard_logger(caplog):
    caplog.set_level(logging.INFO)
    log_event(logging.getLogger("finsight.test"), logging.WARNING, "thing_happened", module="anomaly", error_code="X")
    entry = _lines(caplog)[-1]
    assert entry["event"] == "thing_happened" and entry["level"] == "WARNING" and entry["module"] == "anomaly"


# --- end to end: an upload with the real pipeline must not leak anything sensitive ---

def _real_upload(client, monkeypatch, tiny_categorizer, headers):
    monkeypatch.setattr(analysis_job, "run_full_pipeline", pipeline_module.run_full_pipeline)
    monkeypatch.setattr(main.app.state, "categorizer", tiny_categorizer, raising=False)
    rows = "\n".join(f"2025-02-{1 + i % 27:02d},{40 + i},{SECRET_TEXT} supermarket bababa" for i in range(40))
    return client.post("/api/uploads", headers=headers, files=csv_file(f"date,amount,description\n{rows}\n".encode()))


def test_logs_from_a_real_analysis_contain_no_transactions_passwords_tokens_or_database_urls(client, monkeypatch, tiny_categorizer, caplog):
    caplog.set_level(logging.INFO)
    headers = register_and_login(client)
    token = headers["Authorization"].split()[1]
    response = _real_upload(client, monkeypatch, tiny_categorizer, headers)
    assert response.status_code == 202
    client.get("/api/auth/me", headers=headers)
    client.post("/api/auth/login", json={"email": "user@example.com", "password": "wrong-password-xyz"})

    text = json.dumps(_lines(caplog))
    assert text and caplog.records
    for forbidden in (SECRET_TEXT, "SECRETMERCHANT", PASSWORD, "wrong-password-xyz", token, "postgresql", "user@example.com"):
        assert forbidden not in text, forbidden


def test_the_analysis_logs_name_the_events_modules_and_timings(client, monkeypatch, tiny_categorizer, caplog):
    caplog.set_level(logging.INFO)
    headers = register_and_login(client)
    response = _real_upload(client, monkeypatch, tiny_categorizer, headers)
    upload_id = response.json()["upload_id"]
    entries = [e for e in _lines(caplog) if e.get("upload_id") == upload_id]
    events = [e["event"] for e in entries]
    assert {"upload_accepted", "job_started", "module_finished", "job_finished"} <= set(events)
    finished = [e for e in entries if e["event"] == "module_finished"]
    assert {e["module"] for e in finished} == {"categorization", "forecast", "anomaly", "summary"}
    assert all(isinstance(e["duration_ms"], int) and e["status"] in ("completed", "skipped", "failed") for e in finished)
    done = [e for e in entries if e["event"] == "job_finished"][0]
    assert done["status"] == "completed" and done["needs_review"] == 0 and done["auto_categorized"] == 40
    assert next(e for e in finished if e["module"] == "categorization")["model_version"] == "tiny-test"


def test_background_work_logs_the_request_id_of_the_request_that_started_it(client, monkeypatch, tiny_categorizer, caplog):
    caplog.set_level(logging.INFO)
    headers = register_and_login(client)
    response = _real_upload(client, monkeypatch, tiny_categorizer, headers)
    request_id = response.headers["x-request-id"]
    job_lines = [e for e in _lines(caplog) if e["event"] in ("job_started", "module_finished", "job_finished")]
    assert job_lines and {e["request_id"] for e in job_lines} == {request_id}
    assert any(e["event"] == "request" and e["request_id"] == request_id and e["path"] == "/api/uploads" for e in _lines(caplog))


def test_the_request_log_has_method_path_status_and_user_but_no_query_or_body(client, caplog):
    caplog.set_level(logging.INFO)
    headers = register_and_login(client)
    client.get("/api/uploads?limit=5&offset=0", headers=headers)
    entry = [e for e in _lines(caplog) if e["event"] == "request" and e["path"] == "/api/uploads"][-1]
    assert entry["method"] == "GET" and entry["status"] == 200 and isinstance(entry["duration_ms"], int) and entry["user_id"]
    assert "limit" not in json.dumps(entry)


def test_an_unexpected_error_is_logged_with_the_request_id_and_hidden_from_the_client(caplog):
    from fastapi.testclient import TestClient

    @main.app.get("/_log_boom")
    def boom():
        raise RuntimeError("password=hunter2 postgresql://u:pw@h/db")

    caplog.set_level(logging.INFO)
    try:
        response = TestClient(main.app, raise_server_exceptions=False).get("/_log_boom")
    finally:
        main.app.router.routes = [r for r in main.app.router.routes if getattr(r, "path", "") != "/_log_boom"]
    assert response.status_code == 500 and "hunter2" not in response.text
    entry = [e for e in _lines(caplog) if e["event"] == "unhandled_error"][0]
    assert entry["request_id"] == response.headers["x-request-id"] and entry["exc_type"] == "RuntimeError"
    assert "pw@h" not in json.dumps(entry)


def test_the_request_log_records_the_route_template_not_user_chosen_path_values(client, caplog):
    caplog.set_level(logging.INFO)
    headers = register_and_login(client)
    client.put("/api/budgets/MY%20PRIVATE%20CATEGORY", headers=headers, json={"monthly_limit": 10})
    client.delete("/api/budgets/MY%20PRIVATE%20CATEGORY", headers=headers)
    text = json.dumps(_lines(caplog))
    assert "PRIVATE" not in text and "CATEGORY" not in text
    paths = {e["path"] for e in _lines(caplog) if e["event"] == "request"}
    assert "/api/budgets/{category}" in paths
