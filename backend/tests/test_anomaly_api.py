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


# --- the queue follows category corrections ---

def _mislabelled_rent_upload(db, email="user@example.com"):
    """40 ordinary grocery rows, 12 rent payments of about 1500, and one more 1500 rent payment filed under Groceries."""
    rng_amounts = [58.0 + (i % 9) for i in range(40)]
    rows = [{"date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=i % 28), "amount": a, "description": f"market {i}", "category": "Groceries"} for i, a in enumerate(rng_amounts)]
    rows += [{"date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=30 + i), "amount": 1495.0 + i, "description": f"rent {i}", "category": "Rent"} for i in range(12)]
    rows.append({"date": pd.Timestamp("2025-03-05"), "amount": 1500.0, "description": "rent mislabelled", "category": "Groceries"})
    frame = pd.DataFrame(rows)
    from backend.ml.anomaly import run_anomaly_detection

    frame["effective_category"] = frame["category"]
    result = run_anomaly_detection(frame)
    columns = result.pop("row_columns")
    for name in ("anomaly_score", "anomaly_rank", "anomaly_reason"):
        frame[name] = columns[name].astype(object)
    user = repo.get_user_by_email(db, email)
    upload = repo.create_upload(db, user.id, "f.csv", uuid.uuid4().hex * 2, len(frame))
    repo.store_transactions(db, user.id, upload.id, frame.drop(columns=["effective_category"]))
    repo.upsert_analysis_result(db, user.id, upload.id, "anomaly", result)
    return user, upload


def _queue(client, headers, upload):
    return client.get(f"/api/uploads/{upload.id}/anomalies", headers=headers).json()


def test_correcting_a_category_removes_a_mislabelled_row_from_the_unusual_queue(client, db):
    headers = register_and_login(client)
    user, upload = _mislabelled_rent_upload(db)
    before = _queue(client, headers, upload)
    assert before["items"][0]["description"] == "rent mislabelled" and before["items"][0]["category"] == "Groceries"
    assert "Groceries" in before["items"][0]["reason"]

    target = _txn_id(db, user, upload, "rent mislabelled")
    assert client.patch(f"/api/transactions/{target}/category", headers=headers, json={"category": "Rent"}).status_code == 200
    after = _queue(client, headers, upload)
    assert "rent mislabelled" not in [i["description"] for i in after["items"]]
    # the stored per-transaction score and rank were refreshed too, not just the list
    fixed = [t for t in repo.get_transactions(db, user.id, upload.id) if t.description == "rent mislabelled"][0]
    db.refresh(fixed)
    assert fixed.anomaly_rank is None and fixed.anomaly_score < 0.5


def test_the_queue_size_in_the_summary_follows_the_correction(client, db):
    headers = register_and_login(client)
    user, upload = _mislabelled_rent_upload(db)
    target = _txn_id(db, user, upload, "rent mislabelled")
    client.patch(f"/api/transactions/{target}/category", headers=headers, json={"category": "Rent"})
    queue = _queue(client, headers, upload)
    summary = client.get(f"/api/uploads/{upload.id}/summary", headers=headers).json()["data"]
    assert summary["review_queue_size"] == len(queue["items"])


def test_review_decisions_survive_a_correction_and_come_back_with_the_row(client, db):
    headers = register_and_login(client)
    user, upload = _mislabelled_rent_upload(db)
    target = _txn_id(db, user, upload, "rent mislabelled")
    client.patch(f"/api/transactions/{target}/anomaly-review", headers=headers, json={"status": "confirmed"})

    client.patch(f"/api/transactions/{target}/category", headers=headers, json={"category": "Rent"})
    out = _queue(client, headers, upload)
    assert out["decisions_outside_queue"] == 1 and out["confirmed"] == 0  # left the queue, decision kept

    client.patch(f"/api/transactions/{target}/category", headers=headers, json={"category": "Groceries"})
    back = _queue(client, headers, upload)
    assert back["decisions_outside_queue"] == 0
    assert [i["review_status"] for i in back["items"] if i["description"] == "rent mislabelled"] == ["confirmed"]


def test_no_recomputation_when_the_category_does_not_change(client, db, monkeypatch):
    import backend.api.routes as routes

    calls = []
    monkeypatch.setattr(routes, "refresh_anomaly_ranking", lambda *a: calls.append(a) or True)
    headers = register_and_login(client)
    user, upload = _mislabelled_rent_upload(db)
    target = _txn_id(db, user, upload, "market 3")
    client.patch(f"/api/transactions/{target}/category", headers=headers, json={"category": "Groceries"})  # same as before
    assert calls == []
    client.patch(f"/api/transactions/{target}/category", headers=headers, json={"category": "Dining"})
    assert len(calls) == 1


def test_a_denied_correction_leaves_the_queue_alone(client, db):
    owner = register_and_login(client, "user@example.com")
    intruder = register_and_login(client, "intruder@example.com")
    user, upload = _mislabelled_rent_upload(db)
    target = _txn_id(db, user, upload, "rent mislabelled")
    before = _queue(client, owner, upload)
    assert client.patch(f"/api/transactions/{target}/category", headers=intruder, json={"category": "Rent"}).status_code == 404
    assert _queue(client, owner, upload) == before


def test_uploads_without_a_ranked_queue_are_not_given_one_by_a_correction(client, db):
    headers = register_and_login(client)
    user = repo.get_user_by_email(db, "user@example.com")
    upload = repo.create_upload(db, user.id, "f.csv", uuid.uuid4().hex * 2, 3)
    frame = pd.DataFrame({"date": pd.date_range("2025-03-01", periods=3), "amount": [10.0, 20.0, 5000.0], "description": ["a", "b", "c"]})
    repo.store_transactions(db, user.id, upload.id, frame)
    repo.upsert_analysis_result(db, user.id, upload.id, "anomaly", {"status": "skipped", "reason": "too few"})
    target = _txn_id(db, user, upload, "c")
    assert client.patch(f"/api/transactions/{target}/category", headers=headers, json={"category": "Travel"}).status_code == 200
    body = _queue(client, headers, upload)
    assert body["status"] == "skipped" and body["items"] == []


def test_the_pipeline_reports_an_empty_queue_when_nothing_stands_out(tiny_categorizer):
    results = pipeline.run_full_pipeline(_frame(spikes=()), tiny_categorizer)
    anomaly = results["modules"]["anomaly"]
    assert anomaly["status"] == "completed" and anomaly["flagged"] == 0 and "No expense stood out" in anomaly["reason"]
    assert results["modules"]["summary"]["review_queue_size"] == 0
    assert results["processed_df"]["anomaly_rank"].isna().all()


def test_an_empty_queue_is_reported_by_the_api_with_its_reason(client, db):
    headers = register_and_login(client)
    user = repo.get_user_by_email(db, "user@example.com")
    upload = repo.create_upload(db, user.id, "f.csv", uuid.uuid4().hex * 2, 2)
    repo.store_transactions(db, user.id, upload.id, pd.DataFrame({"date": pd.date_range("2025-03-01", periods=2), "amount": [10.0, 11.0]}))
    repo.upsert_analysis_result(db, user.id, upload.id, "anomaly", {"status": "completed", "flagged": 0, "reason": "No expense stood out from your usual spending for its category.", "method": "deviation", "review_capacity": 10, "expenses_scanned": 2})
    body = client.get(f"/api/uploads/{upload.id}/anomalies", headers=headers).json()
    assert body["status"] == "completed" and body["items"] == [] and "No expense stood out" in body["reason"]
