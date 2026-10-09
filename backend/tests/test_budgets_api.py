import uuid

import pandas as pd
from sqlalchemy import delete

from backend.core import repository as repo
from backend.core.models import AnalysisResult
from backend.tests.conftest import register_and_login


def test_budget_endpoints_require_login(client):
    assert client.get("/api/budgets").status_code == 401
    assert client.put("/api/budgets/Dining", json={"monthly_limit": 10}).status_code == 401
    assert client.delete("/api/budgets/Dining").status_code == 401
    assert client.get(f"/api/uploads/{uuid.uuid4()}/budget-risk").status_code == 401


def test_create_update_list_and_delete_a_budget(client):
    headers = register_and_login(client)
    created = client.put("/api/budgets/Dining", headers=headers, json={"monthly_limit": 600})
    assert created.status_code == 200 and created.json()["monthly_limit"] == 600.0
    client.put("/api/budgets/Groceries", headers=headers, json={"monthly_limit": "1200.50"})
    assert client.put("/api/budgets/Dining", headers=headers, json={"monthly_limit": 650}).json()["monthly_limit"] == 650.0
    assert [(b["category"], b["monthly_limit"]) for b in client.get("/api/budgets", headers=headers).json()] == [
        ("Dining", 650.0),
        ("Groceries", 1200.5),
    ]
    assert client.delete("/api/budgets/Dining", headers=headers).status_code == 204
    assert client.delete("/api/budgets/Dining", headers=headers).status_code == 404
    assert [b["category"] for b in client.get("/api/budgets", headers=headers).json()] == ["Groceries"]


def test_budgets_are_isolated_between_users(client):
    a = register_and_login(client, "a@example.com")
    b = register_and_login(client, "b@example.com")
    client.put("/api/budgets/Dining", headers=a, json={"monthly_limit": 100})
    client.put("/api/budgets/Dining", headers=b, json={"monthly_limit": 999})
    assert client.get("/api/budgets", headers=a).json()[0]["monthly_limit"] == 100.0
    assert client.get("/api/budgets", headers=b).json()[0]["monthly_limit"] == 999.0
    assert client.delete("/api/budgets/Dining", headers=b).status_code == 204
    assert len(client.get("/api/budgets", headers=a).json()) == 1  # user A's budget is untouched


def test_invalid_limits_are_rejected(client):
    headers = register_and_login(client)
    for bad in (0, -5, 100_000_001, "abc", 1.234, None):
        response = client.put("/api/budgets/Dining", headers=headers, json={"monthly_limit": bad})
        assert response.status_code == 422, bad
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get("/api/budgets", headers=headers).json() == []


def test_category_names_are_tidied_and_url_encoded_names_work(client):
    headers = register_and_login(client)
    client.put("/api/budgets/Personal%20%20Care", headers=headers, json={"monthly_limit": 50})
    assert client.get("/api/budgets", headers=headers).json()[0]["category"] == "Personal Care"
    assert client.delete("/api/budgets/Personal%20Care", headers=headers).status_code == 204
    assert client.put("/api/budgets/%20%20", headers=headers, json={"monthly_limit": 5}).status_code == 422


def _seed(db, email="user@example.com"):
    """An upload (March 2025) with a stored completed forecast of 10 per day."""
    user = repo.get_user_by_email(db, email)
    upload = repo.create_upload(db, user.id, "f.csv", uuid.uuid4().hex * 2, 3)
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-03-02", "2025-03-05", "2025-03-10"]),
            "amount": [30.0, 20.0, 100.0],
            "description": ["a", "b", "c"],
            "category": ["Dining", "Dining", None],
            "predicted_category": [None, None, "Groceries"],
            "prediction_confidence": [None, None, 0.9],
        }
    )
    repo.store_transactions(db, user.id, upload.id, frame)
    start = pd.Timestamp("2025-03-11")
    daily = [{"date": (start + pd.Timedelta(days=i)).strftime("%Y-%m-%d"), "predicted_spending": 10.0} for i in range(31)]
    repo.upsert_analysis_result(
        db, user.id, upload.id, "forecast", {"status": "completed", "method": "seasonal_naive", "forecast": {"daily": daily}}
    )
    return user, upload


def test_budget_risk_uses_stored_transactions_budgets_and_forecast(client, db):
    headers = register_and_login(client)
    _, upload = _seed(db)
    client.put("/api/budgets/Dining", headers=headers, json={"monthly_limit": 60})
    client.put("/api/budgets/Groceries", headers=headers, json={"monthly_limit": 500})
    risk = client.get(f"/api/uploads/{upload.id}/budget-risk", headers=headers).json()
    rows = {r["category"]: r for r in risk["categories"]}
    assert rows["Dining"]["spent_so_far"] == 50.0 and rows["Groceries"]["spent_so_far"] == 100.0
    assert risk["month"] == "2025-03" and risk["remaining_days"] == 21 and risk["projection_method"].startswith("forecast")
    assert rows["Dining"]["projected_month_end"] > rows["Dining"]["spent_so_far"]
    assert "not financial advice" in risk["disclaimer"].lower()


def test_a_category_correction_changes_the_budget_risk(client, db):
    headers = register_and_login(client)
    user, upload = _seed(db)
    client.put("/api/budgets/Dining", headers=headers, json={"monthly_limit": 1000})
    before = client.get(f"/api/uploads/{upload.id}/budget-risk", headers=headers).json()["categories"][0]
    groceries_txn = [t for t in repo.get_transactions(db, user.id, upload.id) if t.predicted_category == "Groceries"][0]
    client.patch(f"/api/transactions/{groceries_txn.id}/category", headers=headers, json={"category": "Dining"})
    after = client.get(f"/api/uploads/{upload.id}/budget-risk", headers=headers).json()["categories"][0]
    assert before["spent_so_far"] == 50.0 and after["spent_so_far"] == 150.0


def test_budget_risk_is_owner_only(client, db):
    owner = register_and_login(client, "user@example.com")
    intruder = register_and_login(client, "intruder@example.com")
    _, upload = _seed(db)
    client.put("/api/budgets/Dining", headers=owner, json={"monthly_limit": 60})
    response = client.get(f"/api/uploads/{upload.id}/budget-risk", headers=intruder)
    assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"


def test_budget_risk_without_a_forecast_still_works(client, db):
    headers = register_and_login(client)
    user, upload = _seed(db)
    db.execute(delete(AnalysisResult).where(AnalysisResult.upload_id == upload.id))
    db.commit()
    client.put("/api/budgets/Dining", headers=headers, json={"monthly_limit": 60})
    risk = client.get(f"/api/uploads/{upload.id}/budget-risk", headers=headers).json()
    assert risk["projection_method"] == "none" and risk["categories"][0]["projected_month_end"] == 50.0
