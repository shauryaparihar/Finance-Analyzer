import pytest
from sqlalchemy import select, update

from backend.api.auth import CSRF_HEADER
from backend.core import repository as repo
from backend.core.config import settings
from backend.core.models import User
from backend.tests.conftest import csv_file, register_and_login

CSRF = {CSRF_HEADER: "1"}


def _make_admin(db, email):
    db.execute(update(User).where(User.email == email).values(role="admin"))
    db.commit()


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setattr(settings, "demo_enabled", True)


def _demo(client):
    response = client.post("/api/auth/demo", headers=CSRF)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# --- roles ---

def test_a_normal_account_has_the_user_role(client):
    headers = register_and_login(client)
    assert client.get("/api/auth/me", headers=headers).json()["role"] == "user"


# --- demo (read-only guest) ---

def test_the_demo_login_does_not_exist_unless_the_deployment_enables_it(client):
    assert client.post("/api/auth/demo", headers=CSRF).status_code == 404


def test_the_demo_login_needs_the_same_safety_header_as_the_other_cookie_endpoints(client, demo_on):
    assert client.post("/api/auth/demo").status_code == 403


def test_a_guest_gets_a_read_only_session_with_the_sample_analysis(client, demo_on, db):
    headers = _demo(client)
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["role"] == "demo"
    uploads = client.get("/api/uploads", headers=headers).json()
    assert len(uploads) == 1 and uploads[0]["filename"] == "sample_descriptions_only.csv"
    assert client.get(f"/api/uploads/{uploads[0]['id']}/summary", headers=headers).status_code == 200
    _demo(client)  # a second guest does not queue a second copy
    assert len(client.get("/api/uploads", headers=headers).json()) == 1


def test_a_guest_cannot_change_anything(client, demo_on):
    headers = _demo(client)
    upload_id = client.get("/api/uploads", headers=headers).json()[0]["id"]
    txn = client.get(f"/api/uploads/{upload_id}/transactions", headers=headers).json()["transactions"][0]["id"]
    attempts = [
        client.post("/api/uploads", headers=headers, files=csv_file()),
        client.delete(f"/api/uploads/{upload_id}", headers=headers),
        client.patch(f"/api/transactions/{txn}/category", headers=headers, json={"category": "Groceries"}),
        client.patch(f"/api/transactions/{txn}/anomaly-review", headers=headers, json={"status": "confirmed"}),
        client.put("/api/budgets/Groceries", headers=headers, json={"monthly_limit": 100}),
        client.delete("/api/budgets/Groceries", headers=headers),
    ]
    for response in attempts:
        assert response.status_code == 403 and response.json()["error"]["code"] == "READ_ONLY_ACCOUNT"
    assert client.get(f"/api/uploads/{upload_id}", headers=headers).status_code == 200  # nothing was deleted


def test_nobody_can_log_in_to_or_register_the_demo_account_with_a_password(client, demo_on):
    _demo(client)
    assert client.post("/api/auth/login", json={"email": repo.DEMO_EMAIL, "password": "anything-at-all"}).status_code == 401
    assert client.post("/api/auth/register", json={"email": repo.DEMO_EMAIL, "password": "long-enough-1"}).status_code == 409


def test_the_demo_email_cannot_be_registered_before_the_first_guest_either(client):
    assert client.post("/api/auth/register", json={"email": "Demo@Example.com", "password": "long-enough-1"}).status_code == 409


# --- admin ---

def test_admin_pages_look_missing_to_everyone_else(client):
    headers = register_and_login(client)
    for path in ("/api/admin/overview", "/api/admin/users"):
        assert client.get(path, headers=headers).status_code == 404
    assert client.get("/api/admin/overview").status_code == 401


def test_an_admin_sees_counts_and_accounts_but_never_other_peoples_data(client, db):
    admin = register_and_login(client, "boss@example.com")
    _make_admin(db, "boss@example.com")
    other = register_and_login(client, "someone@example.com")
    upload_id = client.post("/api/uploads", headers=other, files=csv_file()).json()["upload_id"]

    overview = client.get("/api/admin/overview", headers=admin).json()
    assert overview["users_total"] == 2 and overview["users_by_role"] == {"admin": 1, "user": 1}
    assert overview["uploads_total"] == 1 and overview["uploads_last_7_days"] == 1
    users = {u["email"]: u for u in client.get("/api/admin/users", headers=admin).json()}
    assert users["someone@example.com"]["upload_count"] == 1
    assert set(users["someone@example.com"]) == {"id", "email", "role", "is_active", "created_at", "upload_count"}  # no financial fields
    # the admin is still just another user as far as someone else's analysis is concerned
    for path in ("", "/summary", "/transactions", "/anomalies"):
        assert client.get(f"/api/uploads/{upload_id}{path}", headers=admin).status_code == 404
    assert client.delete(f"/api/uploads/{upload_id}", headers=admin).status_code == 404


def test_disabling_an_account_ends_its_access_and_enabling_restores_login(client, db):
    admin = register_and_login(client, "boss@example.com")
    _make_admin(db, "boss@example.com")
    victim = register_and_login(client, "victim@example.com")
    victim_id = repo.get_user_by_email(db, "victim@example.com").id

    off = client.patch(f"/api/admin/users/{victim_id}", headers=admin, json={"is_active": False})
    assert off.status_code == 200 and off.json()["is_active"] is False
    assert client.get("/api/auth/me", headers=victim).status_code == 401
    assert client.post("/api/auth/login", json={"email": "victim@example.com", "password": "correct-horse-battery"}).status_code == 401

    assert client.patch(f"/api/admin/users/{victim_id}", headers=admin, json={"is_active": True}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "victim@example.com", "password": "correct-horse-battery"}).status_code == 200


def test_an_admin_cannot_disable_themselves_another_admin_or_a_missing_account(client, db):
    admin = register_and_login(client, "boss@example.com")
    _make_admin(db, "boss@example.com")
    register_and_login(client, "second@example.com")
    _make_admin(db, "second@example.com")
    ids = {u.email: u.id for u in db.scalars(select(User)).all()}
    me = client.patch(f"/api/admin/users/{ids['boss@example.com']}", headers=admin, json={"is_active": False})
    other = client.patch(f"/api/admin/users/{ids['second@example.com']}", headers=admin, json={"is_active": False})
    assert (me.status_code, me.json()["error"]["code"]) == (409, "CANNOT_CHANGE_SELF")
    assert (other.status_code, other.json()["error"]["code"]) == (409, "CANNOT_CHANGE_ADMIN")
    assert client.patch("/api/admin/users/00000000-0000-0000-0000-000000000000", headers=admin, json={"is_active": False}).status_code == 404
