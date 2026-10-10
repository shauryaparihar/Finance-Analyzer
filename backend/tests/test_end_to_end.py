"""End-to-end checks through the HTTP API with the real trained model and the real analysis pipeline.

Other API tests swap in a fake pipeline for speed; these do not, so a break between the pieces shows up here.
"""
from pathlib import Path

import pytest

import backend.main as main
from backend.ml.categorizer import load_categorizer
from backend.ml.pipeline import run_full_pipeline
from backend.services import analysis_job
from backend.tests.conftest import register_and_login

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample_descriptions_only.csv"


@pytest.fixture
def real_client(client, monkeypatch):
    """The shared client, but with the real model and pipeline instead of the fakes."""
    monkeypatch.setattr(main.app.state, "categorizer", load_categorizer(), raising=False)
    monkeypatch.setattr(analysis_job, "run_full_pipeline", run_full_pipeline)
    return client


def _upload_sample(client, headers) -> str:
    response = client.post("/api/uploads", headers=headers, files={"file": (SAMPLE.name, SAMPLE.read_bytes(), "text/csv")})
    assert response.status_code == 202, response.text
    return response.json()["upload_id"]


def test_register_login_upload_process_and_read_every_result(real_client):
    client = real_client
    headers = register_and_login(client)
    upload_id = _upload_sample(client, headers)

    status = client.get(f"/api/uploads/{upload_id}/status", headers=headers).json()
    assert status["status"] in {"completed", "completed_with_warnings"}, status

    summary = client.get(f"/api/uploads/{upload_id}/summary", headers=headers).json()["data"]
    assert summary["total_transactions"] > 100 and summary["category_spending"]
    assert client.get(f"/api/uploads/{upload_id}/forecast", headers=headers).status_code == 200
    anomalies = client.get(f"/api/uploads/{upload_id}/anomalies", headers=headers).json()
    assert anomalies["status"] in {"completed", "skipped"}
    page = client.get(f"/api/uploads/{upload_id}/transactions?limit=500", headers=headers).json()
    assert page["transactions"] and all(t["category"] for t in page["transactions"])
    assert [u["id"] for u in client.get("/api/uploads", headers=headers).json()] == [upload_id]


def test_a_category_correction_changes_the_summary(real_client):
    client = real_client
    headers = register_and_login(client)
    upload_id = _upload_sample(client, headers)

    def spending():
        data = client.get(f"/api/uploads/{upload_id}/summary", headers=headers).json()["data"]
        return {c["category"]: c["amount"] for c in data["category_spending"]}

    before = spending()
    expenses = [t for t in client.get(f"/api/uploads/{upload_id}/transactions?limit=500", headers=headers).json()["transactions"] if t["amount"] > 0]
    target = expenses[0]
    assert client.patch(f"/api/transactions/{target['id']}/category", headers=headers, json={"category": "Integration Test Category"}).status_code == 200
    after = spending()
    assert after != before
    assert after["Integration Test Category"] == pytest.approx(target["amount"])


def test_unusual_transaction_review_is_saved(real_client):
    client = real_client
    headers = register_and_login(client)
    upload_id = _upload_sample(client, headers)
    queue = client.get(f"/api/uploads/{upload_id}/anomalies", headers=headers).json()
    if not queue["items"]:
        pytest.skip("the sample produces no unusual transactions to review")
    item = queue["items"][0]
    response = client.patch(f"/api/transactions/{item['transaction_id']}/anomaly-review", headers=headers, json={"status": "dismissed"})
    assert response.status_code == 200
    assert client.get(f"/api/uploads/{upload_id}/anomalies", headers=headers).json()["reviewed"] == 1


def test_another_user_is_denied_everything_and_delete_removes_the_data(real_client):
    client = real_client
    owner = register_and_login(client, "owner@example.com")
    other = register_and_login(client, "other@example.com")
    upload_id = _upload_sample(client, owner)

    for path in ("", "/status", "/summary", "/forecast", "/anomalies", "/transactions", "/budget-risk"):
        assert client.get(f"/api/uploads/{upload_id}{path}", headers=other).status_code == 404, path
    assert client.delete(f"/api/uploads/{upload_id}", headers=other).status_code == 404
    assert client.get(f"/api/uploads/{upload_id}", headers=owner).status_code == 200

    assert client.delete(f"/api/uploads/{upload_id}", headers=owner).status_code == 204
    assert client.get(f"/api/uploads/{upload_id}", headers=owner).status_code == 404
    assert client.get(f"/api/uploads/{upload_id}/transactions", headers=owner).status_code == 404
