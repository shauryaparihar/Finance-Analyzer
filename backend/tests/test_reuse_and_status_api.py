import uuid

import backend.main as main
from backend.core import repository as repo
from backend.core.config import settings
from backend.ml.pipeline import ModuleOutcome
from backend.services import analysis_job
from backend.tests.conftest import CSV_OK, csv_file, register_and_login


def _upload(client, headers, content=CSV_OK, name="data.csv", **params):
    return client.post("/api/uploads", headers=headers, files=csv_file(content, name), params=params)


class HoldRunner:
    """Accepts jobs but does not run them, to look at the system between 'accepted' and 'done'."""

    workers, is_running = 1, True

    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args, **kwargs):
        self.jobs.append((fn, args, kwargs))

    def run_all(self):
        for fn, args, kwargs in self.jobs:
            fn(*args, **kwargs)
        self.jobs.clear()

    def shutdown(self):
        self.is_running = False


# --- the status endpoint shows each module ---

def test_status_lists_every_module_with_timing_and_model_version(client):
    headers = register_and_login(client)
    upload_id = _upload(client, headers).json()["upload_id"]
    body = client.get(f"/api/uploads/{upload_id}/status", headers=headers).json()
    assert body["status"] == "completed" and body["error_summary"] is None
    assert [m["module"] for m in body["modules"]] == ["categorization", "forecast", "anomaly", "summary"]
    assert {m["status"] for m in body["modules"]} == {"completed"}
    assert all(m["duration_ms"] is not None and m["finished_at"] for m in body["modules"])
    assert body["modules"][0]["model_version"] == "fake"


def test_between_acceptance_and_completion_the_upload_is_queued_with_pending_modules(client, monkeypatch):
    runner = HoldRunner()
    monkeypatch.setattr(main.app.state, "job_runner", runner, raising=False)
    headers = register_and_login(client)
    response = _upload(client, headers)
    assert response.status_code == 202 and response.json()["status"] == "queued"
    upload_id = response.json()["upload_id"]
    queued = client.get(f"/api/uploads/{upload_id}/status", headers=headers).json()
    assert queued["status"] == "queued" and {m["status"] for m in queued["modules"]} == {"pending"}
    runner.run_all()
    assert client.get(f"/api/uploads/{upload_id}/status", headers=headers).json()["status"] == "completed"


def test_while_the_job_runs_the_upload_is_processing_and_the_module_is_running(client, monkeypatch, test_engine):
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=test_engine)
    seen = {}

    def spying_pipeline(df, categorizer, observer=None):
        observer.on_start("categorization")
        with factory() as session:
            upload = session.query(repo.Upload).one()
            seen["upload"] = upload.status
            seen["runs"] = {r.module: r.status for r in session.query(repo.AnalysisRun).filter_by(upload_id=upload.id)}
        observer.on_finish("categorization", ModuleOutcome("completed"), 1)
        return {"status": "completed", "modules": {"categorization": {"model_version": "x"}}, "errors": [], "processed_df": df}

    monkeypatch.setattr(analysis_job, "run_full_pipeline", spying_pipeline)
    headers = register_and_login(client)
    _upload(client, headers)
    assert seen["upload"] == "processing" and seen["runs"]["categorization"] == "running" and seen["runs"]["forecast"] == "pending"


def test_a_partial_result_is_visible_through_the_api(client, monkeypatch):
    def pipeline(df, categorizer, observer=None):
        observer.on_start("forecast")
        observer.on_finish("forecast", ModuleOutcome("failed", error_code="FORECAST_FAILED", error_message="Forecast failed."), 3)
        observer.on_start("summary")
        observer.on_finish("summary", ModuleOutcome("completed"), 1)
        return {"status": "completed", "modules": {"summary": {"total_transactions": 3}}, "errors": [], "processed_df": df}

    monkeypatch.setattr(analysis_job, "run_full_pipeline", pipeline)
    headers = register_and_login(client)
    upload_id = _upload(client, headers).json()["upload_id"]
    status = client.get(f"/api/uploads/{upload_id}/status", headers=headers).json()
    assert status["status"] == "partial" and "forecast" in status["error_summary"]
    assert {m["module"]: m["status"] for m in status["modules"]}["forecast"] == "failed"
    assert client.get(f"/api/uploads/{upload_id}/summary", headers=headers).status_code == 200  # survivors are usable
    assert client.get(f"/api/uploads/{upload_id}/forecast", headers=headers).status_code == 404


# --- duplicate-result reuse ---

def test_the_same_file_from_the_same_user_returns_the_existing_analysis(client, db):
    headers = register_and_login(client)
    first = _upload(client, headers)
    second = _upload(client, headers)
    assert first.status_code == 202 and first.json()["reused"] is False
    assert second.status_code == 200 and second.json()["reused"] is True
    assert second.json()["upload_id"] == first.json()["upload_id"] and second.json()["status"] == "completed"
    assert "already analysed" in second.json()["message"]
    assert len(client.get("/api/uploads", headers=headers).json()) == 1


def test_reuse_is_per_user_and_never_crosses_accounts(client):
    a = register_and_login(client, "a@example.com")
    b = register_and_login(client, "b@example.com")
    first = _upload(client, a).json()["upload_id"]
    second = _upload(client, b)
    assert second.status_code == 202 and second.json()["reused"] is False and second.json()["upload_id"] != first
    assert client.get(f"/api/uploads/{first}/status", headers=b).status_code == 404
    assert [u["id"] for u in client.get("/api/uploads", headers=b).json()] == [second.json()["upload_id"]]


def test_a_different_sign_convention_is_a_different_analysis(client):
    headers = register_and_login(client)
    first = _upload(client, headers).json()
    flipped = _upload(client, headers, amount_convention="expenses_negative")
    assert flipped.status_code == 202 and flipped.json()["upload_id"] != first["upload_id"]
    assert flipped.json()["amount_convention"] == "expenses_negative"


def test_a_new_model_version_invalidates_the_cache(client, monkeypatch):
    headers = register_and_login(client)
    first = _upload(client, headers).json()["upload_id"]
    monkeypatch.setattr(main.app.state.categorizer, "version", "a-newer-model")
    again = _upload(client, headers)
    assert again.status_code == 202 and again.json()["upload_id"] != first


def test_a_failed_upload_is_never_reused(client, monkeypatch):
    def crash(df, categorizer, observer=None):
        raise RuntimeError("boom")

    headers = register_and_login(client)
    with monkeypatch.context() as m:
        m.setattr(analysis_job, "run_full_pipeline", crash)
        failed = _upload(client, headers).json()["upload_id"]
    assert client.get(f"/api/uploads/{failed}/status", headers=headers).json()["status"] == "failed"
    retry = _upload(client, headers)
    assert retry.status_code == 202 and retry.json()["upload_id"] != failed


def test_deleting_the_analysis_lets_the_same_file_be_analysed_afresh(client):
    headers = register_and_login(client)
    first = _upload(client, headers).json()["upload_id"]
    client.delete(f"/api/uploads/{first}", headers=headers)
    again = _upload(client, headers)
    assert again.status_code == 202 and again.json()["upload_id"] != first


def test_reuse_is_not_blocked_by_a_different_running_job(client, db):
    headers = register_and_login(client)
    first = _upload(client, headers).json()["upload_id"]
    user = repo.get_user_by_email(db, "user@example.com")
    repo.create_upload(db, user.id, "other.csv", uuid.uuid4().hex * 2, 1)  # a different upload is still queued
    reused = _upload(client, headers)
    assert reused.status_code == 200 and reused.json()["upload_id"] == first
    different = _upload(client, headers, b"date,amount\n2025-01-01,5\n")
    assert different.status_code == 409 and different.json()["error"]["code"] == "ACTIVE_JOB_EXISTS"


def test_a_user_corrections_are_kept_when_the_same_file_is_uploaded_again(client, db):
    headers = register_and_login(client)
    upload_id = _upload(client, headers).json()["upload_id"]
    user = repo.get_user_by_email(db, "user@example.com")
    target = repo.get_transactions(db, user.id, uuid.UUID(upload_id))[0].id
    client.patch(f"/api/transactions/{target}/category", headers=headers, json={"category": "My Label"})
    reused = _upload(client, headers).json()["upload_id"]
    rows = client.get(f"/api/uploads/{reused}/transactions", headers=headers).json()["transactions"]
    assert "My Label" in [r["category"] for r in rows]


# --- saturation ---

def test_new_work_is_refused_when_the_server_is_saturated(client, db, monkeypatch):
    monkeypatch.setattr(settings, "max_active_jobs", 1)
    busy_user = repo.create_user(db, "busy@example.com", "hash")
    repo.create_upload(db, busy_user.id, "busy.csv", "a" * 64, 1)  # queued
    headers = register_and_login(client, "waiting@example.com")
    response = _upload(client, headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "SERVER_BUSY"


def test_uploads_are_refused_when_the_runner_is_not_running(client, monkeypatch):
    class Stopped:
        is_running = False

    monkeypatch.setattr(main.app.state, "job_runner", Stopped(), raising=False)
    headers = register_and_login(client)
    response = _upload(client, headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "NOT_READY"


def test_readyz_fails_without_a_running_job_runner(test_engine, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    monkeypatch.setattr(main, "engine", test_engine)
    monkeypatch.setattr(main.app.state, "categorizer", SimpleNamespace(version="t"), raising=False)
    monkeypatch.setattr(main.app.state, "job_runner", None, raising=False)
    assert TestClient(main.app).get("/readyz").status_code == 503


def test_the_dataframe_handed_to_the_job_has_canonical_signs(client, monkeypatch):
    seen = {}

    def spy(df, categorizer, observer=None):
        seen["amounts"] = list(df["amount"])
        return {"status": "completed", "modules": {}, "errors": [], "processed_df": df}

    monkeypatch.setattr(analysis_job, "run_full_pipeline", spy)
    headers = register_and_login(client)
    _upload(client, headers, b"date,amount\n2025-01-01,-10\n2025-01-02,-20\n2025-01-03,500\n")
    assert seen["amounts"] == [10.0, 20.0, -500.0]
