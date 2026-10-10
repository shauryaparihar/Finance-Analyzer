import hashlib
import json
import logging
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text, update

from backend.api.auth import CSRF_HEADER, REFRESH_COOKIE
from backend.core import repository as repo
from backend.core.config import Settings, settings, validate_runtime_settings
from backend.core.logging import JsonFormatter
from backend.core.models import RefreshToken
from backend.tests.conftest import PASSWORD

CSRF = {CSRF_HEADER: "1"}
EMAIL = "cookie@example.com"


@pytest.fixture
def session(client):
    """A registered user who has just logged in: the client's cookie jar now holds the refresh cookie."""
    client.cookies.clear()
    assert client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD}).status_code == 201
    response = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200
    return response


def _cookie(client) -> str:
    return client.cookies.get(REFRESH_COOKIE, path="/api/auth")


def _refresh(client, headers=None, cookie=None):
    if cookie is not None:
        client.cookies.clear()
        client.cookies.set(REFRESH_COOKIE, cookie, path="/api/auth")
    return client.post("/api/auth/refresh", headers=CSRF if headers is None else headers)


def _set_cookie_header(response) -> str:
    return next(v for k, v in response.headers.multi_items() if k.lower() == "set-cookie" and v.startswith(REFRESH_COOKIE))


# --- the cookie ---

def test_login_sets_a_refresh_cookie_scripts_cannot_read_and_the_body_does_not_contain_it(client, session):
    header = _set_cookie_header(session).lower()
    raw = _cookie(client)
    assert raw and raw not in session.text  # the long-lived secret never appears in the JSON the page can read
    assert "httponly" in header and "samesite=strict" in header and "path=/api/auth" in header
    assert f"max-age={settings.refresh_token_days * 24 * 3600}" in header
    assert "secure" not in header.replace("samesite", "")  # plain cookies in local development


def test_the_cookie_is_marked_secure_when_secure_cookies_are_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "cookie_secure", True)
    client.cookies.clear()
    client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
    response = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert "; secure" in _set_cookie_header(response).lower()


def test_production_refuses_to_start_without_secure_cookies():
    good = dict(environment="production", jwt_secret="x" * 40, frontend_url="https://app.example.com")
    validate_runtime_settings(Settings(**good))
    with pytest.raises(RuntimeError, match="COOKIE_SECURE"):
        validate_runtime_settings(Settings(**good, cookie_secure=False))


def test_only_a_hash_of_the_refresh_token_is_stored(client, session, db):
    raw = _cookie(client)
    stored = db.scalars(select(RefreshToken.token_hash)).all()
    assert stored == [hashlib.sha256(raw.encode()).hexdigest()]
    assert raw not in str(stored)


def test_the_access_token_is_short_lived(session):
    assert session.json()["expires_in"] == settings.access_token_expire_minutes * 60 == 900


# --- rotation ---

def test_refreshing_returns_a_working_access_token_and_a_new_cookie(client, session, db):
    old = _cookie(client)
    response = _refresh(client)
    assert response.status_code == 200
    new = _cookie(client)
    assert new and new != old
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}).json()["email"] == EMAIL
    rows = {r.token_hash: r for r in db.scalars(select(RefreshToken))}
    old_row, new_row = rows[hashlib.sha256(old.encode()).hexdigest()], rows[hashlib.sha256(new.encode()).hexdigest()]
    assert old_row.revoke_reason == "rotated" and old_row.replaced_by_id == new_row.id and new_row.revoked_at is None
    assert old_row.family_id == new_row.family_id


def test_the_cookie_works_repeatedly_as_long_as_each_new_one_is_used(client, session):
    for _ in range(4):
        assert _refresh(client).status_code == 200


def test_a_session_cannot_be_extended_past_its_family_limit(client, session, db):
    db.execute(update(RefreshToken).values(family_expires_at=func.now() + timedelta(hours=1)))
    db.commit()
    assert _refresh(client).status_code == 200
    newest = db.scalars(select(RefreshToken).where(RefreshToken.revoked_at.is_(None))).one()
    assert newest.expires_at <= newest.family_expires_at  # the new token's life is capped by the session's absolute limit


def test_an_expired_refresh_token_is_rejected_and_the_cookie_is_cleared(client, session, db):
    db.execute(update(RefreshToken).values(expires_at=func.now() - timedelta(minutes=1)))
    db.commit()
    response = _refresh(client)
    assert response.status_code == 401 and response.json()["error"]["code"] == "REFRESH_EXPIRED"
    assert "max-age=0" in _set_cookie_header(response).lower()


def test_a_session_past_its_absolute_limit_is_rejected(client, session, db):
    db.execute(update(RefreshToken).values(family_expires_at=func.now() - timedelta(minutes=1)))
    db.commit()
    assert _refresh(client).json()["error"]["code"] == "REFRESH_EXPIRED"


@pytest.mark.parametrize("cookie", [None, "", "garbage", "x" * 200])
def test_missing_or_made_up_tokens_are_rejected(client, cookie):
    client.cookies.clear()
    if cookie:
        client.cookies.set(REFRESH_COOKIE, cookie, path="/api/auth")
    response = client.post("/api/auth/refresh", headers=CSRF)
    assert response.status_code == 401 and response.json()["error"]["code"] == "REFRESH_INVALID"


# --- theft detection and the two-tab race ---

def test_replaying_an_old_token_revokes_the_whole_session(client, session, db):
    stolen = _cookie(client)
    assert _refresh(client).status_code == 200  # the real user rotates it
    legitimate_next = _cookie(client)
    db.execute(update(RefreshToken).where(RefreshToken.revoke_reason == "rotated").values(revoked_at=func.now() - timedelta(minutes=5)))
    db.commit()

    replay = _refresh(client, cookie=stolen)  # an attacker presents the copied, already-used token later
    assert replay.status_code == 401 and replay.json()["error"]["code"] == "REFRESH_REUSED"
    assert db.scalar(select(func.count()).select_from(RefreshToken).where(RefreshToken.revoked_at.is_(None))) == 0
    assert _refresh(client, cookie=legitimate_next).status_code == 401  # the real user's newest token died too


def test_a_second_tab_refreshing_at_the_same_moment_is_a_retryable_race_not_theft(client, session, db):
    previous = _cookie(client)
    assert _refresh(client).status_code == 200
    newest = _cookie(client)
    response = _refresh(client, cookie=previous)  # arrives within the grace window
    assert response.status_code == 401 and response.json()["error"]["code"] == "REFRESH_RACE"
    assert "set-cookie" not in {k.lower() for k in response.headers.keys()}  # the winner's new cookie is left alone
    assert _refresh(client, cookie=newest).status_code == 200  # the session is intact


def test_a_logged_out_token_cannot_be_used_again(client, session):
    old = _cookie(client)
    assert client.post("/api/auth/logout", headers=CSRF).status_code == 204
    assert _refresh(client, cookie=old).json()["error"]["code"] == "REFRESH_INVALID"


# --- logout ---

def test_logout_revokes_the_session_clears_the_cookie_and_works_without_one(client, session, db):
    response = client.post("/api/auth/logout", headers=CSRF)
    assert response.status_code == 204 and "max-age=0" in _set_cookie_header(response).lower()
    assert db.scalar(select(func.count()).select_from(RefreshToken).where(RefreshToken.revoked_at.is_(None))) == 0
    client.cookies.clear()
    assert client.post("/api/auth/logout", headers=CSRF).status_code == 204


def test_one_login_session_ending_does_not_end_another(client, db):
    client.cookies.clear()
    client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
    client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    first = _cookie(client)
    client.cookies.clear()
    client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})  # a second device/browser
    second = _cookie(client)
    client.post("/api/auth/logout", headers=CSRF)  # logs out the second session only
    assert _refresh(client, cookie=first).status_code == 200
    assert _refresh(client, cookie=second).status_code == 401


# --- accounts ---

def test_a_disabled_account_cannot_refresh(client, session, db):
    user = repo.get_user_by_email(db, EMAIL)
    user.is_active = False
    db.commit()
    assert _refresh(client).json()["error"]["code"] == "REFRESH_INVALID"
    assert db.scalar(select(func.count()).select_from(RefreshToken).where(RefreshToken.revoked_at.is_(None))) == 0


def test_a_cookie_only_ever_gives_tokens_for_its_own_user(client, db):
    for name in ("a", "b"):
        client.cookies.clear()
        client.post("/api/auth/register", json={"email": f"{name}@example.com", "password": PASSWORD})
        client.post("/api/auth/login", json={"email": f"{name}@example.com", "password": PASSWORD})
        token = _refresh(client).json()["access_token"]
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["email"] == f"{name}@example.com"


def test_deleting_a_user_removes_their_sessions(client, session, db):
    db.execute(text("DELETE FROM users"))
    db.commit()
    assert db.scalar(select(func.count()).select_from(RefreshToken)) == 0


# --- protection against requests from other sites ---

def test_refresh_and_logout_require_the_custom_header(client, session):
    for path in ("/api/auth/refresh", "/api/auth/logout"):
        response = client.post(path)
        assert response.status_code == 403 and response.json()["error"]["code"] == "CSRF_REJECTED"
        assert client.post(path, headers={CSRF_HEADER: "0"}).status_code == 403


def test_a_request_from_an_unknown_website_is_rejected_even_with_the_header(client, session):
    for path in ("/api/auth/refresh", "/api/auth/logout"):
        response = client.post(path, headers={**CSRF, "Origin": "https://evil.example"})
        assert response.status_code == 403 and response.json()["error"]["code"] == "CSRF_REJECTED"
    assert _refresh(client, headers={**CSRF, "Origin": "http://localhost:5173"}).status_code == 200  # our own frontend


def test_the_refresh_cookie_is_not_sent_to_data_endpoints_and_is_not_an_access_credential(client, session):
    assert client.get("/api/uploads").status_code == 401  # holding the cookie alone is not enough to read data
    assert client.get("/api/budgets", headers={"Authorization": f"Bearer {_cookie(client)}"}).status_code == 401


# --- logs ---

def test_refresh_tokens_and_cookies_never_reach_the_logs(client, session, caplog):
    caplog.set_level(logging.INFO)
    first = _cookie(client)
    _refresh(client)
    second = _cookie(client)
    _refresh(client, cookie=first)  # a replay: logged as a security event
    text_ = json.dumps([json.loads(JsonFormatter().format(r)) for r in caplog.records if r.name.startswith("finsight")])
    assert "refresh_token_rotated" in text_
    for secret in (first, second, REFRESH_COOKIE):
        assert secret not in text_
