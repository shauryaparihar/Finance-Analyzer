import time
from urllib.parse import parse_qs, urlparse

import pytest

from backend.api.auth import REFRESH_COOKIE
from backend.core import google_oauth
from backend.core import repository as repo
from backend.core.config import settings
from backend.tests.conftest import PASSWORD, register_and_login

CLIENT_ID = "test-client-id.apps.googleusercontent.com"


@pytest.fixture
def google_on(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")


def _claims(nonce_value, **over):
    base = {
        "iss": "https://accounts.google.com", "aud": CLIENT_ID, "exp": int(time.time()) + 300, "nonce": nonce_value,
        "sub": "google-user-1", "email": "Person@Gmail.com", "email_verified": True,
    }
    return {**base, **over}


def _start(client):
    response = client.get("/api/auth/google/login", follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    return response, {k: v[0] for k, v in query.items()}


def _finish(client, monkeypatch, query, **claim_overrides):
    monkeypatch.setattr(google_oauth, "exchange_code", lambda code, verifier: _claims(query["nonce"], **claim_overrides))
    return client.get("/api/auth/google/callback", params={"code": "one-time-code", "state": query["state"]}, follow_redirects=False)


def test_google_sign_in_does_not_exist_until_it_is_configured(client):
    assert client.get("/api/auth/google/login", follow_redirects=False).status_code == 404
    assert client.get("/api/auth/providers").json() == {"google": False, "demo": False, "email": False}


def test_the_sign_in_address_uses_pkce_state_and_the_websites_own_callback(client, google_on):
    response, query = _start(client)
    assert response.headers["location"].startswith("https://accounts.google.com/")
    assert query["client_id"] == CLIENT_ID and query["response_type"] == "code" and query["code_challenge_method"] == "S256"
    assert query["redirect_uri"] == f"{settings.frontend_url.rstrip('/')}/api/auth/google/callback"
    assert len(query["state"]) >= 24 and len(query["nonce"]) >= 24
    flow = google_oauth.read_flow_cookie(client.cookies.get(google_oauth.FLOW_COOKIE))
    assert query["code_challenge"] == google_oauth.pkce_challenge(flow["verifier"])  # only this server knows the verifier
    assert client.get("/api/auth/providers").json()["google"] is True
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie and "path=/api/auth/google" in set_cookie


def test_a_new_person_gets_an_ordinary_account_and_a_working_session(client, google_on, monkeypatch, db):
    _, query = _start(client)
    done = _finish(client, monkeypatch, query)
    assert done.status_code == 302 and done.headers["location"] == "/"
    assert "httponly" in done.headers["set-cookie"].lower()
    token = client.post("/api/auth/refresh", headers={"X-FinSight-Request": "1"}).json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["email"] == "person@gmail.com" and me["role"] == "user"
    user = repo.get_user_by_email(db, "person@gmail.com")
    assert user.google_sub == "google-user-1" and user.password_hash == repo.UNUSABLE_PASSWORD_HASH
    assert client.post("/api/auth/login", json={"email": "person@gmail.com", "password": PASSWORD}).status_code == 401  # no password exists


def test_signing_in_again_finds_the_same_account(client, google_on, monkeypatch, db):
    for _ in range(2):
        client.cookies.clear()
        _, query = _start(client)
        assert _finish(client, monkeypatch, query).headers["location"] == "/"
    assert len(repo.admin_list_users(db)) == 1


def test_linking_to_a_password_account_switches_the_password_off_and_ends_old_sessions(client, google_on, monkeypatch, db):
    # someone registered this email first and never proved they own it
    old_headers = register_and_login(client, "person@gmail.com")
    old_cookie = client.cookies.get(REFRESH_COOKIE)
    client.cookies.clear()
    _, query = _start(client)
    assert _finish(client, monkeypatch, query).headers["location"] == "/"
    assert client.post("/api/auth/login", json={"email": "person@gmail.com", "password": PASSWORD}).status_code == 401
    client.cookies.set(REFRESH_COOKIE, old_cookie, path="/api/auth")
    assert client.post("/api/auth/refresh", headers={"X-FinSight-Request": "1"}).status_code == 401  # their old session is gone
    assert old_headers  # (the old access token simply expires on its own within minutes)


@pytest.mark.parametrize(
    "override",
    [
        {"email_verified": False}, {"aud": "someone-elses-app"}, {"iss": "https://evil.example"}, {"exp": 1},
        {"nonce": "not-the-nonce"}, {"sub": ""},
    ],
)
def test_a_bad_google_answer_is_refused(client, google_on, monkeypatch, db, override):
    _, query = _start(client)
    done = _finish(client, monkeypatch, query, **override)
    assert done.status_code == 302 and done.headers["location"] == "/login?google=failed"
    assert repo.admin_list_users(db) == []
    assert REFRESH_COOKIE not in client.cookies


def test_a_forged_or_missing_state_is_refused(client, google_on, monkeypatch, db):
    _, query = _start(client)
    monkeypatch.setattr(google_oauth, "exchange_code", lambda code, verifier: _claims(query["nonce"]))
    wrong = client.get("/api/auth/google/callback", params={"code": "c", "state": "forged"}, follow_redirects=False)
    assert wrong.headers["location"] == "/login?google=failed"
    client.cookies.clear()  # an attacker's link opened in a browser that never started the flow
    nocookie = client.get("/api/auth/google/callback", params={"code": "c", "state": query["state"]}, follow_redirects=False)
    assert nocookie.headers["location"] == "/login?google=failed"
    refused = client.get("/api/auth/google/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert refused.headers["location"] == "/login?google=failed"
    assert repo.admin_list_users(db) == []


def test_a_disabled_account_cannot_sign_in_with_google(client, google_on, monkeypatch, db):
    _, query = _start(client)
    _finish(client, monkeypatch, query)
    user = repo.get_user_by_email(db, "person@gmail.com")
    repo.set_user_active(db, user.id, False)
    client.cookies.clear()
    _, query = _start(client)
    assert _finish(client, monkeypatch, query).headers["location"] == "/login?google=failed"


def test_the_demo_account_cannot_be_taken_over_through_google(client, google_on, monkeypatch, db):
    repo.get_or_create_demo_user(db)
    _, query = _start(client)
    done = _finish(client, monkeypatch, query, email=repo.DEMO_EMAIL)
    assert done.headers["location"] == "/login?google=failed"
