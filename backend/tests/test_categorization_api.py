import uuid
from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import backend.main as main
from backend.core import repository as repo
from backend.tests.conftest import csv_file, register_and_login


def _seed_upload(db, email="owner@example.com"):
    """An upload with one confident prediction, one user-labelled row and one row needing review."""
    user = repo.get_user_by_email(db, email) or repo.create_user(db, email, "hash")
    upload = repo.create_upload(db, user.id, "f.csv", uuid.uuid4().hex * 2, 3)
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
            "amount": [10.0, 20.0, 40.0],
            "description": ["shop", "own", "mystery"],
            "category": [None, "Mine", None],
            "predicted_category": ["Groceries", "Dining", "Uncategorized"],
            "prediction_confidence": [0.9, 0.8, 0.2],
        }
    )
    repo.store_transactions(db, user.id, upload.id, frame)
    return user, upload


def _ids(db, user, upload):
    return [t.id for t in repo.get_transactions(db, user.id, upload.id)]


def _login(client, user_email, password="correct-horse-battery"):
    token = client.post("/api/auth/login", json={"email": user_email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_effective_category_order_and_review_flag(client, db):
    headers = register_and_login(client, "owner@example.com")
    user, upload = _seed_upload(db)
    rows = client.get(f"/api/uploads/{upload.id}/transactions", headers=headers).json()["transactions"]
    assert [r["category"] for r in rows] == ["Groceries", "Mine", "Uncategorized"]
    assert [r["review_required"] for r in rows] == [False, False, True]
    assert rows[0]["prediction_confidence"] == 0.9
    # where each category came from: the model for the first row, the uploaded file for the second
    assert [r["source_category"] for r in rows] == [None, "Mine", None]


def test_review_required_filter(client, db):
    headers = register_and_login(client, "owner@example.com")
    _, upload = _seed_upload(db)
    needs = client.get(f"/api/uploads/{upload.id}/transactions?review_required=true", headers=headers).json()
    done = client.get(f"/api/uploads/{upload.id}/transactions?review_required=false", headers=headers).json()
    assert [t["description"] for t in needs["transactions"]] == ["mystery"]
    assert [t["description"] for t in done["transactions"]] == ["shop", "own"]


def test_correction_changes_the_effective_category_and_the_summary(client, db):
    headers = register_and_login(client, "owner@example.com")
    user, upload = _seed_upload(db)
    mystery_id = _ids(db, user, upload)[2]

    response = client.patch(f"/api/transactions/{mystery_id}/category", headers=headers, json={"category": "  Pet   Care "})
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "Pet Care" and body["confirmed_category"] == "Pet Care" and not body["review_required"]

    summary = client.get(f"/api/uploads/{upload.id}/summary", headers=headers).json()["data"]
    spending = {c["category"]: c["amount"] for c in summary["category_spending"]}
    assert spending["Pet Care"] == 40.0 and "Uncategorized" not in spending
    assert client.get(f"/api/uploads/{upload.id}/transactions?review_required=true", headers=headers).json()["count"] == 0


def test_a_correction_beats_the_users_own_csv_label_and_the_prediction(client, db):
    headers = register_and_login(client, "owner@example.com")
    user, upload = _seed_upload(db)
    own_id = _ids(db, user, upload)[1]
    assert client.patch(f"/api/transactions/{own_id}/category", headers=headers, json={"category": "Fixed"}).json()["category"] == "Fixed"


def test_correction_is_owner_only(client, db):
    owner_headers = register_and_login(client, "owner@example.com")
    intruder_headers = register_and_login(client, "intruder@example.com")
    user, upload = _seed_upload(db)
    target = _ids(db, user, upload)[2]

    denied = client.patch(f"/api/transactions/{target}/category", headers=intruder_headers, json={"category": "Hacked"})
    assert denied.status_code == 404 and denied.json()["error"]["code"] == "NOT_FOUND"
    missing = client.patch("/api/transactions/999999999/category", headers=intruder_headers, json={"category": "X"})
    assert missing.json()["error"]["message"] == "Transaction not found." == denied.json()["error"]["message"]
    rows = client.get(f"/api/uploads/{upload.id}/transactions", headers=owner_headers).json()["transactions"]
    assert rows[2]["category"] == "Uncategorized"  # untouched


def test_correction_requires_login_and_a_valid_body(client, db):
    headers = register_and_login(client, "owner@example.com")
    user, upload = _seed_upload(db)
    target = _ids(db, user, upload)[0]
    assert client.patch(f"/api/transactions/{target}/category", json={"category": "X"}).status_code == 401
    assert client.patch(f"/api/transactions/{target}/category", headers=headers, json={"category": ""}).status_code == 422
    assert client.patch(f"/api/transactions/{target}/category", headers=headers, json={"category": "x" * 101}).status_code == 422
    assert client.patch(f"/api/transactions/{target}/category", headers=headers, json={"category": "   "}).status_code == 422


def test_uploads_are_refused_while_the_model_is_unavailable(client, monkeypatch):
    headers = register_and_login(client)
    monkeypatch.setattr(main.app.state, "categorizer", None, raising=False)
    response = client.post("/api/uploads", headers=headers, files=csv_file())
    assert response.status_code == 503 and response.json()["error"]["code"] == "MODEL_UNAVAILABLE"


def test_readyz_reports_the_model_and_fails_without_it(test_engine, monkeypatch):
    monkeypatch.setattr(main, "engine", test_engine)
    monkeypatch.setattr(main.app.state, "categorizer", SimpleNamespace(version="v-test"), raising=False)
    monkeypatch.setattr(main.app.state, "job_runner", SimpleNamespace(is_running=True), raising=False)
    ready = TestClient(main.app).get("/readyz")
    assert ready.status_code == 200 and ready.json()["model_version"] == "v-test"

    monkeypatch.setattr(main.app.state, "categorizer", None, raising=False)
    not_ready = TestClient(main.app).get("/readyz")
    assert not_ready.status_code == 503 and not_ready.json()["error"]["code"] == "NOT_READY"


def test_startup_with_a_corrupted_model_leaves_the_app_running_but_not_ready(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setattr(main, "load_categorizer", lambda: (_ for _ in ()).throw(main.ModelLoadError("corrupt")))
    monkeypatch.setattr(main, "SessionLocal", sessionmaker())  # never reached: stale sweep failure is tolerated

    async def run_startup():
        async with main.lifespan(main.app):
            return main.app.state.categorizer

    assert asyncio.run(run_startup()) is None


def test_the_category_list_comes_from_the_model_and_needs_login(client):
    assert client.get("/api/categories").status_code == 401
    body = client.get("/api/categories", headers=register_and_login(client)).json()
    assert body["categories"] == ["Groceries", "Rent"] and body["model_version"] == "test-model"


def test_the_real_categorizer_exposes_its_seventeen_categories():
    from backend.ml.categorizer import load_categorizer

    categories = load_categorizer().categories
    assert len(categories) == 17 and "Groceries" in categories and "Uncategorized" not in categories
    assert categories == sorted(categories)


def test_the_category_list_is_unavailable_while_the_model_is_(client, monkeypatch):
    monkeypatch.setattr(main.app.state, "categorizer", None, raising=False)
    response = client.get("/api/categories", headers=register_and_login(client))
    assert response.status_code == 503 and response.json()["error"]["code"] == "MODEL_UNAVAILABLE"


def test_the_file_label_is_reported_even_when_the_model_predicted_the_same_category(client, db):
    headers = register_and_login(client, "owner@example.com")
    user = repo.get_user_by_email(db, "owner@example.com")
    upload = repo.create_upload(db, user.id, "f.csv", uuid.uuid4().hex * 2, 1)
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01"]), "amount": [10.0], "description": ["apple store"],
            "category": ["Shopping"], "predicted_category": ["Shopping"], "prediction_confidence": [0.98],
        }
    )
    repo.store_transactions(db, user.id, upload.id, frame)
    row = client.get(f"/api/uploads/{upload.id}/transactions", headers=headers).json()["transactions"][0]
    assert row["category"] == "Shopping" and row["source_category"] == "Shopping" and row["predicted_category"] == "Shopping"
