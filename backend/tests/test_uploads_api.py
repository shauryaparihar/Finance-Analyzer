import pytest

from backend.core import repository as repo
from backend.core.config import settings
from backend.tests.conftest import CSV_OK, csv_file, register_and_login


def _upload(client, headers, content=CSV_OK, name="data.csv", **params):
    return client.post("/api/uploads", headers=headers, files=csv_file(content, name), params=params)


def test_every_resource_endpoint_requires_login(client):
    for method, path in [
        ("post", "/api/uploads"),
        ("get", "/api/uploads"),
        ("get", "/api/uploads/00000000-0000-0000-0000-000000000000"),
        ("get", "/api/uploads/00000000-0000-0000-0000-000000000000/status"),
        ("get", "/api/uploads/00000000-0000-0000-0000-000000000000/summary"),
        ("get", "/api/uploads/00000000-0000-0000-0000-000000000000/forecast"),
        ("get", "/api/uploads/00000000-0000-0000-0000-000000000000/anomalies"),
        ("get", "/api/uploads/00000000-0000-0000-0000-000000000000/transactions"),
        ("delete", "/api/uploads/00000000-0000-0000-0000-000000000000"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path


def test_valid_upload_is_accepted_analysed_and_readable(client):
    headers = register_and_login(client)
    response = _upload(client, headers)
    assert response.status_code == 202
    body = response.json()
    assert body["rows_received"] == 3 and body["rows_dropped"] == 0
    assert body["amount_convention"] == "expenses_positive"
    upload_id = body["upload_id"]

    assert client.get(f"/api/uploads/{upload_id}/status", headers=headers).json()["status"] == "completed"
    summary = client.get(f"/api/uploads/{upload_id}/summary", headers=headers).json()
    assert summary["result_type"] == "summary" and summary["data"]["total_transactions"] == 3
    page = client.get(f"/api/uploads/{upload_id}/transactions", headers=headers).json()
    assert page["count"] == 3 and page["transactions"][0]["category"] == "Uncategorized"
    assert [u["id"] for u in client.get("/api/uploads", headers=headers).json()] == [upload_id]


def test_user_b_cannot_see_or_change_user_a_upload(client):
    a = register_and_login(client, "a@example.com")
    b = register_and_login(client, "b@example.com")
    upload_id = _upload(client, a).json()["upload_id"]

    for suffix in ("", "/status", "/summary", "/forecast", "/anomalies", "/transactions"):
        response = client.get(f"/api/uploads/{upload_id}{suffix}", headers=b)
        assert response.status_code == 404, suffix
        assert response.json()["error"]["code"] == "NOT_FOUND"
    assert client.delete(f"/api/uploads/{upload_id}", headers=b).status_code == 404
    assert client.get("/api/uploads", headers=b).json() == []
    assert client.get(f"/api/uploads/{upload_id}/status", headers=a).status_code == 200  # still intact


def test_unknown_upload_looks_identical_to_someone_elses(client):
    a = register_and_login(client, "a@example.com")
    b = register_and_login(client, "b@example.com")
    upload_id = _upload(client, a).json()["upload_id"]
    theirs = client.get(f"/api/uploads/{upload_id}/summary", headers=b)
    missing = client.get("/api/uploads/00000000-0000-0000-0000-000000000000/summary", headers=b)
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json()["error"]["message"] == missing.json()["error"]["message"]


def test_delete_is_owner_only_and_cascades(client, db):
    headers = register_and_login(client)
    upload_id = _upload(client, headers).json()["upload_id"]
    assert client.delete(f"/api/uploads/{upload_id}", headers=headers).status_code == 204
    assert client.get(f"/api/uploads/{upload_id}/status", headers=headers).status_code == 404
    from sqlalchemy import func, select

    from backend.core.models import AnalysisResult, Transaction

    assert db.scalar(select(func.count()).select_from(Transaction)) == 0
    assert db.scalar(select(func.count()).select_from(AnalysisResult)) == 0


@pytest.mark.parametrize(
    "content,name,status,code",
    [
        (b"", "empty.csv", 400, "UPLOAD_EMPTY"),
        (b"date,amount\n", "headers_only.csv", 400, "UPLOAD_EMPTY"),
        (b"\x00\x01\x02binary", "bin.csv", 400, "UPLOAD_MALFORMED"),
        (b"date,price\n2025-01-01,3\n", "schema.csv", 400, "UPLOAD_SCHEMA_INVALID"),
        (CSV_OK, "notes.txt", 400, "UPLOAD_NOT_CSV"),
        (b"date,amount\n2025-01-01,abc\nnot-a-date,5\n2025-01-03,x\n", "bad.csv", 400, "UPLOAD_TOO_MANY_INVALID_ROWS"),
        (b"date,amount\n2025-01-01,10\n2025-01-02,20\n2025-01-03,-10\n2025-01-04,-20\n", "mixed.csv", 400, "AMOUNT_CONVENTION_INVALID"),
    ],
)
def test_bad_files_fail_safely(client, content, name, status, code):
    response = _upload(client, register_and_login(client), content, name)
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code and error["request_id"]
    assert "Traceback" not in response.text


def test_too_many_rows_and_oversized_files_are_rejected(client, monkeypatch):
    headers = register_and_login(client)
    monkeypatch.setattr(settings, "max_upload_rows", 2)
    assert _upload(client, headers).json()["error"]["code"] == "UPLOAD_TOO_MANY_ROWS"
    monkeypatch.setattr(settings, "max_upload_rows", 50_000)
    monkeypatch.setattr(settings, "max_upload_bytes", 20)
    response = _upload(client, headers)
    assert response.status_code == 413 and response.json()["error"]["code"] == "UPLOAD_TOO_LARGE"


def test_a_few_invalid_rows_are_dropped_and_reported(client):
    content = b"date,amount\n" + b"2025-01-01,10\n" * 9 + b"garbage,5\n"
    body = _upload(client, register_and_login(client), content).json()
    assert body["rows_received"] == 10 and body["rows_dropped"] == 1


def test_amount_convention_can_be_stated_explicitly(client):
    headers = register_and_login(client)
    content = b"date,amount\n2025-01-01,-10\n2025-01-02,-20\n2025-01-03,500\n"
    assert _upload(client, headers, content).json()["amount_convention"] == "expenses_negative"


def test_filename_is_sanitized(client):
    headers = register_and_login(client)
    upload_id = _upload(client, headers, name="../../etc/pass wd<script>.csv").json()["upload_id"]
    name = client.get(f"/api/uploads/{upload_id}", headers=headers).json()["filename"]
    assert "/" not in name and "<" not in name and name.endswith(".csv")


def test_only_one_active_job_per_user(client, db):
    headers = register_and_login(client)
    user = repo.get_user_by_email(db, "user@example.com")
    repo.create_upload(db, user.id, "running.csv", "a" * 64, 1)  # defaults to "queued" = active
    response = _upload(client, headers)
    assert response.status_code == 409 and response.json()["error"]["code"] == "ACTIVE_JOB_EXISTS"
    other = register_and_login(client, "other@example.com")
    assert _upload(client, other).status_code == 202  # another user is unaffected


def test_database_blocks_a_second_active_upload_even_without_the_app_check(db):
    from sqlalchemy.exc import IntegrityError

    user = repo.create_user(db, "x@example.com", "hash")
    repo.create_upload(db, user.id, "one.csv", "a" * 64, 1)
    with pytest.raises(IntegrityError):
        repo.create_upload(db, user.id, "two.csv", "b" * 64, 1)


def test_stale_jobs_are_failed_on_startup_so_users_are_not_locked_out(db):
    user = repo.create_user(db, "x@example.com", "hash")
    upload = repo.create_upload(db, user.id, "one.csv", "a" * 64, 1)
    assert repo.fail_stale_uploads(db) == 1
    db.refresh(upload)
    assert upload.status == "failed" and upload.error_summary
    assert repo.has_active_upload(db, user.id) is False


def test_pipeline_crash_marks_upload_failed_without_leaking_details(client, monkeypatch):
    import backend.api.routes as routes

    def boom(df):
        raise RuntimeError("secret internal detail postgresql://user:pw@host/db")

    monkeypatch.setattr(routes, "run_full_pipeline", boom)
    headers = register_and_login(client)
    upload_id = _upload(client, headers).json()["upload_id"]
    status = client.get(f"/api/uploads/{upload_id}/status", headers=headers)
    assert status.json()["status"] == "failed"
    assert "secret" not in status.text and "postgresql" not in status.text
