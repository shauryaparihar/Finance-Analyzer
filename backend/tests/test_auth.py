import uuid
from datetime import timedelta

import jwt

from backend.core import repository as repo
from backend.core.config import DEV_JWT_SECRET
from backend.core.security import create_access_token
from backend.tests.conftest import PASSWORD, register_and_login


def test_register_succeeds_and_never_returns_the_password(client):
    response = client.post("/api/auth/register", json={"email": "New@Example.com", "password": PASSWORD})
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert "password" not in response.text and "hash" not in response.text


def test_password_is_stored_as_an_argon2_hash(client, db):
    register_and_login(client, "hash@example.com")
    stored = repo.get_user_by_email(db, "hash@example.com").password_hash
    assert stored.startswith("$argon2") and PASSWORD not in stored


def test_duplicate_email_is_rejected_case_insensitively(client):
    register_and_login(client, "dup@example.com")
    response = client.post("/api/auth/register", json={"email": "DUP@example.com", "password": PASSWORD})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


def test_register_rejects_bad_email_and_short_password(client):
    assert client.post("/api/auth/register", json={"email": "nope", "password": PASSWORD}).status_code == 422
    short = client.post("/api/auth/register", json={"email": "a@example.com", "password": "short"})
    assert short.status_code == 422
    assert "short" not in short.text.replace("shortest", "")  # submitted password is never echoed back


def test_login_succeeds_with_correct_password(client):
    register_and_login(client, "login@example.com")
    response = client.post("/api/auth/login", json={"email": "LOGIN@example.com", "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer" and response.json()["expires_in"] == 900


def test_wrong_password_and_unknown_email_get_the_same_answer(client):
    register_and_login(client, "who@example.com")
    wrong = client.post("/api/auth/login", json={"email": "who@example.com", "password": "wrong-password"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_me_returns_the_logged_in_user(client):
    headers = register_and_login(client, "me@example.com")
    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200 and response.json()["email"] == "me@example.com"


def test_missing_token_is_rejected(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"
    assert response.headers["www-authenticate"] == "Bearer"


def test_garbage_and_tampered_tokens_are_rejected(client):
    headers = register_and_login(client, "tamper@example.com")
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    token = headers["Authorization"].split()[1]
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert response.status_code == 401 and response.json()["error"]["code"] == "TOKEN_INVALID"


def test_expired_token_is_rejected(client):
    register_and_login(client, "old@example.com")
    user_id = client.get("/api/auth/me", headers=register_and_login(client, "old2@example.com")).json()["id"]
    expired = create_access_token(uuid.UUID(user_id), expires_delta=timedelta(minutes=-1))
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401 and response.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_token_signed_with_another_secret_or_algorithm_none_is_rejected(client):
    uid = str(uuid.uuid4())
    wrong_secret = jwt.encode({"sub": uid, "exp": 9999999999}, "some-other-secret-of-sufficient-length-123", "HS256")
    no_alg = jwt.encode({"sub": uid, "exp": 9999999999}, None, algorithm="none")
    for token in (wrong_secret, no_alg):
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_token_for_a_deleted_or_inactive_user_is_rejected(client, db):
    headers = register_and_login(client, "gone@example.com")
    user = repo.get_user_by_email(db, "gone@example.com")
    user.is_active = False
    db.commit()
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    ghost = create_access_token(uuid.uuid4())
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {ghost}"}).status_code == 401


def test_token_without_expiry_is_rejected(client):
    token = jwt.encode({"sub": str(uuid.uuid4())}, DEV_JWT_SECRET, "HS256")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
