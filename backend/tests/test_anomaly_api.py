import uuid

import pandas as pd

import backend.ml.pipeline as pipeline
from backend.core import repository as repo
from backend.tests.conftest import register_and_login


def _seed(db, email="user@example.com", flagged=3):
    """An upload whose first `flagged` transactions are in the review queue (rank 1..flagged)."""
    user = repo.get_user_by_email(db, email)
    upload = repo.create_upload(db, user.id, "f.csv", uuid.uuid4().hex * 2, 5)
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2025-03-01", periods=5),
            "amount": [900.0, 600.0, 300.0, 20.0, 25.0],
            "description": ["big", "mid", "small spike", "a", "b"],
            "category": ["Groceries"] * 5,
            "anomaly_score": [1.0, 0.9, 0.8, 0.1, 0.1],
            "anomaly_rank": [1, 2, 3, None, None][:5],
            "anomaly_reason": ["Amount 900.00 is about 15.0x the typical Groceries amount (60.00).", "r2", "r3", None, None],
        }
    )
    if flagged < 3:
        frame.loc[flagged:2, ["anomaly_rank", "anomaly_reason"]] = None
    repo.store_transactions(db, user.id, upload.id, frame)
    repo.upsert_analysis_result(
        db,
        user.id,
        upload.id,
        "anomaly",
        {"status": "completed", "method": "deviation", "review_capacity": 10, "expenses_scanned": 5, "disclaimer": "Unusual does not mean fraudulent."},
    )
    return user, upload


def _txn_id(db, user, upload, description):
    return [t.id for t in repo.get_transactions(db, user.id, upload.id) if t.description == description][0]


def test_review_queue_is_ordered_by_rank_and_shows_reasons(client, db):
    headers = register_and_login(client)
    _, upload = _seed(db)
    body = client.get(f"/api/uploads/{upload.id}/anomalies", headers=headers).json()
    assert body["status"] == "completed" and body["method"] == "deviation" and body["review_capacity"] == 10
    assert [i["rank"] for i in body["items"]] == [1, 2, 3]
    assert [i["description"] for i in body["items"]] == ["big", "mid", "small spike"]
    assert "15.0x the typical Groceries" in body["items"][0]["reason"]
    assert body["reviewed"] == 0 and "fraudulent" in body["disclaimer"]


def test_only_flagged_transactions_appear_in_the_queue(client, db):
    headers = register_and_login(client)
    _, upload = _seed(db, flagged=1)
    items = client.get(f"/api/uploads/{upload.id}/anomalies", headers=headers).json()["items"]
    assert [i["description"] for i in items] == ["big"]


def test_confirm_and_dismiss_are_saved_and_counted(client, db):
    headers = register_and_login(client)
    user, upload = _seed(db)
    first, second = _txn_id(db, user, upload, "big"), _txn_id(db, user, upload, "mid")
    assert client.patch(f"/api/transactions/{first}/anomaly-review", headers=headers, json={"status": "confirmed"}).json()["anomaly_review_status"] == "confirmed"
    client.patch(f"/api/transactions/{second}/anomaly-review", headers=headers, json={"status": "dismissed"})
    body = client.get(f"/api/uploads/{upload.id}/anomalies", headers=headers).json()
    assert (body["reviewed"], body["confirmed"], body["dismissed"]) == (2, 1, 1)
    assert [i["review_status"] for i in body["items"]] == ["confirmed", "dismissed", "unreviewed"]
    client.patch(f"/api/transactions/{first}/anomaly-review", headers=headers, json={"status": "unreviewed"})  # can be undone
    assert client.get(f"/api/uploads/{upload.id}/anomalies", headers=headers).json()["confirmed"] == 0


def test_review_is_owner_only_for_both_list_and_update(client, db):
    owner = register_and_login(client, "user@example.com")
    intruder = register_and_login(client, "intruder@example.com")
    user, upload = _seed(db)
    target = _txn_id(db, user, upload, "big")
    assert client.get(f"/api/uploads/{upload.id}/anomalies", headers=intruder).status_code == 404
    denied = client.patch(f"/api/transactions/{target}/anomaly-review", headers=intruder, json={"status": "dismissed"})
    assert denied.status_code == 404 and denied.json()["error"]["code"] == "NOT_FOUND"
    assert client.get(f"/api/uploads/{upload.id}/anomalies", headers=owner).json()["reviewed"] == 0  # unchanged


def test_a_transaction_outside_the_queue_cannot_be_reviewed(client, db):
    headers = register_and_login(client)
    user, upload = _seed(db)
    outside = _txn_id(db, user, upload, "a")
    response = client.patch(f"/api/transactions/{outside}/anomaly-review", headers=headers, json={"status": "confirmed"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "NOT_IN_REVIEW_QUEUE"


def test_invalid_review_status_and_missing_login_are_rejected(client, db):
    headers = register_and_login(client)
    user, upload = _seed(db)
    target = _txn_id(db, user, upload, "big")
    assert client.patch(f"/api/transactions/{target}/anomaly-review", headers=headers, json={"status": "fraud"}).status_code == 422
    assert client.patch(f"/api/transactions/{target}/anomaly-review", json={"status": "confirmed"}).status_code == 401
    assert client.get(f"/api/uploads/{upload.id}/anomalies").status_code == 401


def test_an_upload_without_an_anomaly_result_reports_not_available(client, db):
    headers = register_and_login(client)
    user = repo.get_user_by_email(db, "user@example.com")
    upload = repo.create_upload(db, user.id, "f.csv", "a" * 64, 1)
    body = client.get(f"/api/uploads/{upload.id}/anomalies", headers=headers).json()
    assert body["status"] == "not_available" and body["items"] == []


def _frame(n=40, spikes=(("2025-02-20", 700.0),)):
    rows = [{"date": pd.Timestamp("2025-02-01") + pd.Timedelta(days=i % 25), "amount": 40.0 + (i % 7), "description": "supermarket bababa"} for i in range(n)]
    rows += [{"date": pd.Timestamp(d), "amount": a, "description": "supermarket bababa"} for d, a in spikes]
    return pd.DataFrame(rows)


def test_the_pipeline_flags_a_spike_and_keeps_the_queue_within_capacity(tiny_categorizer):
    results = pipeline.run_full_pipeline(_frame(), tiny_categorizer)
    processed = results["processed_df"]
    flagged = processed[processed["anomaly_rank"].notna()]
    assert 1 <= len(flagged) <= 10 and processed.loc[processed["amount"].idxmax(), "anomaly_rank"] == 1
    assert results["modules"]["anomaly"]["status"] == "completed"
    assert results["modules"]["summary"]["review_queue_size"] == len(flagged)


def test_one_module_failing_does_not_erase_the_others(tiny_categorizer, monkeypatch):
    def boom(df):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(pipeline, "run_anomaly_detection", boom)
    results = pipeline.run_full_pipeline(_frame(), tiny_categorizer)
    assert "anomaly" not in results["modules"]
    assert {"categorization", "forecast", "summary", "preprocessing"} <= set(results["modules"])
    assert any("Unusual-transaction ranking failed" in e for e in results["errors"])
    assert "secret detail" not in " ".join(results["errors"])
    assert results["processed_df"]["anomaly_rank"].isna().all()
    assert results["status"] == "completed"


def test_the_segmentation_feature_is_gone(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if "segment" in p.lower()]
    import importlib.util

    assert importlib.util.find_spec("backend.ml.segmentation") is None
